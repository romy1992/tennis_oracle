"""Frequent live-score refresh for today's fixtures and betting-slip settlement."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.src.app.core.config import Settings, get_settings
from backend.src.app.services.betting_slips import sync_betting_slip_pick_outcomes
from backend.src.entity import BettingSlip, BettingSlipPick, NextFixture
from backend.src.service.import_next_fixtures import (
    _normalize_fixtures_response,
    is_match_completed,
    is_singles_match,
    normalized_live_score,
    promote_completed_match,
)
from backend.src.utility.request_api import request_api


def _utc_now_naive(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current
    return current.astimezone(timezone.utc).replace(tzinfo=None)


def _today(settings: Settings, value: datetime | None = None) -> date:
    tz = ZoneInfo(settings.betting_slip_timezone)
    if value is None:
        return datetime.now(tz).date()
    if value.tzinfo is None:
        return value.replace(tzinfo=tz).date()
    return value.astimezone(tz).date()


def pending_slip_event_keys(db: Session, *, target_date: date) -> set[int]:
    return set(
        db.scalars(
            select(BettingSlipPick.event_key)
            .join(BettingSlip, BettingSlip.id == BettingSlipPick.betting_slip_id)
            .where(
                BettingSlip.slip_date == target_date,
                BettingSlipPick.outcome == "pending",
            )
            .distinct()
        ).all()
    )


def daily_fixture_event_keys(db: Session, *, target_date: date) -> set[int]:
    """Return every still-active fixture for the day.

    The provider request is already date-wide, so tracking all persisted matches
    lets the Partite page show live scores without increasing provider calls.
    Pending slip keys are merged as a safety net for legacy rows whose fixture
    date may be incomplete.
    """
    fixture_keys = set(
        db.scalars(
            select(NextFixture.event_key).where(
                NextFixture.event_date == target_date,
                NextFixture.is_completed.is_(False),
            )
        ).all()
    )
    return fixture_keys | pending_slip_event_keys(db, target_date=target_date)


def _update_next_fixture_from_payload(
    db: Session,
    *,
    payload: dict[str, Any],
    now_utc: datetime,
) -> bool:
    event_key = int(payload["event_key"])
    row = db.scalar(select(NextFixture).where(NextFixture.event_key == event_key))
    if row is None:
        return False
    row.event_status = payload.get("event_status", row.event_status)
    row.event_winner = payload.get("event_winner", row.event_winner)
    row.event_live = payload.get("event_live", row.event_live)
    score = normalized_live_score(payload)
    if score is not None:
        row.live_score = score
        row.live_score_updated_at = now_utc
    row.imported_at = now_utc
    return True


def run_betting_slip_live_poll_once(
    db: Session,
    *,
    target_date: date | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh one day in one provider call and persist terminal outcomes."""
    settings = settings or get_settings()
    resolved_date = target_date or _today(settings, now)
    now_utc = _utc_now_naive(now)
    event_keys = daily_fixture_event_keys(db, target_date=resolved_date)
    summary: dict[str, Any] = {
        "date": resolved_date.isoformat(),
        "candidates": len(event_keys),
        "provider_rows": 0,
        "updated": 0,
        "promoted": 0,
        "missing": 0,
        "outcomes": {"checked": 0, "settled": 0, "won": 0, "lost": 0, "void": 0},
    }
    if not event_keys:
        return summary

    raw = request_api(
        method="get_fixtures",
        params={
            "date_start": resolved_date.isoformat(),
            "date_stop": resolved_date.isoformat(),
        },
    )
    payloads = _normalize_fixtures_response(raw, f"slip_live_poll[{resolved_date}]")
    by_key = {
        int(payload["event_key"]): payload
        for payload in payloads
        if payload.get("event_key") is not None and is_singles_match(payload)
    }
    summary["provider_rows"] = len(by_key)

    for event_key in sorted(event_keys):
        payload = by_key.get(event_key)
        if payload is None:
            summary["missing"] += 1
            continue
        if is_match_completed(payload):
            promoted = promote_completed_match(payload, db=db)
            summary["promoted"] += (
                int(promoted.get("fixtures_inserted", 0))
                + int(promoted.get("fixtures_updated", 0))
            )
            continue
        if _update_next_fixture_from_payload(
            db,
            payload=payload,
            now_utc=now_utc,
        ):
            summary["updated"] += 1

    db.commit()
    db.expire_all()
    summary["outcomes"] = sync_betting_slip_pick_outcomes(
        db,
        slip_date=resolved_date,
        now=now_utc,
    )
    return summary
