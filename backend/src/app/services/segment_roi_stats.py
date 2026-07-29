"""Orchestrate segment ROI analysis across live and OOS sources."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.src.app.core.config import Settings, get_settings
from backend.src.app.ml.training.probability_band_analysis import AnalysisSource
from backend.src.app.ml.training.segment_roi_analysis import (
    FixtureSegmentMetadata,
    SegmentAnalysisRecord,
    SegmentDimension,
    analyze_segment_records,
    assign_favorite_role,
    assign_odds_band,
    collect_oos_segment_records,
)
from backend.src.app.ml.training.walk_forward import MODEL_NAMES
from backend.src.app.schemas.segment_roi import (
    SegmentRoiAnalysisRead,
    SegmentRoiBucketRead,
    SegmentRoiGroupRead,
)
from backend.src.app.services.published_live_stats import (
    period_key,
    settle_published_tips,
)
from backend.src.app.services.walk_forward import config_from_settings
from backend.src.entity.fixture import Fixture
from backend.src.entity.tournaments import Tournament


def _bucket_to_read(item) -> SegmentRoiBucketRead:
    return SegmentRoiBucketRead(**item.to_dict())


def _load_fixture_segment_metadata(
    db: Session,
    match_ids: list[int],
) -> dict[int, FixtureSegmentMetadata]:
    if not match_ids:
        return {}

    fixtures = list(
        db.scalars(select(Fixture).where(Fixture.event_key.in_(match_ids))).all()
    )
    tournament_keys = {
        row.tournament_key for row in fixtures if row.tournament_key is not None
    }
    surfaces_by_tournament: dict[int, str | None] = {}
    circuits_by_tournament: dict[int, str | None] = {}
    if tournament_keys:
        for tournament in db.scalars(
            select(Tournament).where(Tournament.tournament_key.in_(tournament_keys))
        ).all():
            if tournament.tournament_key is not None:
                key = int(tournament.tournament_key)
                surfaces_by_tournament[key] = tournament.tournament_sourface
                circuits_by_tournament[key] = tournament.event_type_type

    metadata: dict[int, FixtureSegmentMetadata] = {}
    for fixture in fixtures:
        surface = None
        circuit = fixture.event_type_type
        if fixture.tournament_key is not None:
            tk = int(fixture.tournament_key)
            surface = surfaces_by_tournament.get(tk)
            circuit = circuit or circuits_by_tournament.get(tk)
        metadata[int(fixture.event_key)] = FixtureSegmentMetadata(
            tournament_name=fixture.tournament_name,
            circuit=circuit,
            round_name=fixture.tournament_round,
            surface=surface,
        )
    return metadata


def _enrich_oos_records(
    db: Session,
    records: list[SegmentAnalysisRecord],
) -> list[SegmentAnalysisRecord]:
    match_ids = [item.match_id for item in records if item.match_id is not None]
    if not match_ids:
        return records
    fixture_meta = _load_fixture_segment_metadata(db, match_ids)
    enriched: list[SegmentAnalysisRecord] = []
    for record in records:
        meta = fixture_meta.get(record.match_id) if record.match_id is not None else None
        if meta is None:
            enriched.append(record)
            continue
        enriched.append(
            replace(
                record,
                surface=record.surface or meta.surface,
                tournament_name=record.tournament_name or meta.tournament_name,
                circuit=record.circuit or meta.circuit,
                round_name=record.round_name or meta.round_name,
            )
        )
    return enriched


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
) -> list[SegmentAnalysisRecord]:
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
    )
    event_keys = [item.tip.event_key for item in settled]
    fixture_meta = _load_fixture_segment_metadata(db, event_keys)

    records: list[SegmentAnalysisRecord] = []
    for item in settled:
        tip = item.tip
        prob = float(tip.probability)
        won: bool | None
        void = item.outcome == "void"
        if item.outcome in ("won", "lost"):
            won = item.outcome == "won"
        else:
            won = None

        odds = float(tip.odds) if tip.odds is not None else None
        odds_band_key, _ = assign_odds_band(odds)
        favorite_key, _ = assign_favorite_role(odds)
        meta = fixture_meta.get(tip.event_key)

        records.append(
            SegmentAnalysisRecord(
                match_date=tip.event_date,
                fold_index=None,
                match_id=tip.event_key,
                model_version=tip.model_version,
                model_name=tip.model_name,
                prob_used=prob,
                edge_pct=float(tip.edge) if tip.edge is not None else None,
                odds=odds,
                won=won,
                void=void,
                stake=float(tip.unit_stake),
                profit=float(item.profit),
                period_key=period_key(tip.event_date, tip.published_at),
                surface=item.surface or (meta.surface if meta else None),
                tournament_name=tip.tournament_name or (meta.tournament_name if meta else None),
                circuit=meta.circuit if meta else None,
                level=None,
                round_name=meta.round_name if meta else None,
                favorite_role=favorite_key,
                odds_band=odds_band_key,
                bookmaker=None,
                publication_source=tip.publication_source,
            )
        )
    return records


def _result_to_read(
    result,
    *,
    model_version: str | None,
    model_name: str | None,
    from_date: date | None,
    to_date: date | None,
    event_date_from: date | None,
    event_date_to: date | None,
) -> SegmentRoiAnalysisRead:
    return SegmentRoiAnalysisRead(
        source=result.source,
        segment_dimension=result.segment_dimension,
        min_segment_samples=result.min_segment_samples,
        model_version=model_version,
        model_name=model_name,
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
        segments=[_bucket_to_read(item) for item in result.segments],
        by_fold=[
            SegmentRoiGroupRead(
                fold_index=item.get("fold_index"),
                period=None,
                predictions_total=item["predictions_total"],
                closed=item["closed"],
                void=item["void"],
                open=item["open"],
                won=item["won"],
                lost=item["lost"],
                segments=[SegmentRoiBucketRead(**segment) for segment in item["segments"]],
            )
            for item in result.by_fold
        ],
        by_period=[
            SegmentRoiGroupRead(
                fold_index=None,
                period=item.get("period"),
                predictions_total=item["predictions_total"],
                closed=item["closed"],
                void=item["void"],
                open=item["open"],
                won=item["won"],
                lost=item["lost"],
                segments=[SegmentRoiBucketRead(**segment) for segment in item["segments"]],
            )
            for item in result.by_period
        ],
        notes=result.notes,
    )


def compute_segment_roi_analysis(
    db: Session,
    *,
    source: AnalysisSource,
    segment_dimension: SegmentDimension = "surface",
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
    min_segment_samples: int | None = None,
    group_by_fold: bool = False,
    group_by_period: bool = False,
    settings: Settings | None = None,
) -> SegmentRoiAnalysisRead:
    settings = settings or get_settings()
    resolved_min = min_segment_samples or settings.calibration_min_bin_samples
    date_from = event_date_from or from_date
    date_to = event_date_to or to_date

    if source == "live":
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
        )
        effective_group_by_fold = False
    else:
        if not model_version:
            raise ValueError("model_version è obbligatorio per backtest e walk-forward.")
        resolved_model_name = model_name or MODEL_NAMES[0]
        wf_config = config_from_settings(settings)
        records = collect_oos_segment_records(
            model_version,
            wf_config,
            model_name=resolved_model_name,
            date_from=date_from,
            date_to=date_to,
        )
        records = _enrich_oos_records(db, records)
        effective_group_by_fold = group_by_fold and source == "walk_forward"
        model_name = resolved_model_name

    result = analyze_segment_records(
        records,
        source=source,
        segment_dimension=segment_dimension,
        min_segment_samples=resolved_min,
        group_by_fold=effective_group_by_fold,
        group_by_period=group_by_period,
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
            "Live: ledger PublishedPrediction con settlement a lettura (non backtest ML)."
        )

    return _result_to_read(
        result,
        model_version=model_version,
        model_name=model_name,
        from_date=from_date,
        to_date=to_date,
        event_date_from=event_date_from,
        event_date_to=event_date_to,
    )
