"""Orchestrate probability / edge band analysis across live and OOS sources."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from backend.src.app.core.config import Settings, get_settings
from backend.src.app.ml.training.calibration import CalibrationMethod
from backend.src.app.ml.training.probability_band_analysis import (
    AnalysisSource,
    BandAnalysisRecord,
    BandDimension,
    analyze_band_records,
    collect_oos_band_records,
    collect_oos_comparison_records,
    period_key_from_date,
)
from backend.src.app.ml.training.walk_forward import MODEL_NAMES
from backend.src.app.schemas.probability_bands import (
    ProbabilityBandAnalysisRead,
    ProbabilityBandBucketRead,
    ProbabilityBandGroupRead,
)
from backend.src.app.services.published_live_stats import (
    period_key,
    settle_published_tips,
)
from backend.src.app.services.walk_forward import config_from_settings

LIVE_MARKETS = frozenset({"match_winner", "first_set_winner", "over_under_games"})
DEFAULT_LIVE_MARKET = "match_winner"


def _bucket_to_read(item) -> ProbabilityBandBucketRead:
    return ProbabilityBandBucketRead(**item.to_dict())


def _resolve_live_market(market: str | None) -> str:
    resolved = (market or DEFAULT_LIVE_MARKET).strip()
    if resolved not in LIVE_MARKETS:
        raise ValueError(
            f"market non valido: {market!r}. Valori ammessi: {', '.join(sorted(LIVE_MARKETS))}."
        )
    return resolved


def _records_from_live_tips(
    db: Session,
    *,
    from_date: date | None,
    to_date: date | None,
    event_date_from: date | None,
    event_date_to: date | None,
    model_version: str | None,
    model_name: str | None,
    publication_source: str | None,
    tournament_name: str | None,
    surface: str | None,
    odds_band: str | None,
    latest_only: bool,
    market: str,
    include_archived: bool,
) -> list[BandAnalysisRecord]:
    settled = settle_published_tips(
        db,
        from_date=from_date,
        to_date=to_date,
        event_date_from=event_date_from,
        event_date_to=event_date_to,
        model_version=model_version,
        model_name=model_name,
        publication_source=publication_source,
        tournament_name=tournament_name,
        surface=surface,
        odds_band=odds_band,
        latest_only=latest_only,
        market=market,
        include_archived=include_archived,
    )
    records: list[BandAnalysisRecord] = []
    for item in settled:
        tip = item.tip
        prob = float(tip.probability)
        won: bool | None
        void = item.outcome == "void"
        if item.outcome in ("won", "lost"):
            won = item.outcome == "won"
        else:
            won = None
        records.append(
            BandAnalysisRecord(
                match_date=tip.event_date,
                fold_index=None,
                model_version=tip.model_version,
                model_name=tip.model_name,
                prob_raw=prob,
                prob_used=prob,
                edge_pct=float(tip.edge) if tip.edge is not None else None,
                odds=float(tip.odds) if tip.odds is not None else None,
                won=won,
                void=void,
                stake=float(tip.unit_stake),
                profit=float(item.profit),
                period_key=period_key(tip.event_date, tip.published_at),
            )
        )
    return records


def _result_to_read(
    result,
    *,
    model_version: str | None,
    model_name: str | None,
    market: str | None,
    from_date: date | None,
    to_date: date | None,
    event_date_from: date | None,
    event_date_to: date | None,
) -> ProbabilityBandAnalysisRead:
    return ProbabilityBandAnalysisRead(
        source=result.source,
        band_dimension=result.band_dimension,
        probability_kind=result.probability_kind,
        n_bins=result.n_bins,
        min_bin_samples=result.min_bin_samples,
        model_version=model_version,
        model_name=model_name,
        market=market,
        from_date=from_date,
        to_date=to_date,
        event_date_from=event_date_from,
        event_date_to=event_date_to,
        predictions_total=result.predictions_total,
        closed=result.closed,
        void=result.void,
        open=result.open,
        won=result.won,
        lost=result.lost,
        bands=[_bucket_to_read(item) for item in result.bands],
        comparison={
            key: [_bucket_to_read(bucket) for bucket in value]
            for key, value in result.comparison.items()
        },
        by_fold=[
            ProbabilityBandGroupRead(
                fold_index=item.get("fold_index"),
                period=None,
                predictions_total=item["predictions_total"],
                closed=item["closed"],
                void=item["void"],
                open=item["open"],
                won=item["won"],
                lost=item["lost"],
                bands=[ProbabilityBandBucketRead(**band) for band in item["bands"]],
            )
            for item in result.by_fold
        ],
        by_period=[
            ProbabilityBandGroupRead(
                fold_index=None,
                period=item.get("period"),
                predictions_total=item["predictions_total"],
                closed=item["closed"],
                void=item["void"],
                open=item["open"],
                won=item["won"],
                lost=item["lost"],
                bands=[ProbabilityBandBucketRead(**band) for band in item["bands"]],
            )
            for item in result.by_period
        ],
        notes=result.notes,
    )


def compute_probability_band_analysis(
    db: Session,
    *,
    source: AnalysisSource,
    band_dimension: BandDimension = "probability",
    probability_kind: CalibrationMethod = "raw",
    model_version: str | None = None,
    model_name: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    event_date_from: date | None = None,
    event_date_to: date | None = None,
    publication_source: str | None = None,
    tournament_name: str | None = None,
    surface: str | None = None,
    odds_band: str | None = None,
    latest_only: bool = True,
    market: str | None = None,
    include_archived: bool = False,
    n_bins: int | None = None,
    min_bin_samples: int | None = None,
    include_comparison: bool = False,
    group_by_fold: bool = False,
    group_by_period: bool = False,
    settings: Settings | None = None,
) -> ProbabilityBandAnalysisRead:
    settings = settings or get_settings()
    resolved_bins = n_bins or settings.calibration_n_bins
    resolved_min = min_bin_samples or settings.calibration_min_bin_samples
    date_from = event_date_from or from_date
    date_to = event_date_to or to_date
    resolved_market: str | None = None

    if source == "live":
        if probability_kind != "raw":
            probability_kind = "raw"
        resolved_market = _resolve_live_market(market)
        records = _records_from_live_tips(
            db,
            from_date=from_date,
            to_date=to_date,
            event_date_from=event_date_from,
            event_date_to=event_date_to,
            model_version=model_version,
            model_name=model_name,
            publication_source=publication_source,
            tournament_name=tournament_name,
            surface=surface,
            odds_band=odds_band,
            latest_only=latest_only,
            market=resolved_market,
            include_archived=include_archived,
        )
        comparison_records = None
        effective_group_by_fold = False
    else:
        if not model_version:
            raise ValueError("model_version è obbligatorio per backtest e walk-forward.")
        resolved_model_name = model_name or MODEL_NAMES[0]
        wf_config = config_from_settings(settings)
        if include_comparison and band_dimension == "probability":
            all_kinds = collect_oos_comparison_records(
                model_version,
                wf_config,
                model_name=resolved_model_name,
                date_from=date_from,
                date_to=date_to,
            )
            records = all_kinds.get(probability_kind, [])
            comparison_records = {
                key: value for key, value in all_kinds.items() if key != probability_kind
            }
        else:
            records = collect_oos_band_records(
                model_version,
                wf_config,
                model_name=resolved_model_name,
                probability_kind=probability_kind,
                date_from=date_from,
                date_to=date_to,
            )
            comparison_records = None
        effective_group_by_fold = group_by_fold and source == "walk_forward"
        model_name = resolved_model_name

    result = analyze_band_records(
        records,
        source=source,
        band_dimension=band_dimension,
        probability_kind=probability_kind,
        n_bins=resolved_bins,
        min_bin_samples=resolved_min,
        group_by_fold=effective_group_by_fold,
        group_by_period=group_by_period,
        comparison_records=comparison_records,
    )
    if source == "backtest":
        result.notes.append(
            "Backtest: predizioni OOS walk-forward aggregate su tutti i fold (offline)."
        )
    elif source == "walk_forward":
        result.notes.append(
            "Walk-forward: stesse predizioni OOS con possibile breakdown per fold."
        )
    elif source == "live":
        result.notes.append(
            f"Live · mercato {resolved_market}: ledger PublishedPrediction "
            "(settlement a lettura; un mercato alla volta)."
        )

    return _result_to_read(
        result,
        model_version=model_version,
        model_name=model_name,
        market=resolved_market,
        from_date=from_date,
        to_date=to_date,
        event_date_from=event_date_from,
        event_date_to=event_date_to,
    )
