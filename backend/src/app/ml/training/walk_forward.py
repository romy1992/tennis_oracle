"""Temporal walk-forward validation for all model versions.

Independent from the single holdout split in ``train_baseline``:
- never shuffles rows for official WF metrics;
- never overwrites ``baseline_*_metrics.json`` or production ``.pkl`` artifacts;
- never updates the live/public model selection.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from backend.src.app.ml.model_versioning import (
    MODEL_VERSIONS,
    PROCESSED_DATA_DIR,
    REPORTS_DIR,
    ModelVersion,
)
from backend.src.app.ml.training.train_baseline import (
    TARGET_COLUMN,
    build_preprocessor,
    classification_metrics,
    excluded_feature_columns,
    filter_rows_with_valid_odds,
    leakage_excluded_columns,
    market_benchmark_metrics,
    select_training_dataset,
    selected_feature_columns,
)
from backend.src.app.ml.training.value_bet_metrics import DEFAULT_EDGE_THRESHOLD


logger = logging.getLogger(__name__)

WalkForwardMode = Literal["expanding", "rolling"]
FoldStatus = Literal["completed", "skipped_insufficient_data", "skipped_single_class", "error"]

MODEL_NAMES = ("logistic_regression", "random_forest")
WALK_FORWARD_REPORTS_DIR = REPORTS_DIR / "walk_forward"

DEFAULT_INITIAL_TRAIN_DAYS = 365
DEFAULT_TEST_DAYS = 90
DEFAULT_STEP_DAYS = 90
DEFAULT_MIN_TRAIN_ROWS = 200
DEFAULT_MIN_TEST_ROWS = 50
DEFAULT_EMBARGO_DAYS = 0


@dataclass(frozen=True)
class WalkForwardConfig:
    """Window configuration for temporal walk-forward folds."""

    mode: WalkForwardMode = "expanding"
    initial_train_days: int = DEFAULT_INITIAL_TRAIN_DAYS
    test_days: int = DEFAULT_TEST_DAYS
    step_days: int = DEFAULT_STEP_DAYS
    min_train_rows: int = DEFAULT_MIN_TRAIN_ROWS
    min_test_rows: int = DEFAULT_MIN_TEST_ROWS
    embargo_days: int = DEFAULT_EMBARGO_DAYS
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD
    random_state: int = 42

    def validate(self) -> None:
        if self.mode not in ("expanding", "rolling"):
            raise ValueError("mode deve essere 'expanding' o 'rolling'.")
        if self.initial_train_days < 1:
            raise ValueError("initial_train_days deve essere >= 1.")
        if self.test_days < 1:
            raise ValueError("test_days deve essere >= 1.")
        if self.step_days < 1:
            raise ValueError("step_days deve essere >= 1.")
        if self.min_train_rows < 2:
            raise ValueError("min_train_rows deve essere >= 2.")
        if self.min_test_rows < 1:
            raise ValueError("min_test_rows deve essere >= 1.")
        if self.embargo_days < 0:
            raise ValueError("embargo_days deve essere >= 0.")


@dataclass(frozen=True)
class WalkForwardFoldSpec:
    fold_index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    mode: WalkForwardMode

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold_index": self.fold_index,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
            "mode": self.mode,
        }


@dataclass
class WalkForwardFoldOutcome:
    fold: WalkForwardFoldSpec
    model_version: str
    model_name: str
    dataset_path: str
    feature_set: list[str]
    status: FoldStatus
    train_rows: int = 0
    test_rows: int = 0
    metrics: dict[str, Any] | None = None
    market_benchmark: dict[str, Any] | None = None
    skip_reason: str | None = None
    leakage_flags: list[str] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold": self.fold.to_dict(),
            "model_version": self.model_version,
            "model_name": self.model_name,
            "dataset_path": self.dataset_path,
            "feature_set": self.feature_set,
            "status": self.status,
            "train_rows": self.train_rows,
            "test_rows": self.test_rows,
            "metrics": self.metrics,
            "market_benchmark": self.market_benchmark,
            "skip_reason": self.skip_reason,
            "leakage_flags": self.leakage_flags,
            "coverage": self.coverage,
        }


@dataclass
class WalkForwardVersionResult:
    model_version: str
    dataset_path: str
    dataset_rows: int
    date_min: str | None
    date_max: str | None
    feature_set: list[str]
    folds: list[WalkForwardFoldOutcome]
    aggregate_metrics: dict[str, Any]
    holdout_comparison: dict[str, Any] | None
    coverage: dict[str, Any]
    leakage_flags: list[str]


@dataclass
class WalkForwardRunResult:
    config: WalkForwardConfig
    started_at: str
    finished_at: str
    versions: list[WalkForwardVersionResult]
    summary: dict[str, Any]


def prepare_temporal_dataframe(
    dataframe: pd.DataFrame,
    *,
    date_column: str = "match_date",
    target_column: str = TARGET_COLUMN,
    model_version: str = "v2",
) -> pd.DataFrame:
    """Sort chronologically and drop rows without date/target. No shuffle."""
    if date_column not in dataframe.columns:
        raise ValueError(f"Colonna data mancante: {date_column}")
    if target_column not in dataframe.columns:
        raise ValueError(f"Colonna target mancante: {target_column}")

    clean = dataframe.copy()
    clean[date_column] = pd.to_datetime(clean[date_column], errors="coerce")
    clean[target_column] = pd.to_numeric(clean[target_column], errors="coerce")
    clean = clean.dropna(subset=[date_column, target_column]).sort_values(date_column).reset_index(drop=True)
    clean[target_column] = clean[target_column].astype(int)
    if model_version == "v3":
        clean = filter_rows_with_valid_odds(clean)
    return clean


def generate_walk_forward_folds(
    dataframe: pd.DataFrame,
    config: WalkForwardConfig,
    *,
    date_column: str = "match_date",
) -> list[WalkForwardFoldSpec]:
    """Build non-overlapping train→immediate-next-test fold windows."""
    config.validate()
    if date_column not in dataframe.columns:
        raise ValueError(f"Colonna data mancante: {date_column}")
    if dataframe.empty:
        return []

    dates = pd.to_datetime(dataframe[date_column], errors="coerce").dropna()
    if dates.empty:
        return []

    data_start = dates.min().date()
    data_end = dates.max().date()
    first_train_end = data_start + timedelta(days=config.initial_train_days - 1)
    if first_train_end >= data_end:
        return []

    folds: list[WalkForwardFoldSpec] = []
    train_end = first_train_end
    fold_index = 0
    max_folds = 10_000

    while fold_index < max_folds:
        test_start = train_end + timedelta(days=1 + config.embargo_days)
        if test_start > data_end:
            break
        test_end = min(test_start + timedelta(days=config.test_days - 1), data_end)

        if config.mode == "expanding":
            train_start = data_start
        else:
            train_start = train_end - timedelta(days=config.initial_train_days - 1)
            if train_start < data_start:
                train_start = data_start

        if train_start > train_end or test_start > test_end:
            break
        if train_end >= test_start:
            raise ValueError(
                f"Leakage temporale: train_end ({train_end}) >= test_start ({test_start})."
            )

        folds.append(
            WalkForwardFoldSpec(
                fold_index=fold_index,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                mode=config.mode,
            )
        )
        train_end = train_end + timedelta(days=config.step_days)
        fold_index += 1
        if test_end >= data_end and train_end + timedelta(days=1 + config.embargo_days) > data_end:
            break

    return folds


def assert_no_temporal_overlap(
    train: pd.DataFrame,
    test: pd.DataFrame,
    *,
    date_column: str = "match_date",
) -> None:
    if train.empty or test.empty:
        return
    train_max = pd.to_datetime(train[date_column]).max()
    test_min = pd.to_datetime(test[date_column]).min()
    if train_max >= test_min:
        raise ValueError(
            f"Sovrapposizione temporale train/test: train_max={train_max.date()} "
            f"test_min={test_min.date()}."
        )


def slice_fold_frames(
    dataframe: pd.DataFrame,
    fold: WalkForwardFoldSpec,
    *,
    date_column: str = "match_date",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.to_datetime(dataframe[date_column]).dt.date
    train = dataframe.loc[(dates >= fold.train_start) & (dates <= fold.train_end)].copy()
    test = dataframe.loc[(dates >= fold.test_start) & (dates <= fold.test_end)].copy()
    assert_no_temporal_overlap(train, test, date_column=date_column)
    return train, test


def detect_leakage_flags(
    feature_columns: list[str],
    fold: WalkForwardFoldSpec,
    *,
    model_version: str,
    train: pd.DataFrame,
    test: pd.DataFrame,
    date_column: str = "match_date",
) -> list[str]:
    flags: list[str] = []
    excluded = leakage_excluded_columns(model_version)
    leaked = sorted(set(feature_columns) & excluded)
    if leaked:
        flags.append(f"feature_leakage_columns:{','.join(leaked)}")
    if fold.train_end >= fold.test_start:
        flags.append("window_boundary_overlap")
    if not train.empty and not test.empty:
        train_max = pd.to_datetime(train[date_column]).max().date()
        test_min = pd.to_datetime(test[date_column]).min().date()
        if train_max >= test_min:
            flags.append("row_date_overlap")
    return flags


def _estimators(random_state: int) -> dict[str, Any]:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression

    return {
        "logistic_regression": LogisticRegression(max_iter=2000, solver="lbfgs"),
        "random_forest": RandomForestClassifier(
            n_estimators=100,
            max_depth=14,
            min_samples_leaf=20,
            random_state=random_state,
            n_jobs=-1,
        ),
    }


def evaluate_fold_models(
    train: pd.DataFrame,
    test: pd.DataFrame,
    *,
    model_version: str,
    dataset_path: str,
    fold: WalkForwardFoldSpec,
    config: WalkForwardConfig,
    model_names: tuple[str, ...] = MODEL_NAMES,
) -> list[WalkForwardFoldOutcome]:
    """Train in-memory only; do not write production model artifacts."""
    from sklearn.pipeline import Pipeline

    feature_columns = selected_feature_columns(train, model_version=model_version)
    leakage_flags = detect_leakage_flags(
        feature_columns,
        fold,
        model_version=model_version,
        train=train,
        test=test,
    )
    coverage = {
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "train_date_min": fold.train_start.isoformat(),
        "train_date_max": fold.train_end.isoformat(),
        "test_date_min": fold.test_start.isoformat(),
        "test_date_max": fold.test_end.isoformat(),
        "features_count": len(feature_columns),
    }

    outcomes: list[WalkForwardFoldOutcome] = []
    if len(train) < config.min_train_rows or len(test) < config.min_test_rows:
        reason = (
            f"Dati insufficienti: train={len(train)} (min {config.min_train_rows}), "
            f"test={len(test)} (min {config.min_test_rows})."
        )
        for model_name in model_names:
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold,
                    model_version=model_version,
                    model_name=model_name,
                    dataset_path=dataset_path,
                    feature_set=feature_columns,
                    status="skipped_insufficient_data",
                    train_rows=len(train),
                    test_rows=len(test),
                    skip_reason=reason,
                    leakage_flags=leakage_flags,
                    coverage=coverage,
                )
            )
        return outcomes

    if not feature_columns:
        for model_name in model_names:
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold,
                    model_version=model_version,
                    model_name=model_name,
                    dataset_path=dataset_path,
                    feature_set=[],
                    status="skipped_insufficient_data",
                    train_rows=len(train),
                    test_rows=len(test),
                    skip_reason="Nessuna feature pre-match disponibile.",
                    leakage_flags=leakage_flags,
                    coverage=coverage,
                )
            )
        return outcomes

    y_train = train[TARGET_COLUMN].astype(int)
    y_test = test[TARGET_COLUMN].astype(int)
    if y_train.nunique() < 2 or y_test.nunique() < 2:
        reason = "Classe singola nel train o nel test: metriche ufficiali non calcolabili."
        for model_name in model_names:
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold,
                    model_version=model_version,
                    model_name=model_name,
                    dataset_path=dataset_path,
                    feature_set=feature_columns,
                    status="skipped_single_class",
                    train_rows=len(train),
                    test_rows=len(test),
                    skip_reason=reason,
                    leakage_flags=leakage_flags,
                    coverage=coverage,
                )
            )
        return outcomes

    x_train = train[feature_columns]
    x_test = test[feature_columns]
    market = market_benchmark_metrics(test)
    estimators = _estimators(config.random_state)

    for model_name in model_names:
        if model_name not in estimators:
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold,
                    model_version=model_version,
                    model_name=model_name,
                    dataset_path=dataset_path,
                    feature_set=feature_columns,
                    status="error",
                    train_rows=len(train),
                    test_rows=len(test),
                    skip_reason=f"Modello sconosciuto: {model_name}",
                    leakage_flags=leakage_flags,
                    coverage=coverage,
                )
            )
            continue
        try:
            pipeline = Pipeline(
                steps=[
                    ("preprocessor", build_preprocessor(train, feature_columns)),
                    ("model", estimators[model_name]),
                ]
            )
            pipeline.fit(x_train, y_train)
            probabilities = pipeline.predict_proba(x_test)[:, 1]
            predictions = (probabilities >= 0.5).astype(int)
            metrics = classification_metrics(
                y_train,
                y_test,
                predictions,
                probabilities,
                test,
                edge_threshold=config.edge_threshold,
            )
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold,
                    model_version=model_version,
                    model_name=model_name,
                    dataset_path=dataset_path,
                    feature_set=feature_columns,
                    status="completed",
                    train_rows=len(train),
                    test_rows=len(test),
                    metrics=metrics,
                    market_benchmark=market,
                    leakage_flags=leakage_flags,
                    coverage=coverage,
                )
            )
        except Exception as exc:  # noqa: BLE001 — fold isolation
            logger.exception(
                "Walk-forward fold=%s version=%s model=%s failed: %s",
                fold.fold_index,
                model_version,
                model_name,
                exc,
            )
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold,
                    model_version=model_version,
                    model_name=model_name,
                    dataset_path=dataset_path,
                    feature_set=feature_columns,
                    status="error",
                    train_rows=len(train),
                    test_rows=len(test),
                    skip_reason=str(exc),
                    leakage_flags=leakage_flags,
                    coverage=coverage,
                )
            )
    return outcomes


def _mean_metrics(completed: list[WalkForwardFoldOutcome]) -> dict[str, Any]:
    by_model: dict[str, list[dict[str, Any]]] = {}
    for outcome in completed:
        if outcome.metrics is None:
            continue
        by_model.setdefault(outcome.model_name, []).append(outcome.metrics)

    aggregate: dict[str, Any] = {}
    metric_keys = ("accuracy", "precision", "recall", "f1", "roc_auc", "log_loss")
    for model_name, metrics_list in by_model.items():
        model_agg: dict[str, Any] = {"folds_completed": len(metrics_list)}
        for key in metric_keys:
            values = [m[key] for m in metrics_list if m.get(key) is not None]
            if not values:
                model_agg[key] = {"mean": None, "std": None, "n": 0}
                continue
            series = pd.Series(values, dtype=float)
            model_agg[key] = {
                "mean": round(float(series.mean()), 6),
                "std": round(float(series.std(ddof=0)), 6) if len(values) > 1 else 0.0,
                "n": len(values),
            }
        aggregate[model_name] = model_agg
    return aggregate


def load_holdout_metrics_for_comparison(
    model_version: str,
    reports_dir: str | Path = REPORTS_DIR,
) -> dict[str, Any] | None:
    """Read current single-split metrics without modifying them."""
    version_paths = MODEL_VERSIONS.get(model_version)  # type: ignore[arg-type]
    if version_paths is None:
        return None
    path = Path(reports_dir) / version_paths.metrics_filename
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    models = payload.get("models") or {}
    comparison: dict[str, Any] = {
        "source": "holdout_baseline",
        "metrics_path": str(path),
        "split": payload.get("split"),
        "models": {},
        "note": (
            "Confronto informativo con la validazione holdout attuale. "
            "I risultati walk-forward non sostituiscono né mescolano le metriche live."
        ),
    }
    for model_name, metrics in models.items():
        comparison["models"][model_name] = {
            "accuracy": metrics.get("accuracy"),
            "roc_auc": metrics.get("roc_auc"),
            "log_loss": metrics.get("log_loss"),
            "f1": metrics.get("f1"),
        }
    return comparison


def _fold_test_overlaps(folds: list[WalkForwardFoldSpec]) -> list[str]:
    flags: list[str] = []
    ordered = sorted(folds, key=lambda item: item.fold_index)
    for left, right in zip(ordered, ordered[1:]):
        if left.test_end >= right.test_start:
            flags.append(
                f"overlapping_test_windows:fold_{left.fold_index}_fold_{right.fold_index}"
            )
    return flags


def run_walk_forward_for_version(
    model_version: ModelVersion | str,
    config: WalkForwardConfig,
    *,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
    model_names: tuple[str, ...] = MODEL_NAMES,
) -> WalkForwardVersionResult:
    config.validate()
    dataset_path = select_training_dataset(processed_dir, model_version=model_version)
    raw = pd.read_csv(dataset_path, low_memory=False)
    dataframe = prepare_temporal_dataframe(raw, model_version=model_version)
    folds = generate_walk_forward_folds(dataframe, config)
    feature_set = selected_feature_columns(dataframe, model_version=model_version)
    outcomes: list[WalkForwardFoldOutcome] = []
    version_leakage = list(_fold_test_overlaps(folds))

    if not folds:
        version_leakage.append("no_folds_generated_insufficient_date_span")

    for fold in folds:
        train, test = slice_fold_frames(dataframe, fold)
        outcomes.extend(
            evaluate_fold_models(
                train,
                test,
                model_version=model_version,
                dataset_path=str(dataset_path),
                fold=fold,
                config=config,
                model_names=model_names,
            )
        )

    completed = [item for item in outcomes if item.status == "completed"]
    skipped = [item for item in outcomes if item.status.startswith("skipped")]
    errors = [item for item in outcomes if item.status == "error"]
    for item in outcomes:
        version_leakage.extend(item.leakage_flags)
    # de-dupe preserving order
    seen: set[str] = set()
    unique_leakage: list[str] = []
    for flag in version_leakage:
        if flag not in seen:
            seen.add(flag)
            unique_leakage.append(flag)

    coverage = {
        "folds_planned": len(folds),
        "fold_outcomes": len(outcomes),
        "completed": len(completed),
        "skipped": len(skipped),
        "errors": len(errors),
        "dataset_rows_after_filters": int(len(dataframe)),
        "features_excluded_sample": excluded_feature_columns(
            dataframe, feature_set, model_version=model_version
        )[:40],
    }

    return WalkForwardVersionResult(
        model_version=str(model_version),
        dataset_path=str(dataset_path),
        dataset_rows=int(len(dataframe)),
        date_min=_date_min(dataframe),
        date_max=_date_max(dataframe),
        feature_set=feature_set,
        folds=outcomes,
        aggregate_metrics=_mean_metrics(completed),
        holdout_comparison=load_holdout_metrics_for_comparison(
            str(model_version), reports_dir=reports_dir
        ),
        coverage=coverage,
        leakage_flags=unique_leakage,
    )


def run_walk_forward_validation(
    config: WalkForwardConfig | None = None,
    *,
    versions: tuple[str, ...] | None = None,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
    model_names: tuple[str, ...] = MODEL_NAMES,
) -> WalkForwardRunResult:
    """Run walk-forward for all (or selected) versions. Does not touch public models."""
    resolved = config or WalkForwardConfig()
    resolved.validate()
    selected_versions = versions or tuple(MODEL_VERSIONS.keys())
    started = datetime.now(timezone.utc)
    version_results: list[WalkForwardVersionResult] = []

    for version in selected_versions:
        if version not in MODEL_VERSIONS:
            raise ValueError(f"Versione modello sconosciuta: {version}")
        logger.info("Walk-forward start version=%s mode=%s", version, resolved.mode)
        version_results.append(
            run_walk_forward_for_version(
                version,
                resolved,
                processed_dir=processed_dir,
                reports_dir=reports_dir,
                model_names=model_names,
            )
        )

    finished = datetime.now(timezone.utc)
    summary = {
        "versions": [item.model_version for item in version_results],
        "folds_completed": sum(
            1 for version in version_results for fold in version.folds if fold.status == "completed"
        ),
        "folds_skipped": sum(
            1
            for version in version_results
            for fold in version.folds
            if fold.status.startswith("skipped")
        ),
        "folds_errors": sum(
            1 for version in version_results for fold in version.folds if fold.status == "error"
        ),
        "leakage_flags_total": sum(len(item.leakage_flags) for item in version_results),
        "official_metrics_shuffled": False,
        "public_model_unchanged": True,
        "holdout_metrics_unchanged": True,
    }
    return WalkForwardRunResult(
        config=resolved,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        versions=version_results,
        summary=summary,
    )


def walk_forward_result_to_dict(result: WalkForwardRunResult) -> dict[str, Any]:
    return {
        "config": asdict(result.config),
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "summary": result.summary,
        "versions": [
            {
                "model_version": version.model_version,
                "dataset_path": version.dataset_path,
                "dataset_rows": version.dataset_rows,
                "date_min": version.date_min,
                "date_max": version.date_max,
                "feature_set": version.feature_set,
                "aggregate_metrics": version.aggregate_metrics,
                "holdout_comparison": version.holdout_comparison,
                "coverage": version.coverage,
                "leakage_flags": version.leakage_flags,
                "folds": [fold.to_dict() for fold in version.folds],
            }
            for version in result.versions
        ],
    }


def write_walk_forward_report(
    result: WalkForwardRunResult,
    *,
    reports_dir: str | Path = REPORTS_DIR,
    run_id: int | None = None,
) -> Path:
    """Persist WF report under reports/walk_forward/ without touching baseline files."""
    base = Path(reports_dir) / "walk_forward"
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"walk_forward_run_{run_id or 'adhoc'}_{stamp}.json"
    path = base / filename
    latest = base / "walk_forward_latest.json"
    payload = walk_forward_result_to_dict(result)
    payload["report_kind"] = "walk_forward"
    payload["does_not_replace_holdout"] = True
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    with latest.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return path


def _date_min(dataframe: pd.DataFrame, column: str = "match_date") -> str | None:
    if column not in dataframe.columns or dataframe.empty:
        return None
    dates = pd.to_datetime(dataframe[column], errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.min().date().isoformat()


def _date_max(dataframe: pd.DataFrame, column: str = "match_date") -> str | None:
    if column not in dataframe.columns or dataframe.empty:
        return None
    dates = pd.to_datetime(dataframe[column], errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.max().date().isoformat()
