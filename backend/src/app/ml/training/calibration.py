"""Probability calibration analysis using walk-forward out-of-sample predictions.

Uses exclusively OOS data produced by temporal walk-forward folds.
Calibrators are fit only on past OOS data relative to each evaluation period.
Does not modify production model artifacts or public model selection.
"""

from __future__ import annotations

import json
import logging
import pickle
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import numpy as np
import pandas as pd

from backend.src.app.ml.model_versioning import (
    MODEL_VERSIONS,
    PROCESSED_DATA_DIR,
    REPORTS_DIR,
    ModelVersion,
    calibrator_artifact_path,
    select_training_dataset_path,
)
from backend.src.app.ml.training.train_baseline import TARGET_COLUMN
from backend.src.app.ml.training.walk_forward import (
    MODEL_NAMES,
    WalkForwardConfig,
    WalkForwardFoldSpec,
    generate_walk_forward_folds,
    prepare_temporal_dataframe,
    slice_fold_frames,
)
from backend.src.app.services.background_job import BackgroundJobCancelled

logger = logging.getLogger(__name__)

PrepareProgressCallback = Callable[[str], None]
ProgressCallback = Callable[[str, int, int], None]
ShouldCancel = Callable[[], bool]

CalibrationMethod = Literal["raw", "platt", "isotonic"]
CALIBRATION_METHODS: tuple[CalibrationMethod, ...] = ("raw", "platt", "isotonic")
CALIBRATION_REPORTS_DIR = REPORTS_DIR / "calibration"

DEFAULT_N_BINS = 10
DEFAULT_MIN_BIN_SAMPLES = 30
DEFAULT_MIN_CALIBRATOR_TRAIN_SAMPLES = 100


@dataclass(frozen=True)
class CalibrationConfig:
    """Configuration for calibration analysis (inherits walk-forward windows)."""

    n_bins: int = DEFAULT_N_BINS
    min_bin_samples: int = DEFAULT_MIN_BIN_SAMPLES
    min_calibrator_train_samples: int = DEFAULT_MIN_CALIBRATOR_TRAIN_SAMPLES
    methods: tuple[CalibrationMethod, ...] = CALIBRATION_METHODS
    walk_forward: WalkForwardConfig = field(default_factory=WalkForwardConfig)

    def validate(self) -> None:
        self.walk_forward.validate()
        if self.n_bins < 2:
            raise ValueError("n_bins deve essere >= 2.")
        if self.min_bin_samples < 1:
            raise ValueError("min_bin_samples deve essere >= 1.")
        if self.min_calibrator_train_samples < 2:
            raise ValueError("min_calibrator_train_samples deve essere >= 2.")
        for method in self.methods:
            if method not in CALIBRATION_METHODS:
                raise ValueError(f"Metodo calibrazione non supportato: {method}")


@dataclass
class ReliabilityBin:
    bin_index: int
    bin_start: float
    bin_end: float
    count: int
    mean_predicted: float | None
    mean_actual: float | None
    calibration_gap: float | None
    insufficient_sample: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CalibrationMetrics:
    brier_score: float | None
    log_loss: float | None
    ece: float | None
    mce: float | None
    n_samples: int
    reliability_bins: list[ReliabilityBin]

    def to_dict(self) -> dict[str, Any]:
        return {
            "brier_score": self.brier_score,
            "log_loss": self.log_loss,
            "ece": self.ece,
            "mce": self.mce,
            "n_samples": self.n_samples,
            "reliability_bins": [item.to_dict() for item in self.reliability_bins],
        }


@dataclass
class OosPredictionBatch:
    fold_index: int
    test_start: date
    test_end: date
    y_true: np.ndarray
    prob_raw: np.ndarray
    match_dates: np.ndarray

    @property
    def n_samples(self) -> int:
        return int(len(self.y_true))


@dataclass
class FoldCalibrationOutcome:
    fold_index: int
    test_start: str
    test_end: str
    n_samples: int
    calibrator_train_samples: int
    methods: dict[str, CalibrationMetrics]
    skip_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold_index": self.fold_index,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "n_samples": self.n_samples,
            "calibrator_train_samples": self.calibrator_train_samples,
            "methods": {key: value.to_dict() for key, value in self.methods.items()},
            "skip_reason": self.skip_reason,
        }


@dataclass
class ModelCalibrationResult:
    model_version: str
    model_name: str
    dataset_path: str
    date_min: str | None
    date_max: str | None
    oos_samples_total: int
    fold_outcomes: list[FoldCalibrationOutcome]
    aggregate: dict[str, CalibrationMetrics]
    comparison: dict[str, Any]
    artifacts: dict[str, str]
    leakage_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "model_name": self.model_name,
            "dataset_path": self.dataset_path,
            "date_min": self.date_min,
            "date_max": self.date_max,
            "oos_samples_total": self.oos_samples_total,
            "fold_outcomes": [item.to_dict() for item in self.fold_outcomes],
            "aggregate": {key: value.to_dict() for key, value in self.aggregate.items()},
            "comparison": self.comparison,
            "artifacts": self.artifacts,
            "leakage_flags": self.leakage_flags,
        }


@dataclass
class CalibrationRunResult:
    config: CalibrationConfig
    started_at: str
    finished_at: str
    walk_forward_run_id: int | None
    models: list[ModelCalibrationResult]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": {
                "n_bins": self.config.n_bins,
                "min_bin_samples": self.config.min_bin_samples,
                "min_calibrator_train_samples": self.config.min_calibrator_train_samples,
                "methods": list(self.config.methods),
                "walk_forward": asdict(self.config.walk_forward),
            },
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "walk_forward_run_id": self.walk_forward_run_id,
            "models": [item.to_dict() for item in self.models],
            "summary": self.summary,
        }


def _round_metric(value: float | None, digits: int = 6) -> float | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return round(float(value), digits)


def compute_brier_score(y_true: np.ndarray, y_prob: np.ndarray) -> float | None:
    if len(y_true) == 0:
        return None
    from sklearn.metrics import brier_score_loss

    return _round_metric(brier_score_loss(y_true, y_prob))


def compute_log_loss(y_true: np.ndarray, y_prob: np.ndarray) -> float | None:
    if len(y_true) == 0:
        return None
    from sklearn.metrics import log_loss

    clipped = np.clip(y_prob, 1e-15, 1 - 1e-15)
    try:
        return _round_metric(log_loss(y_true, clipped, labels=[0, 1]))
    except ValueError:
        return None


def compute_reliability_bins(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    *,
    n_bins: int = DEFAULT_N_BINS,
    min_bin_samples: int = DEFAULT_MIN_BIN_SAMPLES,
) -> list[ReliabilityBin]:
    if len(y_true) == 0:
        return []
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins: list[ReliabilityBin] = []
    for index in range(n_bins):
        start = float(edges[index])
        end = float(edges[index + 1])
        if index == n_bins - 1:
            mask = (y_prob >= start) & (y_prob <= end)
        else:
            mask = (y_prob >= start) & (y_prob < end)
        count = int(mask.sum())
        insufficient = count < min_bin_samples
        if count == 0:
            bins.append(
                ReliabilityBin(
                    bin_index=index,
                    bin_start=start,
                    bin_end=end,
                    count=0,
                    mean_predicted=None,
                    mean_actual=None,
                    calibration_gap=None,
                    insufficient_sample=True,
                )
            )
            continue
        mean_pred = float(np.mean(y_prob[mask]))
        mean_actual = float(np.mean(y_true[mask]))
        gap = abs(mean_pred - mean_actual)
        bins.append(
            ReliabilityBin(
                bin_index=index,
                bin_start=start,
                bin_end=end,
                count=count,
                mean_predicted=_round_metric(mean_pred),
                mean_actual=_round_metric(mean_actual),
                calibration_gap=_round_metric(gap),
                insufficient_sample=insufficient,
            )
        )
    return bins


def expected_calibration_error(bins: list[ReliabilityBin], total_samples: int) -> float | None:
    if total_samples <= 0:
        return None
    weighted = 0.0
    used = 0
    for item in bins:
        if item.calibration_gap is None or item.count == 0:
            continue
        weighted += item.count * item.calibration_gap
        used += item.count
    if used == 0:
        return None
    return _round_metric(weighted / used)


def maximum_calibration_error(bins: list[ReliabilityBin]) -> float | None:
    gaps = [item.calibration_gap for item in bins if item.calibration_gap is not None]
    if not gaps:
        return None
    return _round_metric(max(gaps))


def compute_calibration_metrics(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    *,
    n_bins: int = DEFAULT_N_BINS,
    min_bin_samples: int = DEFAULT_MIN_BIN_SAMPLES,
) -> CalibrationMetrics:
    bins = compute_reliability_bins(
        y_true,
        y_prob,
        n_bins=n_bins,
        min_bin_samples=min_bin_samples,
    )
    n_samples = int(len(y_true))
    return CalibrationMetrics(
        brier_score=compute_brier_score(y_true, y_prob),
        log_loss=compute_log_loss(y_true, y_prob),
        ece=expected_calibration_error(bins, n_samples),
        mce=maximum_calibration_error(bins),
        n_samples=n_samples,
        reliability_bins=bins,
    )


def fit_platt_calibrator(y_true: np.ndarray, y_prob: np.ndarray) -> Any:
    from sklearn.linear_model import LogisticRegression

    clipped = np.clip(y_prob, 1e-6, 1 - 1e-6).reshape(-1, 1)
    model = LogisticRegression(max_iter=1000, solver="lbfgs")
    model.fit(clipped, y_true)
    return model


def fit_isotonic_calibrator(y_true: np.ndarray, y_prob: np.ndarray) -> Any:
    from sklearn.isotonic import IsotonicRegression

    model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    model.fit(y_prob, y_true)
    return model


def apply_calibrator(method: CalibrationMethod, calibrator: Any, y_prob: np.ndarray) -> np.ndarray:
    if method == "raw":
        return np.asarray(y_prob, dtype=float)
    if method == "platt":
        clipped = np.clip(y_prob, 1e-6, 1 - 1e-6).reshape(-1, 1)
        return calibrator.predict_proba(clipped)[:, 1]
    if method == "isotonic":
        return calibrator.predict(y_prob)
    raise ValueError(f"Metodo non supportato: {method}")


def fit_calibrator(method: CalibrationMethod, y_true: np.ndarray, y_prob: np.ndarray) -> Any | None:
    if method == "raw":
        return None
    if len(y_true) < 2 or len(np.unique(y_true)) < 2:
        return None
    if method == "platt":
        return fit_platt_calibrator(y_true, y_prob)
    if method == "isotonic":
        return fit_isotonic_calibrator(y_true, y_prob)
    raise ValueError(f"Metodo non supportato: {method}")


def _extract_oos_batch(
    fold: WalkForwardFoldSpec,
    train: pd.DataFrame,
    test: pd.DataFrame,
    *,
    model_version: str,
    dataset_path: str,
    config: WalkForwardConfig,
    model_name: str,
) -> OosPredictionBatch | None:
    from sklearn.pipeline import Pipeline

    from backend.src.app.ml.training.walk_forward import (
        _estimators,
        detect_leakage_flags,
        selected_feature_columns,
    )
    from backend.src.app.ml.training.train_baseline import build_preprocessor

    if len(train) < config.min_train_rows or len(test) < config.min_test_rows:
        return None
    feature_columns = selected_feature_columns(train, model_version=model_version)
    y_train = train[TARGET_COLUMN].astype(int)
    y_test = test[TARGET_COLUMN].astype(int)
    if y_train.nunique() < 2 or y_test.nunique() < 2:
        return None
    estimators = _estimators(config.random_state)
    if model_name not in estimators:
        return None
    detect_leakage_flags(
        feature_columns,
        fold,
        model_version=model_version,
        train=train,
        test=test,
    )
    pipeline = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor(train, feature_columns)),
            ("model", estimators[model_name]),
        ]
    )
    pipeline.fit(train[feature_columns], y_train)
    prob_raw = pipeline.predict_proba(test[feature_columns])[:, 1]
    match_dates = pd.to_datetime(test["match_date"]).dt.date.to_numpy()
    return OosPredictionBatch(
        fold_index=fold.fold_index,
        test_start=fold.test_start,
        test_end=fold.test_end,
        y_true=y_test.to_numpy(dtype=int),
        prob_raw=np.asarray(prob_raw, dtype=float),
        match_dates=match_dates,
    )


def collect_oos_predictions_for_version(
    model_version: ModelVersion | str,
    config: WalkForwardConfig,
    *,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    model_names: tuple[str, ...] = MODEL_NAMES,
    should_cancel: ShouldCancel | None = None,
    on_fold_complete: Callable[[str], None] | None = None,
) -> dict[str, list[OosPredictionBatch]]:
    config.validate()
    dataset_path = select_training_dataset_path(processed_dir, version=model_version)  # type: ignore[arg-type]
    raw = pd.read_csv(dataset_path, low_memory=False)
    dataframe = prepare_temporal_dataframe(raw, model_version=model_version)
    folds = generate_walk_forward_folds(dataframe, config)
    batches_by_model: dict[str, list[OosPredictionBatch]] = {name: [] for name in model_names}
    for fold in folds:
        if should_cancel and should_cancel():
            raise BackgroundJobCancelled("Calibration cancelled.")
        train, test = slice_fold_frames(dataframe, fold)
        for model_name in model_names:
            batch = _extract_oos_batch(
                fold,
                train,
                test,
                model_version=model_version,
                dataset_path=str(dataset_path),
                config=config,
                model_name=model_name,
            )
            if batch is not None:
                batches_by_model[model_name].append(batch)
            if on_fold_complete:
                on_fold_complete(
                    f"{model_version} · {model_name} · OOS fold {fold.fold_index + 1}/{len(folds)}"
                )
    return batches_by_model


def _concat_batches(batches: list[OosPredictionBatch]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not batches:
        return np.array([]), np.array([]), np.array([])
    y_true = np.concatenate([item.y_true for item in batches])
    prob_raw = np.concatenate([item.prob_raw for item in batches])
    dates = np.concatenate([item.match_dates for item in batches])
    return y_true, prob_raw, dates


def assert_calibrator_train_precedes_eval(
    train_batches: list[OosPredictionBatch],
    eval_batch: OosPredictionBatch,
) -> None:
    if not train_batches:
        return
    train_max = max(item.test_end for item in train_batches)
    if train_max >= eval_batch.test_start:
        raise ValueError(
            f"Leakage calibrazione: train_max={train_max} >= eval_start={eval_batch.test_start}"
        )
    train_dates = np.concatenate([item.match_dates for item in train_batches])
    eval_dates = eval_batch.match_dates
    if len(train_dates) and len(eval_dates) and np.max(train_dates) >= np.min(eval_dates):
        raise ValueError("Leakage calibrazione: date OOS train/eval si sovrappongono.")


def evaluate_fold_calibration(
    prior_batches: list[OosPredictionBatch],
    eval_batch: OosPredictionBatch,
    config: CalibrationConfig,
) -> FoldCalibrationOutcome:
    assert_calibrator_train_precedes_eval(prior_batches, eval_batch)
    y_train, prob_train, _ = _concat_batches(prior_batches)
    methods: dict[str, CalibrationMetrics] = {}
    for method in config.methods:
        if method == "raw":
            calibrated = eval_batch.prob_raw
        else:
            if len(y_train) < config.min_calibrator_train_samples:
                methods[method] = CalibrationMetrics(
                    brier_score=None,
                    log_loss=None,
                    ece=None,
                    mce=None,
                    n_samples=eval_batch.n_samples,
                    reliability_bins=[],
                )
                continue
            calibrator = fit_calibrator(method, y_train, prob_train)
            if calibrator is None:
                methods[method] = CalibrationMetrics(
                    brier_score=None,
                    log_loss=None,
                    ece=None,
                    mce=None,
                    n_samples=eval_batch.n_samples,
                    reliability_bins=[],
                )
                continue
            calibrated = apply_calibrator(method, calibrator, eval_batch.prob_raw)
        methods[method] = compute_calibration_metrics(
            eval_batch.y_true,
            calibrated,
            n_bins=config.n_bins,
            min_bin_samples=config.min_bin_samples,
        )
    if "raw" not in methods:
        methods["raw"] = compute_calibration_metrics(
            eval_batch.y_true,
            eval_batch.prob_raw,
            n_bins=config.n_bins,
            min_bin_samples=config.min_bin_samples,
        )
    return FoldCalibrationOutcome(
        fold_index=eval_batch.fold_index,
        test_start=eval_batch.test_start.isoformat(),
        test_end=eval_batch.test_end.isoformat(),
        n_samples=eval_batch.n_samples,
        calibrator_train_samples=int(len(y_train)),
        methods=methods,
    )


def run_calibration_for_model(
    model_version: ModelVersion | str,
    config: CalibrationConfig,
    *,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    model_name: str,
    run_id: int | None = None,
    persist_artifacts: bool = True,
    should_cancel: ShouldCancel | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> ModelCalibrationResult:
    config.validate()
    wf_config = config.walk_forward
    dataset_path = select_training_dataset_path(processed_dir, version=model_version)  # type: ignore[arg-type]
    batches = collect_oos_predictions_for_version(
        model_version,
        wf_config,
        processed_dir=processed_dir,
        model_names=(model_name,),
        should_cancel=should_cancel,
        on_fold_complete=on_progress,
    )[model_name]
    leakage_flags: list[str] = []
    fold_outcomes: list[FoldCalibrationOutcome] = []
    aggregated_probs: dict[str, list[np.ndarray]] = {method: [] for method in config.methods}
    aggregated_truth: list[np.ndarray] = []

    for index, batch in enumerate(batches):
        if should_cancel and should_cancel():
            raise BackgroundJobCancelled("Calibration cancelled.")
        prior = batches[:index]
        if index == 0:
            fold_outcomes.append(
                FoldCalibrationOutcome(
                    fold_index=batch.fold_index,
                    test_start=batch.test_start.isoformat(),
                    test_end=batch.test_end.isoformat(),
                    n_samples=batch.n_samples,
                    calibrator_train_samples=0,
                    methods={
                        "raw": compute_calibration_metrics(
                            batch.y_true,
                            batch.prob_raw,
                            n_bins=config.n_bins,
                            min_bin_samples=config.min_bin_samples,
                        )
                    },
                    skip_reason="Primo fold: nessun OOS passato per addestrare calibratore.",
                )
            )
            aggregated_truth.append(batch.y_true)
            aggregated_probs["raw"].append(batch.prob_raw)
            for method in config.methods:
                if method != "raw":
                    aggregated_probs[method].append(batch.prob_raw.copy())
            continue

        outcome = evaluate_fold_calibration(prior, batch, config)
        fold_outcomes.append(outcome)
        aggregated_truth.append(batch.y_true)

        y_train, prob_train, _ = _concat_batches(prior)
        for method in config.methods:
            if method == "raw":
                aggregated_probs[method].append(batch.prob_raw)
            elif len(y_train) >= config.min_calibrator_train_samples:
                calibrator = fit_calibrator(method, y_train, prob_train)
                if calibrator is not None:
                    aggregated_probs[method].append(
                        apply_calibrator(method, calibrator, batch.prob_raw)
                    )
                else:
                    aggregated_probs[method].append(batch.prob_raw.copy())
            else:
                aggregated_probs[method].append(batch.prob_raw.copy())
        if on_progress:
            on_progress(
                f"{model_version} · {model_name} · calib fold {index + 1}/{len(batches)}"
            )

    y_all = np.concatenate(aggregated_truth) if aggregated_truth else np.array([])
    aggregate: dict[str, CalibrationMetrics] = {}
    for method in config.methods:
        probs = aggregated_probs.get(method) or []
        if probs and len(y_all):
            prob_all = np.concatenate(probs)
            aggregate[method] = compute_calibration_metrics(
                y_all,
                prob_all,
                n_bins=config.n_bins,
                min_bin_samples=config.min_bin_samples,
            )
        else:
            aggregate[method] = CalibrationMetrics(
                brier_score=None,
                log_loss=None,
                ece=None,
                mce=None,
                n_samples=0,
                reliability_bins=[],
            )

    comparison = _build_method_comparison(aggregate)
    artifacts: dict[str, str] = {}
    artifact_warnings: list[str] = []
    if persist_artifacts and run_id is not None and len(y_all) >= config.min_calibrator_train_samples:
        y_train_all, prob_train_all, _ = _concat_batches(batches)
        for method in ("platt", "isotonic"):
            if method not in config.methods:
                continue
            calibrator = fit_calibrator(method, y_train_all, prob_train_all)
            if calibrator is None:
                continue
            path = save_calibrator_artifact(
                calibrator,
                model_version=model_version,
                model_name=model_name,
                method=method,
                run_id=run_id,
            )
            if path is not None:
                artifacts[method] = str(path)
            else:
                artifact_warnings.append(f"artifact_save_failed:{method}")
    if artifact_warnings:
        comparison = {**comparison, "artifact_warnings": artifact_warnings}

    date_min = batches[0].test_start.isoformat() if batches else None
    date_max = batches[-1].test_end.isoformat() if batches else None
    return ModelCalibrationResult(
        model_version=str(model_version),
        model_name=model_name,
        dataset_path=str(dataset_path),
        date_min=date_min,
        date_max=date_max,
        oos_samples_total=int(len(y_all)),
        fold_outcomes=fold_outcomes,
        aggregate=aggregate,
        comparison=comparison,
        artifacts=artifacts,
        leakage_flags=leakage_flags,
    )


def _build_method_comparison(aggregate: dict[str, CalibrationMetrics]) -> dict[str, Any]:
    raw = aggregate.get("raw")
    if raw is None:
        return {"note": "Metriche raw non disponibili."}
    comparison: dict[str, Any] = {"raw": raw.to_dict(), "deltas": {}}
    for method, metrics in aggregate.items():
        if method == "raw":
            continue
        deltas: dict[str, float | None] = {}
        for key in ("brier_score", "log_loss", "ece", "mce"):
            raw_val = getattr(raw, key)
            cal_val = getattr(metrics, key)
            if raw_val is None or cal_val is None:
                deltas[key] = None
            else:
                deltas[key] = _round_metric(cal_val - raw_val)
        comparison["deltas"][method] = deltas
        comparison[method] = metrics.to_dict()
    comparison["note"] = (
        "Delta negativo su Brier/log_loss/ECE/MCE indica miglioramento rispetto alle probabilità grezze."
    )
    return comparison


def _count_calibration_units(
    config: CalibrationConfig,
    versions: tuple[str, ...],
    *,
    processed_dir: str | Path,
    model_names: tuple[str, ...],
    should_cancel: ShouldCancel | None = None,
    prepare_progress_callback: PrepareProgressCallback | None = None,
) -> int:
    wf = config.walk_forward
    total = 0
    version_list = [version for version in versions if version in MODEL_VERSIONS]
    for index, version in enumerate(version_list):
        if should_cancel and should_cancel():
            raise BackgroundJobCancelled("Calibration cancelled.")
        if prepare_progress_callback:
            prepare_progress_callback(
                f"Preparazione OOS · {version} ({index + 1}/{len(version_list)})"
            )
        dataset_path = select_training_dataset_path(processed_dir, version=version)  # type: ignore[arg-type]
        raw = pd.read_csv(dataset_path, low_memory=False)
        dataframe = prepare_temporal_dataframe(raw, model_version=version)
        folds = generate_walk_forward_folds(dataframe, wf)
        # OOS extraction + calibration evaluation per fold, per model.
        total += len(folds) * 2 * len(model_names)
    return total


def run_calibration_validation(
    config: CalibrationConfig,
    *,
    versions: tuple[str, ...] | None = None,
    model_names: tuple[str, ...] = MODEL_NAMES,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    walk_forward_run_id: int | None = None,
    run_id: int | None = None,
    persist_artifacts: bool = True,
    progress_callback: ProgressCallback | None = None,
    prepare_progress_callback: PrepareProgressCallback | None = None,
    should_cancel: ShouldCancel | None = None,
) -> CalibrationRunResult:
    config.validate()
    started = datetime.now(timezone.utc).isoformat()
    selected_versions = versions or tuple(MODEL_VERSIONS.keys())
    models: list[ModelCalibrationResult] = []
    if prepare_progress_callback:
        prepare_progress_callback("Conteggio unità calibrazione…")
    total_units = _count_calibration_units(
        config,
        selected_versions,
        processed_dir=processed_dir,
        model_names=model_names,
        should_cancel=should_cancel,
        prepare_progress_callback=prepare_progress_callback,
    )
    completed_units = 0

    def on_progress(phase: str) -> None:
        nonlocal completed_units
        completed_units += 1
        if progress_callback:
            progress_callback(phase, completed_units, max(total_units, 1))

    for version in selected_versions:
        if version not in MODEL_VERSIONS:
            continue
        for model_name in model_names:
            if should_cancel and should_cancel():
                raise BackgroundJobCancelled("Calibration cancelled.")
            try:
                result = run_calibration_for_model(
                    version,
                    config,
                    processed_dir=processed_dir,
                    model_name=model_name,
                    run_id=run_id,
                    persist_artifacts=persist_artifacts,
                    should_cancel=should_cancel,
                    on_progress=on_progress,
                )
                models.append(result)
            except BackgroundJobCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 — version isolation
                logger.exception("Calibration failed version=%s model=%s: %s", version, model_name, exc)
                models.append(
                    ModelCalibrationResult(
                        model_version=version,
                        model_name=model_name,
                        dataset_path="",
                        date_min=None,
                        date_max=None,
                        oos_samples_total=0,
                        fold_outcomes=[],
                        aggregate={},
                        comparison={"error": str(exc)},
                        artifacts={},
                        leakage_flags=[f"error:{exc}"],
                    )
                )
    finished = datetime.now(timezone.utc).isoformat()
    summary = _build_run_summary(models)
    return CalibrationRunResult(
        config=config,
        started_at=started,
        finished_at=finished,
        walk_forward_run_id=walk_forward_run_id,
        models=models,
        summary=summary,
    )


def _build_run_summary(models: list[ModelCalibrationResult]) -> dict[str, Any]:
    completed = [item for item in models if item.oos_samples_total > 0]
    return {
        "models_total": len(models),
        "models_with_oos": len(completed),
        "oos_samples_total": sum(item.oos_samples_total for item in completed),
        "leakage_flags_total": sum(len(item.leakage_flags) for item in models),
        "methods_compared": list(CALIBRATION_METHODS),
        "note": (
            "Calibrazione su OOS walk-forward. Non attiva automaticamente il modello pubblico."
        ),
    }


def save_calibrator_artifact(
    calibrator: Any,
    *,
    model_version: str,
    model_name: str,
    method: str,
    run_id: int,
    reports_dir: str | Path = CALIBRATION_REPORTS_DIR.parent,
) -> Path | None:
    """Persist calibrator pickle; returns None on I/O failure (metrics still kept elsewhere)."""
    path = calibrator_artifact_path(
        model_version=model_version,
        model_name=model_name,
        method=method,
        run_id=run_id,
        reports_dir=reports_dir,
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "calibrator": calibrator,
            "model_version": model_version,
            "model_name": model_name,
            "method": method,
            "run_id": run_id,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        with path.open("wb") as handle:
            pickle.dump(payload, handle)
        return path
    except OSError as exc:
        logger.warning(
            "Calibrator artifact not saved run_id=%s version=%s model=%s method=%s: %s",
            run_id,
            model_version,
            model_name,
            method,
            exc,
        )
        return None


def write_calibration_report(
    result: CalibrationRunResult,
    *,
    run_id: int | None = None,
    reports_dir: str | Path = CALIBRATION_REPORTS_DIR,
) -> Path:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"run_{run_id}_{stamp}" if run_id is not None else f"adhoc_{stamp}"
    path = reports_path / f"calibration_{suffix}.json"
    payload = result.to_dict()
    payload["report_path"] = str(path)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
    latest = reports_path / "calibration_latest.json"
    with latest.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
    return path


def calibration_result_to_dict(result: CalibrationRunResult) -> dict[str, Any]:
    return result.to_dict()
