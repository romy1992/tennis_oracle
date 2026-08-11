"""Append-only pre-match odds snapshot ledger.

Stores per-bookmaker / per-selection detections without overwriting prior rows.
Duplicate detections (same fixture, selection, bookmaker, odds, type, source,
captured_at second) are skipped via ``detection_hash``.

Does not replace ``Fixture.odds`` / ``NextFixture.odds`` JSON blobs, nor the
unused ML ``odds_snapshot`` table.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.src.app.ml.datasets.odds_builder import (
    FixtureOddsRecord,
    HOME_SELECTION,
    AWAY_SELECTION,
    decimal_odd,
    implied_probability,
    match_winner_rows_from_record,
)
from backend.src.app.schemas.prematch_odds_snapshot import (
    PrematchOddsSnapshotCreate,
    PrematchOddsSnapshotFromPayload,
    PrematchOddsSnapshotIngestResponse,
    PrematchOddsSnapshotListResponse,
    PrematchOddsSnapshotRead,
    SnapshotType,
    SnapshotTypeOrAuto,
)
from backend.src.entity.fixture import Fixture
from backend.src.entity.next_fixture import NextFixture
from backend.src.entity.prematch_odds_snapshot import PrematchOddsSnapshot

logger = logging.getLogger(__name__)

ODDS_ROUND = 6
PROB_ROUND = 8
MARGIN_ROUND = 8


class PrematchOddsSnapshotError(Exception):
    """Domain error for the pre-match odds ledger."""

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


def _truncate_to_second(value: datetime) -> datetime:
    return value.replace(microsecond=0)


def compute_detection_hash(
    *,
    event_key: int,
    selection: str,
    bookmaker: str,
    odds: float,
    snapshot_type: str,
    source: str,
    captured_at: datetime,
) -> str:
    """Fingerprint of one detection; identical detections must share this hash."""
    payload = {
        "event_key": event_key,
        "selection": selection.strip(),
        "bookmaker": bookmaker.strip(),
        "odds": round(float(odds), ODDS_ROUND),
        "snapshot_type": snapshot_type,
        "source": source,
        "captured_at": _truncate_to_second(_as_utc_naive(captured_at)).isoformat(
            timespec="seconds"
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _to_read(row: PrematchOddsSnapshot) -> PrematchOddsSnapshotRead:
    return PrematchOddsSnapshotRead.model_validate(row)


def _latest_odds_for_selection(
    db: Session,
    *,
    event_key: int,
    selection: str,
    bookmaker: str,
) -> float | None:
    row = db.scalar(
        select(PrematchOddsSnapshot)
        .where(
            PrematchOddsSnapshot.event_key == event_key,
            PrematchOddsSnapshot.selection == selection,
            PrematchOddsSnapshot.bookmaker == bookmaker,
        )
        .order_by(
            PrematchOddsSnapshot.captured_at.desc(),
            PrematchOddsSnapshot.id.desc(),
        )
        .limit(1)
    )
    return None if row is None else float(row.odds)


def _has_any_snapshot(
    db: Session,
    *,
    event_key: int,
    selection: str,
    bookmaker: str,
) -> bool:
    return (
        db.scalar(
            select(PrematchOddsSnapshot.id)
            .where(
                PrematchOddsSnapshot.event_key == event_key,
                PrematchOddsSnapshot.selection == selection,
                PrematchOddsSnapshot.bookmaker == bookmaker,
            )
            .limit(1)
        )
        is not None
    )


def resolve_snapshot_type(
    db: Session,
    *,
    event_key: int,
    selection: str,
    bookmaker: str,
    requested: SnapshotTypeOrAuto,
) -> SnapshotType:
    if requested != "auto":
        return requested
    if _has_any_snapshot(db, event_key=event_key, selection=selection, bookmaker=bookmaker):
        return "observed"
    return "opening"


def _same_odds(a: float, b: float) -> bool:
    return round(float(a), ODDS_ROUND) == round(float(b), ODDS_ROUND)


def _should_skip_unchanged(
    db: Session,
    *,
    event_key: int,
    selection: str,
    bookmaker: str,
    odds: float,
    snapshot_type: SnapshotType,
) -> bool:
    """Skip observed/opening when the latest stored odds for the selection are unchanged.

    ``publication`` and ``closing`` always attempt insert (still deduped by hash).
    A second ``opening`` for the same bookmaker/selection is always skipped.
    """
    if snapshot_type == "opening" and _has_any_snapshot(
        db, event_key=event_key, selection=selection, bookmaker=bookmaker
    ):
        return True

    if snapshot_type in {"publication", "closing"}:
        return False

    latest = _latest_odds_for_selection(
        db, event_key=event_key, selection=selection, bookmaker=bookmaker
    )
    if latest is None:
        return False
    return _same_odds(latest, odds)


def record_snapshot(
    db: Session,
    payload: PrematchOddsSnapshotCreate,
    *,
    commit: bool = True,
) -> PrematchOddsSnapshotRead | None:
    """Append one snapshot. Returns ``None`` when skipped as duplicate/unchanged."""
    when = (
        _truncate_to_second(_as_utc_naive(payload.captured_at))
        if payload.captured_at
        else _truncate_to_second(_utc_now_naive())
    )
    odd = decimal_odd(payload.odds)
    if odd is None:
        raise PrematchOddsSnapshotError("Odds must be a decimal greater than 1.0.")

    selection = payload.selection.strip()
    bookmaker = payload.bookmaker.strip()
    snapshot_type = payload.snapshot_type

    if _should_skip_unchanged(
        db,
        event_key=payload.event_key,
        selection=selection,
        bookmaker=bookmaker,
        odds=odd,
        snapshot_type=snapshot_type,
    ):
        return None

    implied = (
        round(float(payload.implied_probability), PROB_ROUND)
        if payload.implied_probability is not None
        else round(implied_probability(odd), PROB_ROUND)
    )
    margin = (
        round(float(payload.margin), MARGIN_ROUND)
        if payload.margin is not None
        else 0.0
    )
    detection_hash = compute_detection_hash(
        event_key=payload.event_key,
        selection=selection,
        bookmaker=bookmaker,
        odds=odd,
        snapshot_type=snapshot_type,
        source=payload.source,
        captured_at=when,
    )
    existing = db.scalar(
        select(PrematchOddsSnapshot).where(
            PrematchOddsSnapshot.detection_hash == detection_hash
        )
    )
    if existing is not None:
        return None

    row = PrematchOddsSnapshot(
        event_key=payload.event_key,
        selection=selection,
        bookmaker=bookmaker,
        odds=round(odd, ODDS_ROUND),
        implied_probability=implied,
        margin=margin,
        captured_at=when,
        source=payload.source,
        snapshot_type=snapshot_type,
        detection_hash=detection_hash,
        market_side=payload.market_side,
        player_1_name=payload.player_1_name,
        player_2_name=payload.player_2_name,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        return None
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.refresh(row)
    return _to_read(row)


def _selection_label(
    market_side: str,
    *,
    player_1_name: str | None,
    player_2_name: str | None,
) -> str:
    if market_side == HOME_SELECTION and player_1_name:
        return player_1_name.strip()
    if market_side == AWAY_SELECTION and player_2_name:
        return player_2_name.strip()
    return market_side


def record_odds_payload(
    db: Session,
    payload: PrematchOddsSnapshotFromPayload,
    *,
    commit: bool = True,
) -> PrematchOddsSnapshotIngestResponse:
    """Parse a Home/Away odds matrix and append per-bookmaker selections.

    When ``event_live`` indicates the match has started, do **not** append new
    observed/opening rows (would be post-kickoff). Instead seal closing from the
    last pre-match detection when available.
    """
    if _is_truthy_live(payload.event_live):
        return seal_closing_from_last_prematch(
            db,
            event_key=payload.event_key,
            commit=commit,
        )

    when = (
        _truncate_to_second(_as_utc_naive(payload.captured_at))
        if payload.captured_at
        else _truncate_to_second(_utc_now_naive())
    )
    record = FixtureOddsRecord(
        match_id=payload.event_key,
        match_date=None,
        player_1_id=None,
        player_2_id=None,
        player_1_name=payload.player_1_name,
        player_2_name=payload.player_2_name,
        odds=payload.odds,
        event_live=payload.event_live,
    )
    market_rows = match_winner_rows_from_record(record)
    inserted_items: list[PrematchOddsSnapshotRead] = []
    skipped = 0

    for market_row in market_rows:
        bookmaker = str(market_row["bookmaker"])
        margin = round(float(market_row["bookmaker_margin"]), MARGIN_ROUND)
        sides: list[tuple[str, float, float]] = [
            (
                HOME_SELECTION,
                float(market_row["player_1_odds"]),
                float(market_row["implied_prob_player_1_raw"]),
            ),
            (
                AWAY_SELECTION,
                float(market_row["player_2_odds"]),
                float(market_row["implied_prob_player_2_raw"]),
            ),
        ]
        for market_side, odd, implied_raw in sides:
            selection = _selection_label(
                market_side,
                player_1_name=payload.player_1_name,
                player_2_name=payload.player_2_name,
            )
            snapshot_type = resolve_snapshot_type(
                db,
                event_key=payload.event_key,
                selection=selection,
                bookmaker=bookmaker,
                requested=payload.snapshot_type,
            )
            created = record_snapshot(
                db,
                PrematchOddsSnapshotCreate(
                    event_key=payload.event_key,
                    selection=selection,
                    bookmaker=bookmaker,
                    odds=odd,
                    implied_probability=implied_raw,
                    margin=margin,
                    source=payload.source,
                    snapshot_type=snapshot_type,
                    captured_at=when,
                    market_side=market_side,
                    player_1_name=payload.player_1_name,
                    player_2_name=payload.player_2_name,
                ),
                commit=False,
            )
            if created is None:
                skipped += 1
            else:
                inserted_items.append(created)

    if commit:
        db.commit()
        for item in inserted_items:
            # Re-load ids are already flushed; refresh not required for response.
            pass

    return PrematchOddsSnapshotIngestResponse(
        event_key=payload.event_key,
        inserted=len(inserted_items),
        skipped_duplicates=skipped,
        items=inserted_items,
    )


def record_odds_from_stored_fixture(
    db: Session,
    event_key: int,
    *,
    source: Literal[
        "api_tennis",
        "import",
        "admin_api",
        "telegram",
        "global_update",
        "publication",
        "system",
        "manual",
    ] = "admin_api",
    snapshot_type: SnapshotTypeOrAuto = "auto",
    captured_at: datetime | None = None,
    commit: bool = True,
) -> PrematchOddsSnapshotIngestResponse:
    """Capture snapshots from current ``NextFixture`` / ``Fixture`` odds JSON."""
    next_row = db.scalar(select(NextFixture).where(NextFixture.event_key == event_key))
    fixture = None if next_row is not None else db.scalar(
        select(Fixture).where(Fixture.event_key == event_key)
    )
    row = next_row or fixture
    if row is None:
        raise PrematchOddsSnapshotError(
            f"Fixture {event_key} not found.",
            status_code=404,
        )
    odds = getattr(row, "odds", None)
    if not odds:
        raise PrematchOddsSnapshotError(
            f"No odds stored for fixture {event_key}.",
            status_code=404,
        )
    return record_odds_payload(
        db,
        PrematchOddsSnapshotFromPayload(
            event_key=event_key,
            odds=odds if isinstance(odds, dict) else {},
            source=source,
            snapshot_type=snapshot_type,
            captured_at=captured_at,
            player_1_name=getattr(row, "event_first_player", None),
            player_2_name=getattr(row, "event_second_player", None),
            event_live=getattr(row, "event_live", None),
        ),
        commit=commit,
    )


def get_snapshot(db: Session, snapshot_id: int) -> PrematchOddsSnapshotRead:
    row = db.get(PrematchOddsSnapshot, snapshot_id)
    if row is None:
        raise PrematchOddsSnapshotError("Odds snapshot not found.", status_code=404)
    return _to_read(row)


def _apply_list_filters(
    stmt,
    *,
    event_key: int | None,
    bookmaker: str | None,
    selection: str | None,
    snapshot_type: str | None,
    source: str | None,
    from_date: date | None,
    to_date: date | None,
):
    if event_key is not None:
        stmt = stmt.where(PrematchOddsSnapshot.event_key == event_key)
    if bookmaker:
        stmt = stmt.where(PrematchOddsSnapshot.bookmaker == bookmaker)
    if selection:
        stmt = stmt.where(PrematchOddsSnapshot.selection == selection)
    if snapshot_type:
        stmt = stmt.where(PrematchOddsSnapshot.snapshot_type == snapshot_type)
    if source:
        stmt = stmt.where(PrematchOddsSnapshot.source == source)
    if from_date is not None:
        stmt = stmt.where(
            PrematchOddsSnapshot.captured_at >= datetime.combine(from_date, time.min)
        )
    if to_date is not None:
        stmt = stmt.where(
            PrematchOddsSnapshot.captured_at <= datetime.combine(to_date, time.max)
        )
    return stmt


def list_snapshots(
    db: Session,
    *,
    event_key: int | None = None,
    bookmaker: str | None = None,
    selection: str | None = None,
    snapshot_type: str | None = None,
    source: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PrematchOddsSnapshotListResponse:
    filter_kwargs = {
        "event_key": event_key,
        "bookmaker": bookmaker,
        "selection": selection,
        "snapshot_type": snapshot_type,
        "source": source,
        "from_date": from_date,
        "to_date": to_date,
    }
    stmt = _apply_list_filters(select(PrematchOddsSnapshot), **filter_kwargs)
    count_stmt = _apply_list_filters(
        select(func.count()).select_from(PrematchOddsSnapshot),
        **filter_kwargs,
    )
    total = int(db.scalar(count_stmt) or 0)
    rows = list(
        db.scalars(
            stmt.order_by(
                PrematchOddsSnapshot.captured_at.desc(),
                PrematchOddsSnapshot.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return PrematchOddsSnapshotListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[_to_read(row) for row in rows],
    )


def _is_truthy_live(event_live: Any) -> bool:
    if event_live is True:
        return True
    if isinstance(event_live, (int, float)) and int(event_live) != 0:
        return True
    if isinstance(event_live, str):
        return event_live.strip().lower() in {"1", "true", "yes", "live", "inprogress"}
    return False


def _kickoff_from_row(row: NextFixture | Fixture, *, require_event_time: bool = False) -> datetime | None:
    """Scheduled kickoff in UTC-naive for an already-loaded row (no extra query).

    ``require_event_time=True`` returns ``None`` instead of defaulting to
    midnight when ``event_time`` is missing (used by the closing-odds capture
    window, where an unknown kickoff time must never look "imminent").
    """
    from zoneinfo import ZoneInfo

    if row is None or row.event_date is None:
        return None
    if row.event_time is None:
        if require_event_time:
            return None
        local_time = time(0, 0)
    else:
        local_time = row.event_time
    rome = ZoneInfo("Europe/Rome")
    local_dt = datetime.combine(row.event_date, local_time, tzinfo=rome)
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


def _kickoff_utc_naive(db: Session, event_key: int) -> datetime | None:
    """Scheduled kickoff in UTC-naive (Europe/Rome local date/time → UTC)."""
    next_row = db.scalar(select(NextFixture).where(NextFixture.event_key == event_key))
    fixture = None if next_row is not None else db.scalar(
        select(Fixture).where(Fixture.event_key == event_key)
    )
    row = next_row or fixture
    return _kickoff_from_row(row)


def seal_closing_from_last_prematch(
    db: Session,
    *,
    event_key: int,
    kickoff_utc: datetime | None = None,
    commit: bool = True,
) -> PrematchOddsSnapshotIngestResponse:
    """Promote the last *pre-match* opening/observed quote to ``closing``.

    Does **not** invent odds. Copies the last stored pre-match detection
    (``captured_at`` kept as the original pre-match timestamp). Skips when no
    usable pre-match row exists. Never uses a quote captured after kickoff.
    Idempotent for already-sealed (selection, bookmaker) pairs.

    Note: without a dedicated pre-kickoff polling job, this is a best-effort
    label on the last observed import — not a guaranteed true closing line.
    """
    kickoff = kickoff_utc or _kickoff_utc_naive(db, event_key)
    prematch_types = ("opening", "observed")
    rows = list(
        db.scalars(
            select(PrematchOddsSnapshot)
            .where(
                PrematchOddsSnapshot.event_key == event_key,
                PrematchOddsSnapshot.snapshot_type.in_(prematch_types),
            )
            .order_by(
                PrematchOddsSnapshot.captured_at.desc(),
                PrematchOddsSnapshot.id.desc(),
            )
        ).all()
    )

    latest_by_key: dict[tuple[str, str], PrematchOddsSnapshot] = {}
    for row in rows:
        if kickoff is not None and _as_utc_naive(row.captured_at) > kickoff:
            continue
        key = (row.selection, row.bookmaker)
        if key not in latest_by_key:
            latest_by_key[key] = row

    inserted_items: list[PrematchOddsSnapshotRead] = []
    skipped = 0
    for (selection, bookmaker), source_row in latest_by_key.items():
        already = db.scalar(
            select(PrematchOddsSnapshot.id)
            .where(
                PrematchOddsSnapshot.event_key == event_key,
                PrematchOddsSnapshot.selection == selection,
                PrematchOddsSnapshot.bookmaker == bookmaker,
                PrematchOddsSnapshot.snapshot_type == "closing",
            )
            .limit(1)
        )
        if already is not None:
            skipped += 1
            continue
        created = record_snapshot(
            db,
            PrematchOddsSnapshotCreate(
                event_key=event_key,
                selection=selection,
                bookmaker=bookmaker,
                odds=float(source_row.odds),
                implied_probability=float(source_row.implied_probability),
                margin=float(source_row.margin),
                source="system",
                snapshot_type="closing",
                captured_at=_as_utc_naive(source_row.captured_at),
                market_side=source_row.market_side,
                player_1_name=source_row.player_1_name,
                player_2_name=source_row.player_2_name,
            ),
            commit=False,
        )
        if created is None:
            skipped += 1
        else:
            inserted_items.append(created)

    if commit:
        db.commit()

    return PrematchOddsSnapshotIngestResponse(
        event_key=event_key,
        inserted=len(inserted_items),
        skipped_duplicates=skipped,
        items=inserted_items,
    )


def capture_imported_odds(
    *,
    event_key: int,
    odds: dict[str, Any] | None,
    player_1_name: str | None = None,
    player_2_name: str | None = None,
    event_live: Any = None,
    source: str = "import",
) -> PrematchOddsSnapshotIngestResponse | None:
    """Best-effort capture from import path (own Session; never raises to caller)."""
    if not odds or not isinstance(odds, dict):
        return None
    try:
        from backend.src.app.db.session import SessionLocal

        with SessionLocal() as db:
            return record_odds_payload(
                db,
                PrematchOddsSnapshotFromPayload(
                    event_key=event_key,
                    odds=odds,
                    source=source,  # type: ignore[arg-type]
                    snapshot_type="auto",
                    player_1_name=player_1_name,
                    player_2_name=player_2_name,
                    event_live=event_live,
                ),
                commit=True,
            )
    except Exception:
        logger.exception(
            "Failed to capture prematch odds history for event_key=%s",
            event_key,
        )
        return None


# ---------------------------------------------------------------------------
# Dedicated pre-kickoff closing-odds capture (job run_closing_odds_capture).
#
# The daily import only calls ``seal_closing_from_last_prematch`` opportunistically
# (when the batch import happens to run while the match is already live), which
# produces very low and irregular CLV coverage (see docs/SCHEDULING.md). Running
# this on a frequent cron (every 1-5 minutes) in the last N minutes before kickoff
# writes ``snapshot_type="closing"`` directly and repeatedly; ``_resolve_clv`` in
# ``published_live_stats.py`` already picks the row with the latest ``captured_at``
# per bookmaker, so multiple closing rows per fixture are expected and correctly
# collapse to "the last quote seen before kickoff" without any consumer changes.
# ---------------------------------------------------------------------------


def find_fixtures_pending_closing_capture(
    db: Session,
    *,
    window_minutes: int,
    now_utc_naive: datetime | None = None,
) -> list[tuple[int, datetime]]:
    """Event keys whose scheduled kickoff falls within ``(now, now + window]``.

    Only considers ``next_fixture`` rows with a known ``event_time`` (an
    unknown/midnight-defaulted time must never look "imminent") and not yet
    promoted to ``Fixture`` (``is_completed=False``). Returns
    ``(event_key, kickoff_utc_naive)`` pairs sorted by nearest kickoff first.
    """
    now = now_utc_naive if now_utc_naive is not None else _utc_now_naive()
    if window_minutes <= 0:
        return []
    horizon_date = (now + timedelta(minutes=window_minutes)).date()

    candidates = db.scalars(
        select(NextFixture).where(
            NextFixture.is_completed.is_(False),
            NextFixture.event_date.is_not(None),
            NextFixture.event_time.is_not(None),
            NextFixture.event_date >= (now.date() - timedelta(days=1)),
            NextFixture.event_date <= horizon_date,
        )
    ).all()

    pending: list[tuple[int, datetime]] = []
    for row in candidates:
        kickoff = _kickoff_from_row(row, require_event_time=True)
        if kickoff is None:
            continue
        if now < kickoff <= now + timedelta(minutes=window_minutes):
            pending.append((row.event_key, kickoff))
    pending.sort(key=lambda item: item[1])
    return pending


def capture_closing_odds_for_fixture(
    db: Session,
    *,
    event_key: int,
    commit: bool = True,
) -> PrematchOddsSnapshotIngestResponse | None:
    """Fetch fresh odds from the provider and append ``closing`` snapshot rows.

    Intended only for the dedicated pre-kickoff job (fixture must already be
    inside its capture window). Returns ``None`` (never raises) when the
    fixture is missing or the provider returns no odds, so one bad fixture
    never blocks the rest of the batch.
    """
    # Local import: import_next_fixtures imports this module at module scope,
    # so a top-level import here would be circular.
    from backend.src.service.import_next_fixtures import fetch_odds_for_match

    row = db.scalar(select(NextFixture).where(NextFixture.event_key == event_key))
    if row is None:
        return None
    odds = fetch_odds_for_match(event_key)
    if not odds:
        return None
    return record_odds_payload(
        db,
        PrematchOddsSnapshotFromPayload(
            event_key=event_key,
            odds=odds,
            source="system",
            snapshot_type="closing",
            player_1_name=row.event_first_player,
            player_2_name=row.event_second_player,
            event_live=None,
        ),
        commit=commit,
    )


def run_closing_odds_capture_once(
    db: Session,
    *,
    window_minutes: int,
    commit: bool = True,
) -> dict[str, Any]:
    """One capture pass: find fixtures entering the window, fetch + append closing odds.

    Meant to be invoked by ``backend.src.jobs.run_closing_odds_capture`` on a
    frequent external cron; this function itself does not loop/sleep.
    """
    pending = find_fixtures_pending_closing_capture(db, window_minutes=window_minutes)
    summary: dict[str, Any] = {
        "window_minutes": window_minutes,
        "candidates": len(pending),
        "captured": 0,
        "inserted_rows": 0,
        "skipped_no_odds": 0,
        "failed": 0,
        "event_keys": [event_key for event_key, _kickoff in pending],
    }
    for event_key, _kickoff in pending:
        try:
            result = capture_closing_odds_for_fixture(db, event_key=event_key, commit=commit)
        except Exception:
            logger.exception(
                "Closing odds capture failed event_key=%s",
                event_key,
            )
            db.rollback()
            summary["failed"] += 1
            continue
        if result is None:
            summary["skipped_no_odds"] += 1
            continue
        summary["captured"] += 1
        summary["inserted_rows"] += result.inserted
    return summary



