"""Aggiornamento PUNTUALE di una partita (bottone sulla card, solo super admin lato BFF).

Per UN evento (`event_key`):
1. riscarica da api-tennis la partita (`get_fixtures` con `match_key`): calendario/quote se e' ancora da giocare,
   risultato se e' conclusa (la partita passa tra le giocate e le predizioni salvate vengono risolte);
2. se non e' ancora conclusa, rigenera la predizione del vincitore per ogni combinazione modello attiva e
   le predizioni dei mercati extra (1° set, O/U games) - queste ultime restano congelate se gia' pubblicate
   (stesse regole dell'"Aggiorna tutto": una predizione pubblicata non viene riscritta).
Il regolamento delle tip pubblicate si calcola dai risultati: nessun passo di settlement a parte.
Non parte se un aggiornamento globale e' in corso (stesse tabelle)."""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.src.app.ml.prediction.predictor import PreMatchFeatureBuilder, predict_upcoming_fixtures
from backend.src.app.services.extra_market_predictions import (
    DEFAULT_PUBLICATION_SOURCE,
    EXTRA_MARKET_PREDICTORS,
    _publish_result,
)
from backend.src.entity import NextFixture
from backend.src.service.import_next_fixtures import (
    _ingest_upcoming_payloads,
    _normalize_fixtures_response,
    is_match_completed,
)
from backend.src.utility.request_api import request_api

logger = logging.getLogger(__name__)


class SingleEventRefreshBusy(RuntimeError):
    """Un aggiornamento globale e' in corso: riprovare dopo."""


def refresh_single_event(db: Session, event_key: int) -> dict[str, Any]:
    from backend.src.app.services.global_update import get_active_run, list_enabled_combinations

    if get_active_run(db) is not None:
        raise SingleEventRefreshBusy("Aggiornamento globale in corso")

    raw = request_api(method="get_fixtures", params={"match_key": int(event_key)})
    payloads = [
        p for p in _normalize_fixtures_response(raw, context=f"match_key={event_key}")
        if str(p.get("event_key")) == str(int(event_key))
    ]
    if not payloads:
        return {"found": False, "event_key": int(event_key)}
    payload = payloads[0]

    summary: dict[str, int] = defaultdict(int)
    _ingest_upcoming_payloads([payload], summary, import_odds=True)
    completed = is_match_completed(payload)
    result: dict[str, Any] = {
        "found": True,
        "event_key": int(event_key),
        "completed": completed,
        "import": dict(summary),
        "predictions": {},
        "extra_markets": {},
        "errors": {},
    }
    if summary.get("skipped_non_singles"):
        result["note"] = "partita non singolare: ignorata"
        return result
    if completed:
        return result

    db.expire_all()
    fixture = db.scalar(select(NextFixture).where(NextFixture.event_key == int(event_key)))
    if fixture is None:
        result["note"] = "partita non presente nel calendario"
        return result

    for combo in list_enabled_combinations():
        label = f"{combo.model_version}/{combo.model_name}"
        try:
            generated = predict_upcoming_fixtures(
                db=db,
                fixtures=[fixture],
                model_version=combo.model_version,
                model_name=combo.model_name,
            )
            result["predictions"][label] = len(generated)
        except Exception as exc:  # noqa: BLE001 - una combinazione non blocca le altre
            logger.exception("single-event refresh: predizione %s fallita", label)
            result["errors"][label] = str(exc)

    try:
        feature_builder = PreMatchFeatureBuilder.from_db(db, model_version="v3")
        for predict_fn, market_key in EXTRA_MARKET_PREDICTORS:
            extra = predict_fn(fixture, feature_builder=feature_builder)
            result["extra_markets"][market_key] = _publish_result(
                db, fixture, extra, publication_source=DEFAULT_PUBLICATION_SOURCE, dry_run=False
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("single-event refresh: mercati extra falliti")
        result["errors"]["extra_markets"] = str(exc)
    return result
