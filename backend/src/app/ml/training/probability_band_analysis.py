"""Performance analysis by configurable probability and edge bands.

Supports OOS walk-forward/backtest records and live published tips.
Reuses calibration helpers for raw vs calibrated probability comparison.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal, Sequence

import numpy as np
import pandas as pd

from backend.src.app.ml.datasets.odds_builder import profit_for_unit_stake
from backend.src.app.ml.model_versioning import (
    MODEL_VERSIONS,
    PROCESSED_DATA_DIR,
    ModelVersion,
    select_training_dataset_path,
)
from backend.src.app.ml.training.calibration import (
    CalibrationMethod,
    apply_calibrator,
    fit_calibrator,
)
from backend.src.app.ml.training.train_baseline import TARGET_COLUMN
from backend.src.app.ml.training.value_bet_metrics import market_probability_column
from backend.src.app.ml.training.walk_forward import (
    MODEL_NAMES,
    WalkForwardConfig,
    WalkForwardFoldSpec,
    generate_walk_forward_folds,
    prepare_temporal_dataframe,
    slice_fold_frames,
)
from backend.src.app.services.live_betting_metrics import (
    average,
    hit_rate_pct,
    roi_pct,
    round_metric,
    yield_pct,
)

BandDimension = Literal["probability", "edge"]
AnalysisSource = Literal["live", "walk_forward", "backtest"]

DEFAULT_N_BINS = 10
DEFAULT_MIN_BIN_SAMPLES = 30
DEFAULT_CONFIDENCE_Z = 1.96

EDGE_BAND_EDGES: tuple[tuple[float, float, str, str], ...] = (
    (-math.inf, 0.0, "lt_0", "< 0%"),
    (0.0, 5.0, "0_5", "0% – 5%"),
    (5.0, 10.0, "5_10", "5% – 10%"),
    (10.0, math.inf, "gte_10", "≥ 10%"),
)


@dataclass(frozen=True)
class BandAnalysisRecord:
    """One settled or OOS prediction used for band aggregation."""

    match_date: date | None
    fold_index: int | None
    model_version: str | None
    model_name: str | None
    prob_raw: float
    prob_used: float
    edge_pct: float | None
    odds: float | None
    won: bool | None
    void: bool = False
    stake: float = 1.0
    profit: float = 0.0
    period_key: str | None = None

    @property
    def closed(self) -> bool:
        return self.won is not None and not self.void


@dataclass
class ProbabilityBandBucket:
    key: str
    label: str
    bin_start: float | None
    bin_end: float | None
    predictions_total: int
    closed: int
    void: int
    open: int
    won: int
    lost: int
    hit_rate_pct: float | None
    mean_predicted_pct: float | None
    mean_observed_pct: float | None
    calibration_gap_pct: float | None
    avg_odds: float | None
    avg_edge_pct: float | None
    stake_total: float
    stake_settled: float
    profit: float
    roi_pct: float | None
    yield_pct: float | None
    hit_rate_ci_lower_pct: float | None
    hit_rate_ci_upper_pct: float | None
    insufficient_sample: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProbabilityBandAnalysisResult:
    source: AnalysisSource
    band_dimension: BandDimension
    probability_kind: CalibrationMethod
    n_bins: int
    min_bin_samples: int
    predictions_total: int
    closed: int
    void: int
    open: int
    won: int
    lost: int
    bands: list[ProbabilityBandBucket]
    comparison: dict[str, list[ProbabilityBandBucket]] = field(default_factory=dict)
    by_fold: list[dict[str, Any]] = field(default_factory=list)
    by_period: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "band_dimension": self.band_dimension,
            "probability_kind": self.probability_kind,
            "n_bins": self.n_bins,
            "min_bin_samples": self.min_bin_samples,
            "predictions_total": self.predictions_total,
            "closed": self.closed,
            "void": self.void,
            "open": self.open,
            "won": self.won,
            "lost": self.lost,
            "bands": [item.to_dict() for item in self.bands],
            "comparison": {
                key: [item.to_dict() for item in value]
                for key, value in self.comparison.items()
            },
            "by_fold": self.by_fold,
            "by_period": self.by_period,
            "notes": self.notes,
        }


def wilson_score_interval(
    successes: int,
    total: int,
    *,
    z: float = DEFAULT_CONFIDENCE_Z,
) -> tuple[float | None, float | None]:
    """Wilson score 95% interval for binomial proportion (returns 0–100 scale)."""
    if total <= 0:
        return None, None
    phat = successes / total
    z2 = z * z
    denom = 1.0 + z2 / total
    center = phat + z2 / (2 * total)
    margin = z * math.sqrt((phat * (1 - phat) + z2 / (4 * total)) / total)
    lower = max(0.0, (center - margin) / denom)
    upper = min(1.0, (center + margin) / denom)
    return round_metric(lower * 100.0, 4), round_metric(upper * 100.0, 4)


def period_key_from_date(value: date | None) -> str | None:
    if value is None:
        return None
    return f"{value.year:04d}-{value.month:02d}"


def probability_band_label(start: float, end: float, *, last_bin: bool = False) -> str:
    start_pct = start * 100.0
    end_pct = end * 100.0
    if last_bin:
        return f"{start_pct:.0f}% – {end_pct:.0f}%"
    return f"{start_pct:.0f}% – {end_pct:.0f}%"


def probability_band_key(index: int, start: float, end: float) -> str:
    return f"p_{index:02d}_{start:.2f}_{end:.2f}"


def assign_probability_band(probability: float, *, n_bins: int) -> tuple[int, float, float]:
    clipped = min(max(float(probability), 0.0), 1.0)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    index = int(np.searchsorted(edges, clipped, side="right") - 1)
    index = min(max(index, 0), n_bins - 1)
    start = float(edges[index])
    end = float(edges[index + 1])
    return index, start, end


def assign_edge_band(edge_pct: float | None) -> tuple[str, str, float | None, float | None]:
    if edge_pct is None or math.isnan(edge_pct):
        return "missing", "Senza edge", None, None
    for start, end, key, label in EDGE_BAND_EDGES:
        if start <= edge_pct < end:
            return key, label, start if math.isfinite(start) else None, end if math.isfinite(end) else None
    return "gte_10", "≥ 10%", 10.0, None


def _aggregate_records(
    records: Sequence[BandAnalysisRecord],
    *,
    band_dimension: BandDimension,
    n_bins: int,
    min_bin_samples: int,
) -> list[ProbabilityBandBucket]:
    grouped: dict[str, list[BandAnalysisRecord]] = {}
    meta: dict[str, tuple[str, float | None, float | None]] = {}

    for record in records:
        if band_dimension == "probability":
            _, start, end = assign_probability_band(record.prob_used, n_bins=n_bins)
            key = probability_band_key(_, start, end)
            last = _ == n_bins - 1
            label = probability_band_label(start, end, last_bin=last)
            meta[key] = (label, start, end)
        else:
            key, label, start, end = assign_edge_band(record.edge_pct)
            meta[key] = (label, start, end)
        grouped.setdefault(key, []).append(record)

    if band_dimension == "probability":
        edges = np.linspace(0.0, 1.0, n_bins + 1)
        order = [
            probability_band_key(index, float(edges[index]), float(edges[index + 1]))
            for index in range(n_bins)
        ]
    else:
        order = [item[2] for item in EDGE_BAND_EDGES] + ["missing"]

    buckets: list[ProbabilityBandBucket] = []
    for key in order:
        items = grouped.get(key, [])
        label, start, end = meta.get(key, (key, None, None))
        buckets.append(_bucket_from_records(items, key=key, label=label, start=start, end=end, min_bin_samples=min_bin_samples))

    for key, items in grouped.items():
        if key in order:
            continue
        label, start, end = meta[key]
        buckets.append(_bucket_from_records(items, key=key, label=label, start=start, end=end, min_bin_samples=min_bin_samples))
    return buckets


def _bucket_from_records(
    records: Sequence[BandAnalysisRecord],
    *,
    key: str,
    label: str,
    start: float | None,
    end: float | None,
    min_bin_samples: int,
) -> ProbabilityBandBucket:
    total = len(records)
    closed_records = [item for item in records if item.closed]
    void_count = sum(1 for item in records if item.void)
    open_count = total - len(closed_records) - void_count
    won = sum(1 for item in closed_records if item.won)
    lost = len(closed_records) - won
    closed = len(closed_records)

    predicted_probs = [item.prob_used for item in closed_records]
    observed = [1.0 if item.won else 0.0 for item in closed_records]
    mean_predicted = average(predicted_probs)
    mean_observed = average(observed)
    calibration_gap = None
    if mean_predicted is not None and mean_observed is not None:
        calibration_gap = abs(mean_predicted - mean_observed) * 100.0

    odds_values = [item.odds for item in closed_records if item.odds is not None]
    edge_values = [item.edge_pct for item in closed_records if item.edge_pct is not None]
    stake_total = sum(item.stake for item in records)
    stake_settled = sum(item.stake for item in closed_records)
    profit = sum(item.profit for item in closed_records)
    ci_lower, ci_upper = wilson_score_interval(won, closed)

    insufficient = closed < min_bin_samples

    return ProbabilityBandBucket(
        key=key,
        label=label,
        bin_start=start,
        bin_end=end,
        predictions_total=total,
        closed=closed,
        void=void_count,
        open=open_count,
        won=won,
        lost=lost,
        hit_rate_pct=hit_rate_pct(won, lost),
        mean_predicted_pct=round_metric(mean_predicted * 100.0, 4) if mean_predicted is not None else None,
        mean_observed_pct=round_metric(mean_observed * 100.0, 4) if mean_observed is not None else None,
        calibration_gap_pct=round_metric(calibration_gap, 4),
        avg_odds=round_metric(average(odds_values), 4),
        avg_edge_pct=round_metric(average(edge_values), 4),
        stake_total=round_metric(stake_total, 6) or 0.0,
        stake_settled=round_metric(stake_settled, 6) or 0.0,
        profit=round_metric(profit, 6) or 0.0,
        roi_pct=round_metric(roi_pct(profit, stake_settled), 4),
        yield_pct=round_metric(yield_pct(profit, stake_settled), 4),
        hit_rate_ci_lower_pct=ci_lower,
        hit_rate_ci_upper_pct=ci_upper,
        insufficient_sample=insufficient,
    )


def _summary_counts(records: Sequence[BandAnalysisRecord]) -> dict[str, int]:
    closed_records = [item for item in records if item.closed]
    won = sum(1 for item in closed_records if item.won)
    lost = len(closed_records) - won
    void_count = sum(1 for item in records if item.void)
    open_count = len(records) - len(closed_records) - void_count
    return {
        "predictions_total": len(records),
        "closed": len(closed_records),
        "void": void_count,
        "open": open_count,
        "won": won,
        "lost": lost,
    }


def analyze_band_records(
    records: Sequence[BandAnalysisRecord],
    *,
    source: AnalysisSource,
    band_dimension: BandDimension,
    probability_kind: CalibrationMethod = "raw",
    n_bins: int = DEFAULT_N_BINS,
    min_bin_samples: int = DEFAULT_MIN_BIN_SAMPLES,
    group_by_fold: bool = False,
    group_by_period: bool = False,
    comparison_records: dict[str, list[BandAnalysisRecord]] | None = None,
) -> ProbabilityBandAnalysisResult:
    counts = _summary_counts(records)
    bands = _aggregate_records(
        records,
        band_dimension=band_dimension,
        n_bins=n_bins,
        min_bin_samples=min_bin_samples,
    )
    comparison: dict[str, list[ProbabilityBandBucket]] = {}
    notes: list[str] = []
    if source == "live" and probability_kind != "raw":
        notes.append("Live: disponibile solo probabilità grezza al momento della pubblicazione.")
    if comparison_records:
        for kind, kind_records in comparison_records.items():
            if kind == probability_kind:
                continue
            comparison[kind] = _aggregate_records(
                kind_records,
                band_dimension=band_dimension,
                n_bins=n_bins,
                min_bin_samples=min_bin_samples,
            )

    by_fold: list[dict[str, Any]] = []
    if group_by_fold:
        fold_keys = sorted({item.fold_index for item in records if item.fold_index is not None})
        for fold_index in fold_keys:
            fold_records = [item for item in records if item.fold_index == fold_index]
            fold_bands = _aggregate_records(
                fold_records,
                band_dimension=band_dimension,
                n_bins=n_bins,
                min_bin_samples=min_bin_samples,
            )
            fold_counts = _summary_counts(fold_records)
            by_fold.append(
                {
                    "fold_index": fold_index,
                    **fold_counts,
                    "bands": [item.to_dict() for item in fold_bands],
                }
            )

    by_period: list[dict[str, Any]] = []
    if group_by_period:
        period_keys = sorted({item.period_key for item in records if item.period_key})
        for period in period_keys:
            period_records = [item for item in records if item.period_key == period]
            period_bands = _aggregate_records(
                period_records,
                band_dimension=band_dimension,
                n_bins=n_bins,
                min_bin_samples=min_bin_samples,
            )
            period_counts = _summary_counts(period_records)
            by_period.append(
                {
                    "period": period,
                    **period_counts,
                    "bands": [item.to_dict() for item in period_bands],
                }
            )

    return ProbabilityBandAnalysisResult(
        source=source,
        band_dimension=band_dimension,
        probability_kind=probability_kind,
        n_bins=n_bins,
        min_bin_samples=min_bin_samples,
        bands=bands,
        comparison=comparison,
        by_fold=by_fold,
        by_period=by_period,
        notes=notes,
        **counts,
    )


def _side_metrics_from_player1(
    prob_p1: float,
    y_true: int,
    market_prob_p1: float | None,
    odds_p1: float | None,
    odds_p2: float | None,
) -> tuple[float, float | None, float | None, bool, float]:
    """Return side probability, edge %, odds, won, profit for model-favored side."""
    bet_p1 = prob_p1 >= 0.5
    side_prob = prob_p1 if bet_p1 else 1.0 - prob_p1
    won = bool(y_true == 1) if bet_p1 else bool(y_true == 0)
    odds = odds_p1 if bet_p1 else odds_p2
    edge_pct = None
    if market_prob_p1 is not None:
        market_p2 = 1.0 - market_prob_p1
        if bet_p1:
            edge_pct = (prob_p1 - market_prob_p1) * 100.0
        else:
            edge_pct = ((1.0 - prob_p1) - market_p2) * 100.0
    profit = 0.0
    if odds is not None and odds > 1.0:
        profit = profit_for_unit_stake(float(odds), won)
    return side_prob, edge_pct, odds, won, profit


def _records_from_oos_fold(
    fold: WalkForwardFoldSpec,
    test: pd.DataFrame,
    prob_raw: np.ndarray,
    prob_used: np.ndarray,
    *,
    model_version: str,
    model_name: str,
) -> list[BandAnalysisRecord]:
    market_col = market_probability_column(test)
    odds_p1_col = "avg_player_1_odds" if "avg_player_1_odds" in test.columns else None
    odds_p2_col = "avg_player_2_odds" if "avg_player_2_odds" in test.columns else None
    records: list[BandAnalysisRecord] = []
    y_true = test[TARGET_COLUMN].astype(int).to_numpy()
    match_dates = pd.to_datetime(test["match_date"], errors="coerce").dt.date.to_numpy()

    for index in range(len(test)):
        market_prob = None
        if market_col is not None:
            raw_market = test.iloc[index][market_col]
            if pd.notna(raw_market):
                market_prob = float(raw_market)
        odds_p1 = None
        odds_p2 = None
        if odds_p1_col is not None and pd.notna(test.iloc[index][odds_p1_col]):
            odds_p1 = float(test.iloc[index][odds_p1_col])
        if odds_p2_col is not None and pd.notna(test.iloc[index][odds_p2_col]):
            odds_p2 = float(test.iloc[index][odds_p2_col])

        side_prob, edge_pct, odds, won, profit = _side_metrics_from_player1(
            float(prob_used[index]),
            int(y_true[index]),
            market_prob,
            odds_p1,
            odds_p2,
        )
        match_day = match_dates[index]
        if isinstance(match_day, date):
            event_day = match_day
        else:
            event_day = None
        records.append(
            BandAnalysisRecord(
                match_date=event_day,
                fold_index=fold.fold_index,
                model_version=model_version,
                model_name=model_name,
                prob_raw=float(prob_raw[index]),
                prob_used=side_prob,
                edge_pct=edge_pct,
                odds=odds,
                won=won,
                profit=profit,
                period_key=period_key_from_date(event_day),
            )
        )
    return records


def collect_oos_band_records(
    model_version: ModelVersion | str,
    wf_config: WalkForwardConfig,
    *,
    model_name: str,
    probability_kind: CalibrationMethod = "raw",
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[BandAnalysisRecord]:
    """Build row-level OOS records with optional fold-wise calibration."""
    from backend.src.app.ml.training.calibration import (
        OosPredictionBatch,
        _concat_batches,
        collect_oos_predictions_for_version,
    )

    wf_config.validate()
    if model_version not in MODEL_VERSIONS:
        raise ValueError(f"Versione modello sconosciuta: {model_version}")
    if model_name not in MODEL_NAMES:
        raise ValueError(f"Modello non supportato: {model_name}")

    dataset_path = select_training_dataset_path(processed_dir, version=model_version)  # type: ignore[arg-type]
    raw = pd.read_csv(dataset_path, low_memory=False)
    dataframe = prepare_temporal_dataframe(raw, model_version=model_version)
    folds = generate_walk_forward_folds(dataframe, wf_config)

    batches = collect_oos_predictions_for_version(
        model_version,
        wf_config,
        processed_dir=processed_dir,
        model_names=(model_name,),
    )[model_name]
    batch_by_fold = {item.fold_index: item for item in batches}

    all_records: list[BandAnalysisRecord] = []
    prior_batches: list[OosPredictionBatch] = []

    for fold in folds:
        batch = batch_by_fold.get(fold.fold_index)
        if batch is None:
            continue
        train, test = slice_fold_frames(dataframe, fold)
        prob_raw = batch.prob_raw
        prob_used = prob_raw.copy()

        if probability_kind != "raw" and prior_batches:
            y_train, prob_train, _ = _concat_batches(prior_batches)
            if len(y_train) >= 2:
                calibrator = fit_calibrator(probability_kind, y_train, prob_train)
                if calibrator is not None:
                    prob_used = apply_calibrator(probability_kind, calibrator, prob_raw)

        fold_records = _records_from_oos_fold(
            fold,
            test,
            prob_raw,
            prob_used,
            model_version=str(model_version),
            model_name=model_name,
        )
        if date_from is not None:
            fold_records = [item for item in fold_records if item.match_date and item.match_date >= date_from]
        if date_to is not None:
            fold_records = [item for item in fold_records if item.match_date and item.match_date <= date_to]
        all_records.extend(fold_records)
        prior_batches.append(batch)

    return all_records


def collect_oos_comparison_records(
    model_version: ModelVersion | str,
    wf_config: WalkForwardConfig,
    *,
    model_name: str,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[CalibrationMethod, list[BandAnalysisRecord]]:
    kinds: tuple[CalibrationMethod, ...] = ("raw", "platt", "isotonic")
    return {
        kind: collect_oos_band_records(
            model_version,
            wf_config,
            model_name=model_name,
            probability_kind=kind,
            processed_dir=processed_dir,
            date_from=date_from,
            date_to=date_to,
        )
        for kind in kinds
    }
