"""Temporal walk-forward validation for live models across all active markets.

Independent from the single holdout split in ``train_baseline``:
- never shuffles rows for official WF metrics;
- never overwrites ``baseline_*_metrics.json`` or production ``.pkl`` artifacts;
- never updates the live/public model selection.
Default scope is every active market/version (match-winner +
first_set_winner + over_under_games), not archived match-winner v1-v3 — see
``walk_forward_markets.ACTIVE_WALK_FORWARD_MARKET_VERSIONS``. This module
owns the match-winner (CSV-based) fold generation/evaluation primitives;
``walk_forward_markets.py`` plugs the DB-based extra markets into the same
engine to avoid a circular import (those markets' dataframe builders/fold
evaluators already import primitives FROM this module).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import pandas as pd
from sqlalchemy.orm import Session

from backend.src.app.ml.model_versioning import (
    ACTIVE_MATCH_WINNER_VERSIONS,
    MODEL_VERSIONS,
    MODELS_DIR,
    ODDS_REQUIRED_VERSIONS,
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


from backend.src.app.services.background_job import BackgroundJobCancelled

logger = logging.getLogger(__name__)

WalkForwardMode = Literal["expanding", "rolling"]
FoldStatus = Literal["completed", "skipped_insufficient_data", "skipped_single_class", "error"]

PrepareProgressCallback = Callable[[str], None]
ProgressCallback = Callable[[str, int, int], None]
ShouldCancel = Callable[[], bool]
EstimatorsFactory = Callable[[int], dict[str, Any]]

MODEL_NAMES = ("logistic_regression", "random_forest")
V4_ENSEMBLE_MODEL_NAME = "voting_ensemble"
V4_MODEL_NAMES = (*MODEL_NAMES, V4_ENSEMBLE_MODEL_NAME)
OFFICIAL_BENCHMARK_NAMES = (
    "market_favorite",
    "market_no_vig",
    "atp_ranking",
    "elo",
)
OFFICIAL_CONTENDERS = (*OFFICIAL_BENCHMARK_NAMES, *MODEL_NAMES)
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
    if model_version in ODDS_REQUIRED_VERSIONS:
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


def model_names_for_version(
    model_version: str,
    requested: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """Resolve the standard estimator set without leaking v4 into other markets."""
    if requested is not None:
        return requested
    if model_version == "v4":
        return V4_MODEL_NAMES
    return MODEL_NAMES


def make_estimators_factory_for_version(
    model_version: str,
    *,
    reports_dir: str | Path = REPORTS_DIR,
) -> EstimatorsFactory:
    """Build fresh estimators for a fold, including the live v4 ensemble."""
    if model_version != "v4":
        return _estimators

    def factory(random_state: int) -> dict[str, Any]:
        from sklearn.ensemble import VotingClassifier

        from backend.src.app.ml.training.train_v4_ensemble import build_base_estimators

        estimators = _estimators(random_state)
        base_estimators, _provenance = build_base_estimators(reports_dir)
        estimators[V4_ENSEMBLE_MODEL_NAME] = VotingClassifier(
            estimators=list(base_estimators),
            voting="soft",
            n_jobs=1,
        )
        return estimators

    return factory


def _clip_probabilities(series: pd.Series) -> pd.Series:
    return series.astype(float).clip(lower=1e-6, upper=1.0 - 1e-6)


def _safe_side_odds(value: Any) -> float | None:
    try:
        odd = float(value)
    except (TypeError, ValueError):
        return None
    if odd <= 1.0:
        return None
    return odd


def _numeric_column_or_nan(test: pd.DataFrame, column: str) -> pd.Series:
    if column not in test.columns:
        return pd.Series(float("nan"), index=test.index, dtype=float)
    return pd.to_numeric(test[column], errors="coerce")


def _series_max_drawdown(profits: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for profit in profits:
        equity += float(profit)
        if equity > peak:
            peak = equity
        drawdown = peak - equity
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    return round(float(max_drawdown), 6)


def _compute_official_metrics(
    y_true: pd.Series,
    probabilities: pd.Series,
    player_1_odds: pd.Series,
    player_2_odds: pd.Series,
) -> dict[str, Any]:
    from sklearn.metrics import accuracy_score, brier_score_loss, log_loss

    probs = _clip_probabilities(probabilities)
    predictions = (probs >= 0.5).astype(int)
    chosen_odds: list[float] = []
    profits: list[float] = []
    for pred, odd_1, odd_2, actual in zip(predictions, player_1_odds, player_2_odds, y_true):
        odd = _safe_side_odds(odd_1 if pred == 1 else odd_2)
        if odd is None:
            continue
        chosen_odds.append(odd)
        won = int(actual) == int(pred)
        profits.append(odd - 1.0 if won else -1.0)

    settled = len(profits)
    total_profit = float(sum(profits))
    roi = (total_profit / settled) if settled else None
    avg_odds = (sum(chosen_odds) / len(chosen_odds)) if chosen_odds else None

    return {
        "accuracy": round(float(accuracy_score(y_true, predictions)), 6),
        "log_loss": round(float(log_loss(y_true, probs, labels=[0, 1])), 6),
        "brier_score": round(float(brier_score_loss(y_true, probs)), 6),
        "roi": round(float(roi), 6) if roi is not None else None,
        "yield": round(float(roi), 6) if roi is not None else None,
        "max_drawdown": _series_max_drawdown(profits),
        "clv_pct": None,
        "clv_available_count": 0,
        "clv_unavailable_reason": "closing_odds_non_disponibili_nel_dataset_oos",
        "bets_settled": settled,
        "total_profit": round(total_profit, 6),
        "avg_odds": round(float(avg_odds), 6) if avg_odds is not None else None,
    }


def _market_no_vig_probabilities(test: pd.DataFrame) -> pd.Series:
    odd_1 = _numeric_column_or_nan(test, "avg_player_1_odds")
    odd_2 = _numeric_column_or_nan(test, "avg_player_2_odds")
    denom = (1.0 / odd_1) + (1.0 / odd_2)
    probs = (1.0 / odd_1) / denom
    return probs.where((odd_1 > 1.0) & (odd_2 > 1.0) & denom.notna() & (denom > 0.0))


def _market_favorite_probabilities(test: pd.DataFrame) -> pd.Series:
    odd_1 = _numeric_column_or_nan(test, "avg_player_1_odds")
    odd_2 = _numeric_column_or_nan(test, "avg_player_2_odds")
    probabilities = pd.Series(index=test.index, dtype=float)
    favorite_p1 = (odd_1 < odd_2) & odd_1.notna() & odd_2.notna()
    favorite_p2 = (odd_2 < odd_1) & odd_1.notna() & odd_2.notna()
    tie = (odd_1 == odd_2) & odd_1.notna()
    probabilities.loc[favorite_p1] = 1.0
    probabilities.loc[favorite_p2] = 0.0
    probabilities.loc[tie] = 0.5
    return probabilities


def _atp_rank_probabilities(test: pd.DataFrame) -> pd.Series:
    rank_1 = _numeric_column_or_nan(test, "player_1_atp_rank")
    rank_2 = _numeric_column_or_nan(test, "player_2_atp_rank")
    probabilities = pd.Series(index=test.index, dtype=float)
    valid = rank_1.notna() & rank_2.notna() & (rank_1 > 0) & (rank_2 > 0)
    stronger_p1 = valid & (rank_1 < rank_2)
    stronger_p2 = valid & (rank_2 < rank_1)
    tie = valid & (rank_1 == rank_2)
    probabilities.loc[stronger_p1] = 1.0
    probabilities.loc[stronger_p2] = 0.0
    probabilities.loc[tie] = 0.5
    return probabilities


def _elo_probabilities(test: pd.DataFrame) -> pd.Series:
    if "elo_diff" in test.columns:
        elo_diff = pd.to_numeric(test["elo_diff"], errors="coerce")
        probabilities = 1.0 / (1.0 + (10.0 ** (-elo_diff / 400.0)))
        return probabilities.where(elo_diff.notna())

    elo_1 = _numeric_column_or_nan(test, "player_1_elo")
    elo_2 = _numeric_column_or_nan(test, "player_2_elo")
    elo_diff = elo_1 - elo_2
    probabilities = 1.0 / (1.0 + (10.0 ** (-elo_diff / 400.0)))
    return probabilities.where(elo_1.notna() & elo_2.notna())


def _official_probability_inputs(
    test: pd.DataFrame,
    model_probabilities: dict[str, pd.Series],
) -> dict[str, pd.Series]:
    return {
        "market_favorite": _market_favorite_probabilities(test),
        "market_no_vig": _market_no_vig_probabilities(test),
        "atp_ranking": _atp_rank_probabilities(test),
        "elo": _elo_probabilities(test),
        **model_probabilities,
    }


def _evaluate_official_contenders(
    test: pd.DataFrame,
    *,
    probabilities_by_name: dict[str, pd.Series],
    contenders: tuple[str, ...] = OFFICIAL_CONTENDERS,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if TARGET_COLUMN not in test.columns:
        raise ValueError(f"Colonna target mancante: {TARGET_COLUMN}")

    y_true_all = pd.to_numeric(test[TARGET_COLUMN], errors="coerce")
    odds_1_all = _numeric_column_or_nan(test, "avg_player_1_odds")
    odds_2_all = _numeric_column_or_nan(test, "avg_player_2_odds")
    required = y_true_all.notna() & (odds_1_all > 1.0) & (odds_2_all > 1.0)

    contender_masks: dict[str, pd.Series] = {}
    for name in contenders:
        series = probabilities_by_name.get(name)
        if series is None:
            contender_masks[name] = pd.Series(False, index=test.index)
        else:
            contender_masks[name] = pd.to_numeric(series, errors="coerce").notna()

    common_mask = required.copy()
    for mask in contender_masks.values():
        common_mask &= mask

    rows_total = int(len(test))
    rows_with_required = int(required.sum())
    common_rows = int(common_mask.sum())
    rows_excluded = rows_total - common_rows
    missing_by_contender = {
        name: int((~mask & required).sum()) for name, mask in contender_masks.items()
    }
    sample_meta = {
        "rows_total_test": rows_total,
        "rows_with_required_fields": rows_with_required,
        "rows_common_official": common_rows,
        "rows_excluded_for_common_sample": rows_excluded,
        "common_sample_ratio_pct": round((common_rows / rows_total) * 100, 4) if rows_total else 0.0,
        "sample_mismatch_detected": common_rows < rows_with_required,
        "missing_rows_by_contender": missing_by_contender,
        "comparison_guard": (
            "Tutte le metriche ufficiali sono calcolate sul campione comune. "
            "Se sample_mismatch_detected=true, alcune righe sono state escluse per evitare "
            "confronti su campioni differenti."
        ),
    }

    metrics_by_contender: dict[str, dict[str, Any]] = {}
    if common_rows <= 0:
        return metrics_by_contender, sample_meta

    y_true = y_true_all.loc[common_mask].astype(int)
    odds_1 = odds_1_all.loc[common_mask]
    odds_2 = odds_2_all.loc[common_mask]
    for name in contenders:
        probs = pd.to_numeric(probabilities_by_name[name], errors="coerce").loc[common_mask]
        metrics = _compute_official_metrics(y_true, probs, odds_1, odds_2)
        metrics["official_common_sample_rows"] = common_rows
        metrics["official_sample_mismatch_detected"] = sample_meta["sample_mismatch_detected"]
        metrics_by_contender[name] = metrics
    return metrics_by_contender, sample_meta


def evaluate_fold_models(
    train: pd.DataFrame,
    test: pd.DataFrame,
    *,
    model_version: str,
    dataset_path: str,
    fold: WalkForwardFoldSpec,
    config: WalkForwardConfig,
    model_names: tuple[str, ...] = MODEL_NAMES,
    estimators_factory: EstimatorsFactory = _estimators,
) -> list[WalkForwardFoldOutcome]:
    """Train in-memory only; do not write production model artifacts.

    ``estimators_factory`` di default costruisce i due modelli ufficiali
    (logistic_regression/random_forest). Può essere sostituita (es. dagli
    script esplorativi Fase 5 per v4) per validare stimatori/ensemble diversi
    senza duplicare tutta la logica di fold/leakage/metriche di questo modulo.
    """
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
    estimators = estimators_factory(config.random_state)
    trained_probabilities: dict[str, pd.Series] = {}

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
            trained_probabilities[model_name] = pd.Series(probabilities, index=test.index)
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

    official_probabilities = _official_probability_inputs(test, trained_probabilities)
    # I "contenders" ufficiali sono i benchmark fissi + i model_names effettivamente
    # valutati in questo fold: per le chiamate standard (model_names=MODEL_NAMES,
    # default) equivale esattamente a OFFICIAL_CONTENDERS; se model_names include un
    # modello extra (es. l'ensemble esplorativo v4), anche quello riceve lo stesso
    # calcolo "official_benchmark" (bet-always sul predetto, ROI/log_loss/brier/...).
    contenders = tuple(dict.fromkeys((*OFFICIAL_BENCHMARK_NAMES, *model_names)))
    official_metrics, sample_meta = _evaluate_official_contenders(
        test,
        probabilities_by_name=official_probabilities,
        contenders=contenders,
    )

    for outcome in outcomes:
        if outcome.status != "completed":
            continue
        model_official = official_metrics.get(outcome.model_name)
        if model_official is not None:
            outcome.metrics = {**(outcome.metrics or {}), "official_benchmark": model_official}
        coverage = dict(outcome.coverage)
        coverage["official_benchmark_sample"] = sample_meta
        outcome.coverage = coverage

    completed_reference = next((item for item in outcomes if item.status == "completed"), None)
    for benchmark_name in OFFICIAL_BENCHMARK_NAMES:
        benchmark_metrics = official_metrics.get(benchmark_name)
        if completed_reference is None:
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold,
                    model_version=model_version,
                    model_name=benchmark_name,
                    dataset_path=dataset_path,
                    feature_set=feature_columns,
                    status="skipped_insufficient_data",
                    train_rows=len(train),
                    test_rows=len(test),
                    skip_reason="Nessun modello ML completato nel fold.",
                    leakage_flags=leakage_flags,
                    coverage={**coverage, "official_benchmark_sample": sample_meta},
                )
            )
            continue
        if benchmark_metrics is None:
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold,
                    model_version=model_version,
                    model_name=benchmark_name,
                    dataset_path=dataset_path,
                    feature_set=feature_columns,
                    status="skipped_insufficient_data",
                    train_rows=len(train),
                    test_rows=len(test),
                    skip_reason="Campione comune insufficiente per benchmark ufficiali.",
                    leakage_flags=leakage_flags,
                    coverage={**coverage, "official_benchmark_sample": sample_meta},
                )
            )
            continue
        outcomes.append(
            WalkForwardFoldOutcome(
                fold=fold,
                model_version=model_version,
                model_name=benchmark_name,
                dataset_path=dataset_path,
                feature_set=feature_columns,
                status="completed",
                train_rows=len(train),
                test_rows=len(test),
                metrics={"official_benchmark": benchmark_metrics},
                market_benchmark=market if benchmark_name.startswith("market_") else None,
                leakage_flags=leakage_flags,
                coverage={**coverage, "official_benchmark_sample": sample_meta},
            )
        )

    return outcomes


def _mean_metrics(completed: list[WalkForwardFoldOutcome]) -> dict[str, Any]:
    by_model: dict[str, list[dict[str, Any]]] = {}
    for outcome in completed:
        if outcome.metrics is None:
            continue
        if "accuracy" not in outcome.metrics:
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


def _aggregate_official_benchmarks(completed: list[WalkForwardFoldOutcome]) -> dict[str, Any]:
    keys = ("accuracy", "log_loss", "brier_score", "roi", "yield", "max_drawdown", "clv_pct")
    by_name: dict[str, list[dict[str, Any]]] = {}
    for outcome in completed:
        payload = (outcome.metrics or {}).get("official_benchmark")
        if isinstance(payload, dict):
            by_name.setdefault(outcome.model_name, []).append(payload)

    aggregate: dict[str, Any] = {}
    for name, entries in by_name.items():
        row: dict[str, Any] = {"folds_completed": len(entries)}
        for key in keys:
            values = [item.get(key) for item in entries if item.get(key) is not None]
            if not values:
                row[key] = {"mean": None, "std": None, "n": 0}
                continue
            series = pd.Series(values, dtype=float)
            row[key] = {
                "mean": round(float(series.mean()), 6),
                "std": round(float(series.std(ddof=0)), 6) if len(values) > 1 else 0.0,
                "n": len(values),
            }
        aggregate[name] = row
    return aggregate


def _load_extra_market_holdout_metadata(model_version: str) -> dict[str, Any] | None:
    """Read the ``model_metadata.json`` written by the extra-market final-model
    trainers (``train_first_set_winner_odds_final_model.py`` /
    ``train_over_under_games_final_model.py``), which have no holdout split
    (trained on full history) but do record training-row counts/date range."""
    path = MODELS_DIR / model_version / "model_metadata.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    return {
        "source": "extra_market_full_history_training",
        "metrics_path": str(path),
        "split": None,
        "models": {},
        "note": (
            "Nessun holdout per questo mercato: il modello di produzione è allenato "
            "su tutto lo storico disponibile. Confronto informativo con i metadati di "
            "training (righe, intervallo date). La stima OOS resta il walk-forward."
        ),
        "training_rows": metadata.get("training_rows"),
        "date_min": metadata.get("date_min"),
        "date_max": metadata.get("date_max"),
        "generated_at": metadata.get("generated_at"),
    }


def load_holdout_metrics_for_comparison(
    model_version: str,
    reports_dir: str | Path = REPORTS_DIR,
) -> dict[str, Any] | None:
    """Read current single-split metrics without modifying them."""
    version_paths = MODEL_VERSIONS.get(model_version)  # type: ignore[arg-type]
    if version_paths is None:
        return _load_extra_market_holdout_metadata(model_version)
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


def _count_planned_fold_units(
    config: WalkForwardConfig,
    versions: tuple[str, ...],
    *,
    processed_dir: str | Path,
    model_names: tuple[str, ...] | None,
    db: Session | None = None,
    should_cancel: ShouldCancel | None = None,
    prepare_progress_callback: PrepareProgressCallback | None = None,
) -> int:
    from backend.src.app.ml.training.walk_forward_markets import EXTRA_MARKET_SPECS

    total = 0
    version_list = list(versions)
    for index, version in enumerate(version_list):
        if should_cancel and should_cancel():
            raise BackgroundJobCancelled("Walk-forward cancelled.")
        if prepare_progress_callback:
            prepare_progress_callback(
                f"Preparazione fold · {version} ({index + 1}/{len(version_list)})"
            )
        if version in MODEL_VERSIONS:
            dataset_path = select_training_dataset(processed_dir, model_version=version)
            raw = pd.read_csv(dataset_path, low_memory=False)
            dataframe = prepare_temporal_dataframe(raw, model_version=version)
        elif version in EXTRA_MARKET_SPECS:
            spec = EXTRA_MARKET_SPECS[version]
            dataframe, _ = spec.load_dataframe(db, processed_dir)
        else:
            continue
        folds = generate_walk_forward_folds(dataframe, config)
        total += len(folds) * len(model_names_for_version(version, model_names))
    return total


def _finalize_version_result(
    *,
    model_version: str,
    dataset_path: str,
    dataframe: pd.DataFrame,
    folds: list[WalkForwardFoldSpec],
    outcomes: list[WalkForwardFoldOutcome],
    version_leakage: list[str],
    feature_set: list[str],
    excluded_feature_model_version: str,
    reports_dir: str | Path,
) -> WalkForwardVersionResult:
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
            dataframe, feature_set, model_version=excluded_feature_model_version
        )[:40],
    }

    aggregate_metrics = _mean_metrics(completed)
    aggregate_metrics["official_benchmarks"] = _aggregate_official_benchmarks(completed)

    return WalkForwardVersionResult(
        model_version=model_version,
        dataset_path=dataset_path,
        dataset_rows=int(len(dataframe)),
        date_min=_date_min(dataframe),
        date_max=_date_max(dataframe),
        feature_set=feature_set,
        folds=outcomes,
        aggregate_metrics=aggregate_metrics,
        holdout_comparison=load_holdout_metrics_for_comparison(
            model_version, reports_dir=reports_dir
        ),
        coverage=coverage,
        leakage_flags=unique_leakage,
    )


def _run_walk_forward_for_market_version(
    version: str,
    config: WalkForwardConfig,
    *,
    db: Session | None,
    processed_dir: str | Path,
    reports_dir: str | Path,
    progress_callback: ProgressCallback | None,
    should_cancel: ShouldCancel | None,
    estimators_factory: EstimatorsFactory,
) -> WalkForwardVersionResult:
    """Extra-market (non match-winner) counterpart of ``run_walk_forward_for_version``.

    Reuses the dataframe builder + fold evaluator already built for this
    market in ``train_first_set_winner_odds.py`` / ``train_over_under_games.py``
    (see ``walk_forward_markets.EXTRA_MARKET_SPECS``), just plugged into the
    same fold-generation/persistence pipeline as match-winner versions.
    """
    from backend.src.app.ml.training.walk_forward_markets import EXTRA_MARKET_SPECS

    spec = EXTRA_MARKET_SPECS.get(version)
    if spec is None:
        raise ValueError(f"Versione/mercato walk-forward sconosciuto: {version}")
    if db is None:
        raise ValueError(f"Walk-forward per '{version}' richiede una sessione DB.")

    dataframe, dataset_path = spec.load_dataframe(db, processed_dir)
    folds = generate_walk_forward_folds(dataframe, config)
    feature_set = selected_feature_columns(dataframe, model_version="v3") + [
        column for column in spec.feature_columns_extra if column in dataframe.columns
    ]
    outcomes: list[WalkForwardFoldOutcome] = []
    version_leakage = list(_fold_test_overlaps(folds))
    if not folds:
        version_leakage.append("no_folds_generated_insufficient_date_span")

    for fold in folds:
        if should_cancel and should_cancel():
            raise BackgroundJobCancelled("Walk-forward cancelled.")
        train, test = slice_fold_frames(dataframe, fold)
        outcomes.extend(
            spec.evaluate_fold(
                train,
                test,
                dataset_path=str(dataset_path),
                fold=fold,
                config=config,
                estimators_factory=estimators_factory,
            )
        )
        if progress_callback:
            progress_callback(
                f"{version} · fold {fold.fold_index + 1}/{len(folds)}",
                len(MODEL_NAMES),
                len(folds),
            )

    return _finalize_version_result(
        model_version=version,
        dataset_path=str(dataset_path),
        dataframe=dataframe,
        folds=folds,
        outcomes=outcomes,
        version_leakage=version_leakage,
        feature_set=feature_set,
        excluded_feature_model_version="v3",
        reports_dir=reports_dir,
    )


def run_walk_forward_for_version(
    model_version: ModelVersion | str,
    config: WalkForwardConfig,
    *,
    db: Session | None = None,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
    model_names: tuple[str, ...] | None = None,
    progress_callback: ProgressCallback | None = None,
    should_cancel: ShouldCancel | None = None,
    estimators_factory: EstimatorsFactory | None = None,
) -> WalkForwardVersionResult:
    config.validate()
    resolved_model_names = model_names_for_version(str(model_version), model_names)
    resolved_estimators_factory = estimators_factory or make_estimators_factory_for_version(
        str(model_version), reports_dir=reports_dir
    )
    if model_version not in MODEL_VERSIONS:
        return _run_walk_forward_for_market_version(
            str(model_version),
            config,
            db=db,
            processed_dir=processed_dir,
            reports_dir=reports_dir,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
            estimators_factory=resolved_estimators_factory,
        )

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
        if should_cancel and should_cancel():
            raise BackgroundJobCancelled("Walk-forward cancelled.")
        train, test = slice_fold_frames(dataframe, fold)
        outcomes.extend(
            evaluate_fold_models(
                train,
                test,
                model_version=model_version,
                dataset_path=str(dataset_path),
                fold=fold,
                config=config,
                model_names=resolved_model_names,
                estimators_factory=resolved_estimators_factory,
            )
        )
        if progress_callback:
            progress_callback(
                f"{model_version} · fold {fold.fold_index + 1}/{len(folds)}",
                len(resolved_model_names),
                len(folds),
            )

    return _finalize_version_result(
        model_version=str(model_version),
        dataset_path=str(dataset_path),
        dataframe=dataframe,
        folds=folds,
        outcomes=outcomes,
        version_leakage=version_leakage,
        feature_set=feature_set,
        excluded_feature_model_version=str(model_version),
        reports_dir=reports_dir,
    )


def run_walk_forward_validation(
    config: WalkForwardConfig | None = None,
    *,
    versions: tuple[str, ...] | None = None,
    db: Session | None = None,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
    model_names: tuple[str, ...] | None = None,
    progress_callback: ProgressCallback | None = None,
    prepare_progress_callback: PrepareProgressCallback | None = None,
    should_cancel: ShouldCancel | None = None,
) -> WalkForwardRunResult:
    """Run walk-forward for live (or selected) markets. Does not touch public models.

    Default scope (``versions=None``) is every currently active market/version
    (see ``walk_forward_markets.ACTIVE_WALK_FORWARD_MARKET_VERSIONS``), not just
    match-winner. Extra markets (first_set_winner, over_under_games) build their
    dataframe from the DB, so ``db`` must be provided to include them.
    """
    from backend.src.app.ml.training.walk_forward_markets import (
        ACTIVE_WALK_FORWARD_MARKET_VERSIONS,
        ALL_WALK_FORWARD_VERSIONS,
    )

    resolved = config or WalkForwardConfig()
    resolved.validate()
    selected_versions = versions or ACTIVE_WALK_FORWARD_MARKET_VERSIONS
    started = datetime.now(timezone.utc)
    version_results: list[WalkForwardVersionResult] = []
    if prepare_progress_callback:
        prepare_progress_callback("Conteggio fold pianificati…")
    total_units = _count_planned_fold_units(
        resolved,
        selected_versions,
        processed_dir=processed_dir,
        model_names=model_names,
        db=db,
        should_cancel=should_cancel,
        prepare_progress_callback=prepare_progress_callback,
    )
    completed_units = 0

    def on_version_progress(phase: str, delta: int, _fold_total: int) -> None:
        nonlocal completed_units
        completed_units += delta
        if progress_callback:
            progress_callback(phase, completed_units, max(total_units, 1))

    for version in selected_versions:
        if version not in ALL_WALK_FORWARD_VERSIONS:
            raise ValueError(f"Versione/mercato walk-forward sconosciuto: {version}")
        if should_cancel and should_cancel():
            raise BackgroundJobCancelled("Walk-forward cancelled.")
        logger.info("Walk-forward start version=%s mode=%s", version, resolved.mode)
        version_results.append(
            run_walk_forward_for_version(
                version,
                resolved,
                db=db,
                processed_dir=processed_dir,
                reports_dir=reports_dir,
                model_names=model_names,
                progress_callback=on_version_progress,
                should_cancel=should_cancel,
            )
        )

    finished = datetime.now(timezone.utc)
    sample_mismatch_folds: set[tuple[str, int]] = set()
    for version in version_results:
        for fold in version.folds:
            sample = (fold.coverage or {}).get("official_benchmark_sample")
            if isinstance(sample, dict) and sample.get("sample_mismatch_detected"):
                sample_mismatch_folds.add(
                    (version.model_version, fold.fold.fold_index)
                )
    evaluated_model_names = tuple(
        dict.fromkeys(
            model_name
            for version in selected_versions
            for model_name in model_names_for_version(version, model_names)
        )
    )
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
        "official_contenders": list(
            dict.fromkeys((*OFFICIAL_BENCHMARK_NAMES, *evaluated_model_names))
        ),
        "official_sample_mismatch_folds": len(sample_mismatch_folds),
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
