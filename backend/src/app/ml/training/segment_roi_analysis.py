"""Performance analysis by configurable business segments (ML-04).

Supports OOS walk-forward/backtest records and live published tips.
Reuses settlement conventions from probability band analysis and live betting metrics.
"""

from __future__ import annotations

import math
import statistics
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
from backend.src.app.ml.training.probability_band_analysis import (
    AnalysisSource,
    period_key_from_date,
    wilson_score_interval,
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
    max_drawdown,
    roi_pct,
    round_metric,
    yield_pct,
)

SegmentDimension = Literal[
    "surface",
    "tournament",
    "circuit",
    "level",
    "round",
    "favorite_role",
    "odds_band",
    "bookmaker",
    "model",
    "version",
    "period",
]

DEFAULT_MIN_SEGMENT_SAMPLES = 30
DEFAULT_CONFIDENCE_Z = 1.96

FAVORITE_ODDS_THRESHOLD = 2.0

ODDS_BAND_EDGES: tuple[tuple[float, float, str, str], ...] = (
    (-math.inf, 1.5, "lt_1_50", "< 1.50"),
    (1.5, 2.0, "1_50_2_00", "1.50 – 2.00"),
    (2.0, 3.0, "2_00_3_00", "2.00 – 3.00"),
    (3.0, math.inf, "gte_3_00", "≥ 3.00"),
)

ODDS_BAND_ORDER = [item[2] for item in ODDS_BAND_EDGES] + ["missing"]

FAVORITE_ROLE_LABELS: dict[str, str] = {
    "favorite": "Favorito",
    "underdog": "Sfavorito",
    "unknown": "Sconosciuto",
}


@dataclass(frozen=True)
class FixtureSegmentMetadata:
    """Optional fixture metadata keyed by match_id for OOS enrichment."""

    tournament_name: str | None = None
    circuit: str | None = None
    round_name: str | None = None
    surface: str | None = None


@dataclass(frozen=True)
class SegmentAnalysisRecord:
    """One settled or OOS prediction used for segment aggregation."""

    match_date: date | None
    fold_index: int | None
    model_version: str | None
    model_name: str | None
    prob_used: float
    edge_pct: float | None
    odds: float | None
    won: bool | None
    void: bool = False
    stake: float = 1.0
    profit: float = 0.0
    period_key: str | None = None
    surface: str | None = None
    tournament_name: str | None = None
    circuit: str | None = None
    level: str | None = None
    round_name: str | None = None
    favorite_role: str | None = None
    odds_band: str | None = None
    bookmaker: str | None = None
    publication_source: str | None = None
    match_id: int | None = None

    @property
    def closed(self) -> bool:
        return self.won is not None and not self.void


@dataclass
class SegmentRoiBucket:
    key: str
    label: str
    predictions_total: int
    closed: int
    void: int
    open: int
    won: int
    lost: int
    hit_rate_pct: float | None
    avg_odds: float | None
    avg_edge_pct: float | None
    stake_total: float
    stake_settled: float
    profit: float
    roi_pct: float | None
    yield_pct: float | None
    max_drawdown: float
    hit_rate_ci_lower_pct: float | None
    hit_rate_ci_upper_pct: float | None
    roi_ci_lower_pct: float | None
    roi_ci_upper_pct: float | None
    insufficient_sample: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SegmentRoiAnalysisResult:
    source: AnalysisSource
    segment_dimension: SegmentDimension
    min_segment_samples: int
    predictions_total: int
    closed: int
    void: int
    open: int
    won: int
    lost: int
    segments: list[SegmentRoiBucket]
    by_fold: list[dict[str, Any]] = field(default_factory=list)
    by_period: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "segment_dimension": self.segment_dimension,
            "min_segment_samples": self.min_segment_samples,
            "predictions_total": self.predictions_total,
            "closed": self.closed,
            "void": self.void,
            "open": self.open,
            "won": self.won,
            "lost": self.lost,
            "segments": [item.to_dict() for item in self.segments],
            "by_fold": self.by_fold,
            "by_period": self.by_period,
            "notes": self.notes,
        }


def _normalize_text(value: str | None, *, unknown_key: str = "unknown") -> str:
    if value is None:
        return unknown_key
    clean = str(value).strip()
    return clean if clean else unknown_key


def assign_odds_band(odds: float | None) -> tuple[str, str]:
    if odds is None or math.isnan(odds):
        return "missing", "Senza quota"
    for start, end, key, label in ODDS_BAND_EDGES:
        if start <= odds < end:
            return key, label
    return "gte_3_00", "≥ 3.00"


def assign_favorite_role(odds: float | None) -> tuple[str, str]:
    if odds is None or math.isnan(odds):
        return "unknown", FAVORITE_ROLE_LABELS["unknown"]
    if odds < FAVORITE_ODDS_THRESHOLD:
        return "favorite", FAVORITE_ROLE_LABELS["favorite"]
    return "underdog", FAVORITE_ROLE_LABELS["underdog"]


def _segment_key_label(record: SegmentAnalysisRecord, dimension: SegmentDimension) -> tuple[str, str]:
    if dimension == "surface":
        key = _normalize_text(record.surface)
        label = "Sconosciuta" if key == "unknown" else key
        return key, label
    if dimension == "tournament":
        key = _normalize_text(record.tournament_name)
        label = "Sconosciuto" if key == "unknown" else key
        return key, label
    if dimension == "circuit":
        key = _normalize_text(record.circuit)
        label = "Sconosciuto" if key == "unknown" else key
        return key, label
    if dimension == "level":
        key = _normalize_text(record.level)
        label = "Sconosciuto" if key == "unknown" else key
        return key, label
    if dimension == "round":
        key = _normalize_text(record.round_name)
        label = "Sconosciuto" if key == "unknown" else key
        return key, label
    if dimension == "favorite_role":
        key, label = assign_favorite_role(record.odds)
        if record.favorite_role:
            key = record.favorite_role
            label = FAVORITE_ROLE_LABELS.get(key, key)
        return key, label
    if dimension == "odds_band":
        if record.odds_band:
            key = record.odds_band
            for _, _, band_key, band_label in ODDS_BAND_EDGES:
                if band_key == key:
                    return key, band_label
            if key == "missing":
                return key, "Senza quota"
        return assign_odds_band(record.odds)
    if dimension == "bookmaker":
        if record.bookmaker:
            key = _normalize_text(record.bookmaker, unknown_key="aggregated")
            return key, key
        return "aggregated", "Quota aggregata"
    if dimension == "model":
        key = _normalize_text(record.model_name)
        label = "Sconosciuto" if key == "unknown" else key
        return key, label
    if dimension == "version":
        key = _normalize_text(record.model_version)
        label = "Sconosciuta" if key == "unknown" else key
        return key, label
    if dimension == "period":
        key = _normalize_text(record.period_key, unknown_key="unknown")
        label = "Sconosciuto" if key == "unknown" else key
        return key, label
    raise ValueError(f"Dimensione segmento non supportata: {dimension}")


def _roi_confidence_interval(
    records: Sequence[SegmentAnalysisRecord],
    *,
    z: float = DEFAULT_CONFIDENCE_Z,
) -> tuple[float | None, float | None]:
    """Normal-approximation 95% CI on per-bet ROI % (closed bets only)."""
    returns: list[float] = []
    for record in records:
        if not record.closed or record.stake <= 0:
            continue
        returns.append(record.profit / record.stake)
    if len(returns) < 2:
        return None, None
    mean = statistics.fmean(returns)
    stdev = statistics.stdev(returns)
    if stdev <= 0:
        pct = round_metric(mean * 100.0, 4)
        return pct, pct
    margin = z * stdev / math.sqrt(len(returns))
    lower = (mean - margin) * 100.0
    upper = (mean + margin) * 100.0
    return round_metric(lower, 4), round_metric(upper, 4)


def _segment_bucket_from_records(
    records: Sequence[SegmentAnalysisRecord],
    *,
    key: str,
    label: str,
    min_segment_samples: int,
) -> SegmentRoiBucket:
    total = len(records)
    closed_records = [item for item in records if item.closed]
    void_count = sum(1 for item in records if item.void)
    open_count = total - len(closed_records) - void_count
    won = sum(1 for item in closed_records if item.won)
    lost = len(closed_records) - won

    odds_values = [item.odds for item in closed_records if item.odds is not None]
    edge_values = [item.edge_pct for item in closed_records if item.edge_pct is not None]
    stake_total = sum(item.stake for item in records)
    stake_settled = sum(item.stake for item in closed_records)
    profit = sum(item.profit for item in closed_records)

    sorted_closed = sorted(
        closed_records,
        key=lambda item: (
            item.match_date or date.min,
            item.fold_index if item.fold_index is not None else -1,
        ),
    )
    drawdown = max_drawdown(item.profit for item in sorted_closed)

    ci_lower, ci_upper = wilson_score_interval(won, len(closed_records))
    roi_ci_lower, roi_ci_upper = _roi_confidence_interval(closed_records)
    insufficient = len(closed_records) < min_segment_samples

    return SegmentRoiBucket(
        key=key,
        label=label,
        predictions_total=total,
        closed=len(closed_records),
        void=void_count,
        open=open_count,
        won=won,
        lost=lost,
        hit_rate_pct=round_metric(hit_rate_pct(won, lost), 4),
        avg_odds=round_metric(average(odds_values), 4),
        avg_edge_pct=round_metric(average(edge_values), 4),
        stake_total=round_metric(stake_total, 6) or 0.0,
        stake_settled=round_metric(stake_settled, 6) or 0.0,
        profit=round_metric(profit, 6) or 0.0,
        roi_pct=round_metric(roi_pct(profit, stake_settled), 4),
        yield_pct=round_metric(yield_pct(profit, stake_settled), 4),
        max_drawdown=round(drawdown, 6),
        hit_rate_ci_lower_pct=ci_lower,
        hit_rate_ci_upper_pct=ci_upper,
        roi_ci_lower_pct=roi_ci_lower,
        roi_ci_upper_pct=roi_ci_upper,
        insufficient_sample=insufficient,
    )


def _ordered_segment_keys(dimension: SegmentDimension) -> list[str] | None:
    if dimension == "odds_band":
        return ODDS_BAND_ORDER
    if dimension == "favorite_role":
        return ["favorite", "underdog", "unknown"]
    return None


def _aggregate_segment_records(
    records: Sequence[SegmentAnalysisRecord],
    *,
    segment_dimension: SegmentDimension,
    min_segment_samples: int,
) -> list[SegmentRoiBucket]:
    grouped: dict[str, list[SegmentAnalysisRecord]] = {}
    meta: dict[str, str] = {}

    for record in records:
        key, label = _segment_key_label(record, segment_dimension)
        grouped.setdefault(key, []).append(record)
        meta[key] = label

    order = _ordered_segment_keys(segment_dimension)
    keys = order if order is not None else sorted(grouped.keys())

    buckets: list[SegmentRoiBucket] = []
    seen: set[str] = set()
    for key in keys:
        items = grouped.get(key, [])
        if not items and order is None:
            continue
        seen.add(key)
        buckets.append(
            _segment_bucket_from_records(
                items,
                key=key,
                label=meta.get(key, key),
                min_segment_samples=min_segment_samples,
            )
        )

    for key in sorted(grouped.keys()):
        if key in seen:
            continue
        buckets.append(
            _segment_bucket_from_records(
                grouped[key],
                key=key,
                label=meta[key],
                min_segment_samples=min_segment_samples,
            )
        )
    return buckets


def _summary_counts(records: Sequence[SegmentAnalysisRecord]) -> dict[str, int]:
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


def analyze_segment_records(
    records: Sequence[SegmentAnalysisRecord],
    *,
    source: AnalysisSource,
    segment_dimension: SegmentDimension,
    min_segment_samples: int = DEFAULT_MIN_SEGMENT_SAMPLES,
    group_by_fold: bool = False,
    group_by_period: bool = False,
) -> SegmentRoiAnalysisResult:
    counts = _summary_counts(records)
    segments = _aggregate_segment_records(
        records,
        segment_dimension=segment_dimension,
        min_segment_samples=min_segment_samples,
    )
    notes: list[str] = []
    if segment_dimension == "bookmaker":
        notes.append(
            "Bookmaker: le quote live/OOS usano medie di mercato; il segmento "
            "'Quota aggregata' indica assenza di bookmaker singolo sul record."
        )

    by_fold: list[dict[str, Any]] = []
    if group_by_fold:
        fold_keys = sorted({item.fold_index for item in records if item.fold_index is not None})
        for fold_index in fold_keys:
            fold_records = [item for item in records if item.fold_index == fold_index]
            fold_segments = _aggregate_segment_records(
                fold_records,
                segment_dimension=segment_dimension,
                min_segment_samples=min_segment_samples,
            )
            fold_counts = _summary_counts(fold_records)
            by_fold.append(
                {
                    "fold_index": fold_index,
                    **fold_counts,
                    "segments": [item.to_dict() for item in fold_segments],
                }
            )

    by_period: list[dict[str, Any]] = []
    if group_by_period:
        period_keys = sorted({item.period_key for item in records if item.period_key})
        for period in period_keys:
            period_records = [item for item in records if item.period_key == period]
            period_segments = _aggregate_segment_records(
                period_records,
                segment_dimension=segment_dimension,
                min_segment_samples=min_segment_samples,
            )
            period_counts = _summary_counts(period_records)
            by_period.append(
                {
                    "period": period,
                    **period_counts,
                    "segments": [item.to_dict() for item in period_segments],
                }
            )

    return SegmentRoiAnalysisResult(
        source=source,
        segment_dimension=segment_dimension,
        min_segment_samples=min_segment_samples,
        segments=segments,
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


def _optional_str(row: pd.Series, column: str) -> str | None:
    if column not in row.index:
        return None
    raw = row[column]
    if pd.isna(raw):
        return None
    clean = str(raw).strip()
    return clean or None


def _segment_fields_from_row(
    row: pd.Series,
    *,
    odds: float | None,
    fixture_metadata: dict[int, FixtureSegmentMetadata] | None,
    match_id: int | None,
) -> dict[str, str | None]:
    surface = _optional_str(row, "surface")
    level = _optional_str(row, "atp_tourney_level")
    round_name = _optional_str(row, "atp_round")
    tournament_name = _optional_str(row, "tournament_name")
    circuit = _optional_str(row, "event_type_type")
    bookmaker = _optional_str(row, "bookmaker")

    if fixture_metadata and match_id is not None:
        meta = fixture_metadata.get(match_id)
        if meta is not None:
            surface = surface or meta.surface
            tournament_name = tournament_name or meta.tournament_name
            circuit = circuit or meta.circuit
            round_name = round_name or meta.round_name

    odds_band_key, _ = assign_odds_band(odds)
    favorite_key, _ = assign_favorite_role(odds)

    return {
        "surface": surface,
        "tournament_name": tournament_name,
        "circuit": circuit,
        "level": level,
        "round_name": round_name,
        "odds_band": odds_band_key,
        "favorite_role": favorite_key,
        "bookmaker": bookmaker,
    }


def _records_from_oos_fold(
    fold: WalkForwardFoldSpec,
    test: pd.DataFrame,
    prob_raw: np.ndarray,
    prob_used: np.ndarray,
    *,
    model_version: str,
    model_name: str,
    fixture_metadata: dict[int, FixtureSegmentMetadata] | None = None,
) -> list[SegmentAnalysisRecord]:
    market_col = market_probability_column(test)
    odds_p1_col = "avg_player_1_odds" if "avg_player_1_odds" in test.columns else None
    odds_p2_col = "avg_player_2_odds" if "avg_player_2_odds" in test.columns else None
    match_id_col = "match_id" if "match_id" in test.columns else None
    records: list[SegmentAnalysisRecord] = []
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
        event_day = match_day if isinstance(match_day, date) else None
        match_id = None
        if match_id_col is not None and pd.notna(test.iloc[index][match_id_col]):
            match_id = int(test.iloc[index][match_id_col])

        segment_fields = _segment_fields_from_row(
            test.iloc[index],
            odds=odds,
            fixture_metadata=fixture_metadata,
            match_id=match_id,
        )

        records.append(
            SegmentAnalysisRecord(
                match_date=event_day,
                fold_index=fold.fold_index,
                match_id=match_id,
                model_version=model_version,
                model_name=model_name,
                prob_used=side_prob,
                edge_pct=edge_pct,
                odds=odds,
                won=won,
                profit=profit,
                period_key=period_key_from_date(event_day),
                **segment_fields,
            )
        )
    return records


def collect_oos_segment_records(
    model_version: ModelVersion | str,
    wf_config: WalkForwardConfig,
    *,
    model_name: str,
    probability_kind: CalibrationMethod = "raw",
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    date_from: date | None = None,
    date_to: date | None = None,
    fixture_metadata: dict[int, FixtureSegmentMetadata] | None = None,
) -> list[SegmentAnalysisRecord]:
    """Build row-level OOS records with segment metadata."""
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

    all_records: list[SegmentAnalysisRecord] = []
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
            fixture_metadata=fixture_metadata,
        )
        if date_from is not None:
            fold_records = [
                item for item in fold_records if item.match_date and item.match_date >= date_from
            ]
        if date_to is not None:
            fold_records = [
                item for item in fold_records if item.match_date and item.match_date <= date_to
            ]
        all_records.extend(fold_records)
        prior_batches.append(batch)

    return all_records
