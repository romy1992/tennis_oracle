"""Immutable published-prediction ledger (append-only).

Does not replace ``MatchPrediction`` (ML upsert) or ``BettingSlip*`` (daily slips).
After the match start datetime, existing rows cannot be corrected; corrections
always insert a new version linked to the previous row.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.src.app.schemas.published_prediction import (
    PublishedPredictionCorrection,
    PublishedPredictionCreate,
    PublishedPredictionListResponse,
    PublishedPredictionRead,
    PublishedPredictionVersionChainResponse,
)
from backend.src.app.services.match_lifecycle import classify_match_lifecycle, is_terminal_lifecycle
from backend.src.entity.fixture import Fixture
from backend.src.entity.next_fixture import NextFixture
from backend.src.entity.published_prediction import PublishedPrediction

ROME_TZ = ZoneInfo("Europe/Rome")


class PublishedPredictionError(Exception):
    """Domain error for the publication ledger."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _combine_match_start(
    event_date: date | None,
    event_time: time | None,
) -> datetime | None:
    """Interpret scheduled local (Europe/Rome) kickoff as UTC-naive."""
    if event_date is None:
        return None
    local_time = event_time or time(0, 0)
    local_dt = datetime.combine(event_date, local_time, tzinfo=ROME_TZ)
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


def _is_explicitly_live(event_status: str | None, lifecycle: str) -> bool:
    """True only for clear in-play signals (avoid 'Not Started' → started)."""
    if lifecycle != "started":
        return False
    status = (event_status or "").strip().lower()
    if "not started" in status or status in {"", "-", "scheduled", "upcoming", "ns"}:
        return False
    return True


def _load_match_schedule(db: Session, event_key: int) -> tuple[
    date | None,
    time | None,
    str | None,
    str | None,
    str | None,
    str | None,
    bool,
]:
    """Return schedule + display fields and whether the match has already started."""
    next_row = db.scalar(select(NextFixture).where(NextFixture.event_key == event_key))
    if next_row is not None:
        lifecycle = classify_match_lifecycle(
            event_status=next_row.event_status,
            event_winner=None,
            is_completed=next_row.is_completed,
        )
        started = bool(next_row.is_completed) or is_terminal_lifecycle(lifecycle)
        if _is_explicitly_live(next_row.event_status, lifecycle):
            started = True
        start_at = _combine_match_start(next_row.event_date, next_row.event_time)
        if start_at is not None and _utc_now_naive() >= start_at:
            started = True
        return (
            next_row.event_date,
            next_row.event_time,
            next_row.event_first_player,
            next_row.event_second_player,
            next_row.tournament_name,
            next_row.event_status,
            started,
        )

    fixture = db.scalar(select(Fixture).where(Fixture.event_key == event_key))
    if fixture is not None:
        lifecycle = classify_match_lifecycle(
            event_status=fixture.event_status,
            event_winner=fixture.event_winner,
            event_final_result=fixture.event_final_result,
            event_live=fixture.event_live,
        )
        started = is_terminal_lifecycle(lifecycle) or bool(fixture.event_winner)
        if _is_explicitly_live(fixture.event_status, lifecycle):
            started = True
        start_at = _combine_match_start(fixture.event_date, fixture.event_time)
        if start_at is not None and _utc_now_naive() >= start_at:
            started = True
        return (
            fixture.event_date,
            fixture.event_time,
            fixture.event_first_player,
            fixture.event_second_player,
            fixture.tournament_name,
            fixture.event_status,
            started,
        )

    return None, None, None, None, None, None, False


def match_has_started(db: Session, event_key: int) -> bool:
    *_rest, started = _load_match_schedule(db, event_key)
    return started


def compute_content_hash(
    *,
    event_key: int,
    selection: str,
    model_version: str,
    model_name: str,
    probability: float,
    odds: float | None,
    void_odds: float | None,
    edge: float | None,
    unit_stake: float,
    publication_source: str,
    initial_status: str,
    content_version: int,
    publication_id: str,
) -> str:
    payload = {
        "publication_id": publication_id,
        "content_version": content_version,
        "event_key": event_key,
        "selection": selection,
        "model_version": model_version,
        "model_name": model_name,
        "probability": round(float(probability), 8),
        "odds": None if odds is None else round(float(odds), 6),
        "void_odds": None if void_odds is None else round(float(void_odds), 6),
        "edge": None if edge is None else round(float(edge), 6),
        "unit_stake": round(float(unit_stake), 6),
        "publication_source": publication_source,
        "initial_status": initial_status,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _latest_version_ids(db: Session, publication_ids: list[str]) -> set[int]:
    if not publication_ids:
        return set()
    rows = db.execute(
        select(
            PublishedPrediction.publication_id,
            func.max(PublishedPrediction.content_version).label("max_version"),
        )
        .where(PublishedPrediction.publication_id.in_(publication_ids))
        .group_by(PublishedPrediction.publication_id)
    ).all()
    if not rows:
        return set()
    latest_ids: set[int] = set()
    for publication_id, max_version in rows:
        row_id = db.scalar(
            select(PublishedPrediction.id).where(
                PublishedPrediction.publication_id == publication_id,
                PublishedPrediction.content_version == max_version,
            )
        )
        if row_id is not None:
            latest_ids.add(row_id)
    return latest_ids


def _to_read(
    row: PublishedPrediction,
    *,
    is_latest: bool,
    match_started: bool,
) -> PublishedPredictionRead:
    return PublishedPredictionRead(
        id=row.id,
        publication_id=row.publication_id,
        content_version=row.content_version,
        previous_version_id=row.previous_version_id,
        event_key=row.event_key,
        selection=row.selection,
        model_version=row.model_version,
        model_name=row.model_name,
        probability=row.probability,
        odds=row.odds,
        void_odds=row.void_odds,
        edge=row.edge,
        unit_stake=row.unit_stake,
        published_at=row.published_at,
        publication_source=row.publication_source,
        initial_status=row.initial_status,
        content_hash=row.content_hash,
        player_1_name=row.player_1_name,
        player_2_name=row.player_2_name,
        tournament_name=row.tournament_name,
        event_date=row.event_date,
        event_time=row.event_time,
        match_prediction_id=row.match_prediction_id,
        betting_slip_pick_id=row.betting_slip_pick_id,
        is_latest=is_latest,
        match_started=match_started,
    )


def publish_prediction(
    db: Session,
    payload: PublishedPredictionCreate,
    *,
    published_at: datetime | None = None,
) -> PublishedPredictionRead:
    (
        sched_date,
        sched_time,
        p1,
        p2,
        tournament,
        _status,
        started,
    ) = _load_match_schedule(db, payload.event_key)
    if started:
        raise PublishedPredictionError(
            "Cannot publish after the match has started; ledger is frozen for this event.",
            status_code=409,
        )

    publication_id = str(uuid.uuid4())
    content_version = 1
    when = _as_utc_naive(published_at) if published_at else _utc_now_naive()
    content_hash = compute_content_hash(
        event_key=payload.event_key,
        selection=payload.selection.strip(),
        model_version=payload.model_version,
        model_name=payload.model_name,
        probability=payload.probability,
        odds=payload.odds,
        void_odds=payload.void_odds,
        edge=payload.edge,
        unit_stake=payload.unit_stake,
        publication_source=payload.publication_source,
        initial_status=payload.initial_status,
        content_version=content_version,
        publication_id=publication_id,
    )
    row = PublishedPrediction(
        publication_id=publication_id,
        content_version=content_version,
        previous_version_id=None,
        event_key=payload.event_key,
        selection=payload.selection.strip(),
        model_version=payload.model_version,
        model_name=payload.model_name,
        probability=payload.probability,
        odds=payload.odds,
        void_odds=payload.void_odds,
        edge=payload.edge,
        unit_stake=payload.unit_stake,
        published_at=when,
        publication_source=payload.publication_source,
        initial_status=payload.initial_status,
        content_hash=content_hash,
        player_1_name=payload.player_1_name or p1,
        player_2_name=payload.player_2_name or p2,
        tournament_name=payload.tournament_name or tournament,
        event_date=payload.event_date or sched_date,
        event_time=payload.event_time or sched_time,
        match_prediction_id=payload.match_prediction_id,
        betting_slip_pick_id=payload.betting_slip_pick_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_read(row, is_latest=True, match_started=False)


def correct_published_prediction(
    db: Session,
    *,
    previous_id: int,
    payload: PublishedPredictionCorrection,
    published_at: datetime | None = None,
) -> PublishedPredictionRead:
    previous = db.get(PublishedPrediction, previous_id)
    if previous is None:
        raise PublishedPredictionError("Published prediction not found.", status_code=404)

    latest_id = db.scalar(
        select(PublishedPrediction.id)
        .where(PublishedPrediction.publication_id == previous.publication_id)
        .order_by(PublishedPrediction.content_version.desc())
        .limit(1)
    )
    if latest_id != previous.id:
        raise PublishedPredictionError(
            "Corrections must be applied to the latest version of a publication.",
            status_code=409,
        )

    if match_has_started(db, previous.event_key):
        raise PublishedPredictionError(
            "Cannot correct a publication after the match has started.",
            status_code=409,
        )

    content_version = int(previous.content_version) + 1
    selection = (payload.selection or previous.selection).strip()
    model_version = payload.model_version or previous.model_version
    model_name = payload.model_name or previous.model_name
    probability = (
        previous.probability if payload.probability is None else payload.probability
    )
    odds = previous.odds if payload.odds is None else payload.odds
    void_odds = previous.void_odds if payload.void_odds is None else payload.void_odds
    edge = previous.edge if payload.edge is None else payload.edge
    unit_stake = (
        previous.unit_stake if payload.unit_stake is None else payload.unit_stake
    )
    when = _as_utc_naive(published_at) if published_at else _utc_now_naive()
    content_hash = compute_content_hash(
        event_key=previous.event_key,
        selection=selection,
        model_version=model_version,
        model_name=model_name,
        probability=probability,
        odds=odds,
        void_odds=void_odds,
        edge=edge,
        unit_stake=unit_stake,
        publication_source=payload.publication_source,
        initial_status=payload.initial_status,
        content_version=content_version,
        publication_id=previous.publication_id,
    )
    row = PublishedPrediction(
        publication_id=previous.publication_id,
        content_version=content_version,
        previous_version_id=previous.id,
        event_key=previous.event_key,
        selection=selection,
        model_version=model_version,
        model_name=model_name,
        probability=probability,
        odds=odds,
        void_odds=void_odds,
        edge=edge,
        unit_stake=unit_stake,
        published_at=when,
        publication_source=payload.publication_source,
        initial_status=payload.initial_status,
        content_hash=content_hash,
        player_1_name=payload.player_1_name
        if payload.player_1_name is not None
        else previous.player_1_name,
        player_2_name=payload.player_2_name
        if payload.player_2_name is not None
        else previous.player_2_name,
        tournament_name=payload.tournament_name
        if payload.tournament_name is not None
        else previous.tournament_name,
        event_date=payload.event_date
        if payload.event_date is not None
        else previous.event_date,
        event_time=payload.event_time
        if payload.event_time is not None
        else previous.event_time,
        match_prediction_id=payload.match_prediction_id
        if payload.match_prediction_id is not None
        else previous.match_prediction_id,
        betting_slip_pick_id=payload.betting_slip_pick_id
        if payload.betting_slip_pick_id is not None
        else previous.betting_slip_pick_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_read(row, is_latest=True, match_started=False)


def get_published_prediction(db: Session, prediction_id: int) -> PublishedPredictionRead:
    row = db.get(PublishedPrediction, prediction_id)
    if row is None:
        raise PublishedPredictionError("Published prediction not found.", status_code=404)
    latest_ids = _latest_version_ids(db, [row.publication_id])
    return _to_read(
        row,
        is_latest=row.id in latest_ids,
        match_started=match_has_started(db, row.event_key),
    )


def list_publication_versions(
    db: Session,
    publication_id: str,
) -> PublishedPredictionVersionChainResponse:
    rows = list(
        db.scalars(
            select(PublishedPrediction)
            .where(PublishedPrediction.publication_id == publication_id)
            .order_by(PublishedPrediction.content_version.asc())
        ).all()
    )
    if not rows:
        raise PublishedPredictionError("Publication not found.", status_code=404)
    latest_ids = _latest_version_ids(db, [publication_id])
    started = match_has_started(db, rows[0].event_key)
    return PublishedPredictionVersionChainResponse(
        publication_id=publication_id,
        items=[
            _to_read(row, is_latest=row.id in latest_ids, match_started=started)
            for row in rows
        ],
    )


def _apply_list_filters(
    stmt,
    *,
    from_date: date | None,
    to_date: date | None,
    event_key: int | None,
    model_version: str | None,
    model_name: str | None,
    publication_source: str | None,
):
    if from_date is not None:
        start = datetime.combine(from_date, time.min)
        stmt = stmt.where(PublishedPrediction.published_at >= start)
    if to_date is not None:
        end = datetime.combine(to_date, time.max)
        stmt = stmt.where(PublishedPrediction.published_at <= end)
    if event_key is not None:
        stmt = stmt.where(PublishedPrediction.event_key == event_key)
    if model_version:
        stmt = stmt.where(PublishedPrediction.model_version == model_version)
    if model_name:
        stmt = stmt.where(PublishedPrediction.model_name == model_name)
    if publication_source:
        stmt = stmt.where(PublishedPrediction.publication_source == publication_source)
    return stmt


def list_published_predictions(
    db: Session,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    event_key: int | None = None,
    model_version: str | None = None,
    model_name: str | None = None,
    publication_source: str | None = None,
    latest_only: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> PublishedPredictionListResponse:
    filter_kwargs = {
        "from_date": from_date,
        "to_date": to_date,
        "event_key": event_key,
        "model_version": model_version,
        "model_name": model_name,
        "publication_source": publication_source,
    }
    stmt = _apply_list_filters(select(PublishedPrediction), **filter_kwargs)
    count_stmt = _apply_list_filters(
        select(func.count()).select_from(PublishedPrediction),
        **filter_kwargs,
    )

    if latest_only:
        latest_subq = (
            select(
                PublishedPrediction.publication_id.label("pid"),
                func.max(PublishedPrediction.content_version).label("max_v"),
            )
            .group_by(PublishedPrediction.publication_id)
            .subquery()
        )
        join_on = (PublishedPrediction.publication_id == latest_subq.c.pid) & (
            PublishedPrediction.content_version == latest_subq.c.max_v
        )
        stmt = stmt.join(latest_subq, join_on)
        count_stmt = _apply_list_filters(
            select(func.count())
            .select_from(PublishedPrediction)
            .join(latest_subq, join_on),
            **filter_kwargs,
        )

    total = int(db.scalar(count_stmt) or 0)
    rows = list(
        db.scalars(
            stmt.order_by(
                PublishedPrediction.published_at.desc(),
                PublishedPrediction.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        ).all()
    )
    publication_ids = [row.publication_id for row in rows]
    latest_ids = _latest_version_ids(db, publication_ids)
    started_cache: dict[int, bool] = {}
    items: list[PublishedPredictionRead] = []
    for row in rows:
        if row.event_key not in started_cache:
            started_cache[row.event_key] = match_has_started(db, row.event_key)
        items.append(
            _to_read(
                row,
                is_latest=row.id in latest_ids,
                match_started=started_cache[row.event_key],
            )
        )
    return PublishedPredictionListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=items,
    )
