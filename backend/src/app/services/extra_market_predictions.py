"""Generate and publish predictions for the "extra" markets (first-set-winner,
over/under games) into the generic ``PublishedPrediction`` ledger.

Moved here (from ``backend/src/jobs/generate_extra_market_predictions.py``) so
the global-update orchestrator (``app/services/global_update.py``) can call it
as a regular pipeline phase, same as match-winner predictions/betting slips.
The job module is now a thin CLI wrapper around ``run_extra_market_predictions_generation``
(kept for standalone/manual use and backward-compat import paths).

Idempotent: a publication (event_key, selection, model_version, model_name,
publication_source) that already exists with ``content_version=1`` is skipped
(no duplicate, no unique-constraint error). Fixtures whose match has already
started are also skipped (the ledger refuses to publish after match start,
see ``publish_prediction``).

Adding a future extra market: add a ``(predict_fn, market_key)`` pair to
``EXTRA_MARKET_PREDICTORS`` below — no other orchestration change needed, this
same function (and the global-update phase that calls it) picks it up
automatically.
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.src.app.db.session import SessionLocal
from backend.src.app.ml.prediction.extra_markets_predictor import (
    predict_first_set_winner,
    predict_over_under_games,
)
from backend.src.app.ml.prediction.predictor import PreMatchFeatureBuilder
from backend.src.app.schemas.published_prediction import PublicationSource, PublishedPredictionCreate
from backend.src.app.services.predictions import list_next_fixtures
from backend.src.app.services.published_predictions import PublishedPredictionError, publish_prediction
from backend.src.app.services.single_match_value import (
    DEFAULT_MIN_EDGE_PERCENT,
    calculate_void_odds,
    classify_single_bet_value,
)
from backend.src.entity.published_prediction import PublishedPrediction

logger = logging.getLogger(__name__)

DEFAULT_PUBLICATION_SOURCE: PublicationSource = "system"
PUBLICATION_SOURCE_CHOICES = ("admin_api", "telegram", "global_update", "system", "manual")

# Registry of extra-market predictors: add a new market here (predict_fn,
# market_key) once trained + wired into extra_markets_predictor.py, and it
# is automatically generated/published by this function and by the
# global-update orchestrator phase that calls it.
EXTRA_MARKET_PREDICTORS: tuple[tuple[Any, str], ...] = (
    (predict_first_set_winner, "first_set_winner"),
    (predict_over_under_games, "over_under_games"),
)


def _already_published(
    db: Session,
    *,
    event_key: int,
    selection: str,
    model_version: str,
    model_name: str,
    publication_source: str,
) -> bool:
    existing = db.scalar(
        select(PublishedPrediction.id).where(
            PublishedPrediction.event_key == event_key,
            PublishedPrediction.selection == selection,
            PublishedPrediction.model_version == model_version,
            PublishedPrediction.model_name == model_name,
            PublishedPrediction.publication_source == publication_source,
            PublishedPrediction.content_version == 1,
        )
    )
    return existing is not None


def _publish_result(
    db: Session,
    fixture: Any,
    result: dict[str, Any],
    *,
    publication_source: PublicationSource,
    dry_run: bool,
) -> str:
    """Return one of: 'published', 'skipped_no_probability',
    'skipped_invalid_probability', 'skipped_already_published',
    'skipped_match_started', 'error'."""
    raw_probability = result.get("probability")
    if raw_probability is None:
        return "skipped_no_probability"
    try:
        probability = float(raw_probability)
    except (TypeError, ValueError):
        return "skipped_invalid_probability"
    if not math.isfinite(probability) or not 0.0 < probability < 1.0:
        # Random-forest predict_proba can legitimately reach an exact 0/1
        # boundary. The publication schema requires an open interval (and a
        # fair odd strictly above 1), so skip this unusable row without
        # aborting generation for every remaining fixture/market.
        return "skipped_invalid_probability"

    if _already_published(
        db,
        event_key=result["event_key"],
        selection=result["selection"],
        model_version=result["model_version"],
        model_name=result["model_name"],
        publication_source=publication_source,
    ):
        return "skipped_already_published"

    if dry_run:
        return "published"

    # void_odds (fair/break-even odds, 1/probability) is always computable from
    # the model probability alone. odds/edge require a REAL market quote for
    # this exact selection: set by the extra-market predictors when the
    # dedicated bookmaker market is present (Home/Away 1st Set, O/U games).
    void_odds = calculate_void_odds(probability)
    market_odds = result.get("market_odds")
    odds = float(market_odds) if market_odds is not None else None
    edge = ((odds - void_odds) / void_odds) * 100.0 if odds is not None else None
    market = str(result.get("market") or "match_winner")
    value_decision = None
    if market in {"over_under_games", "first_set_winner"} and odds is not None:
        value_decision = classify_single_bet_value(
            market_odds=odds,
            void_odds=void_odds,
            min_edge_percent=DEFAULT_MIN_EDGE_PERCENT,
        )
    official_play = bool(
        publication_source == DEFAULT_PUBLICATION_SOURCE
        and odds is not None
        and value_decision == "PLAY"
    )

    try:
        publish_prediction(
            db,
            PublishedPredictionCreate(
                event_key=result["event_key"],
                market=market,
                value_decision=value_decision,
                official_play=official_play,
                selection=result["selection"],
                model_version=result["model_version"],
                model_name=result["model_name"],
                probability=probability,
                odds=round(odds, 4) if odds is not None else None,
                void_odds=round(void_odds, 4),
                edge=round(edge, 2) if edge is not None else None,
                publication_source=publication_source,
                player_1_name=fixture.event_first_player,
                player_2_name=fixture.event_second_player,
                tournament_name=fixture.tournament_name,
                event_date=fixture.event_date,
                event_time=fixture.event_time,
            ),
        )
        return "published"
    except PublishedPredictionError as exc:
        if exc.status_code == 409:
            return "skipped_match_started"
        logger.warning(
            "Pubblicazione fallita per event_key=%s selection=%s: %s",
            result["event_key"], result["selection"], exc,
        )
        return "error"


def run_extra_market_predictions_generation(
    *,
    days_forward: int = 10,
    publication_source: PublicationSource = DEFAULT_PUBLICATION_SOURCE,
    dry_run: bool = False,
    db: Session | None = None,
) -> dict[str, Any]:
    """Generate + publish predictions for all registered extra markets.

    Opens its own ``SessionLocal`` when ``db`` is not provided (standalone
    CLI use); accepts an existing session (e.g. from the global-update
    orchestrator) to reuse the same transaction/connection.
    """
    today = date.today()
    counts: dict[str, int] = {}
    per_market: dict[str, dict[str, int]] = {key: {} for _, key in EXTRA_MARKET_PREDICTORS}

    def _run(session: Session) -> None:
        fixtures = list_next_fixtures(
            db=session,
            from_date=today,
            to_date=today + timedelta(days=days_forward),
            limit=500,
            odds_required=True,
        )
        feature_builder = PreMatchFeatureBuilder.from_db(session, model_version="v3")

        for fixture in fixtures:
            for predict_fn, market_key in EXTRA_MARKET_PREDICTORS:
                result = predict_fn(fixture, feature_builder=feature_builder)
                status = _publish_result(
                    session, fixture, result, publication_source=publication_source, dry_run=dry_run,
                )
                per_market[market_key][status] = per_market[market_key].get(status, 0) + 1
                counts[status] = counts.get(status, 0) + 1

        counts["_fixtures_considered"] = len(fixtures)

    if db is not None:
        _run(db)
    else:
        with SessionLocal() as session:
            _run(session)

    fixtures_considered = counts.pop("_fixtures_considered", 0)
    summary = {
        "fixtures_considered": fixtures_considered,
        "dry_run": dry_run,
        "publication_source": publication_source,
        "totals": counts,
        "by_market": per_market,
    }
    logger.info("Extra market predictions generation summary: %s", summary)
    return summary


def format_summary(summary: dict[str, Any]) -> str:
    lines = [
        f"Fixture considerate: {summary['fixtures_considered']} (dry_run={summary['dry_run']})",
        f"Totali: {summary['totals']}",
    ]
    for market, stats in summary["by_market"].items():
        lines.append(f"  {market}: {stats}")
    return "\n".join(lines)



