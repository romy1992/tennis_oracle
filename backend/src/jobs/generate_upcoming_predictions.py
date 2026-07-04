"""Generate and persist predictions for the next fixture window.

Upsert policy: one row is maintained for each
``event_key + model_version + model_name``. Future/unresolved rows are refreshed
when the job is rerun; rows with an actual winner are left unchanged so saved
prediction history remains evaluable.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from backend.src.app.db.session import SessionLocal
from backend.src.app.ml.model_selection import select_best_model
from backend.src.app.ml.model_versioning import ModelVersion
from backend.src.app.ml.prediction.predictor import predict_upcoming_fixtures
from backend.src.app.services.predictions import list_next_fixtures

logger = logging.getLogger(__name__)


def run_upcoming_prediction_generation(
    *,
    days_forward: int = 10,
    model_version: ModelVersion = "v2",
    model_name: str | None = None,
) -> dict[str, object]:
    selected = None
    if model_name is None:
        selected = select_best_model(model_version)
        model_name = selected.model_name

    today = date.today()
    with SessionLocal() as db:
        fixtures = list_next_fixtures(
            db=db,
            from_date=today,
            to_date=today + timedelta(days=days_forward),
            limit=500,
        )
        predictions = predict_upcoming_fixtures(
            db=db,
            fixtures=fixtures,
            model_version=model_version,
            model_name=model_name,
            persist=True,
        )

    generated = sum(1 for prediction in predictions if prediction["prob_player_1_win"] is not None)
    summary = {
        "fixtures_considered": len(fixtures),
        "predictions_generated": generated,
        "model_version": model_version,
        "model_name": model_name,
        "selection_metric": selected.metric_name if selected else None,
        "selection_metric_value": selected.metric_value if selected else None,
    }
    logger.info("Upcoming prediction generation summary: %s", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate persisted predictions for upcoming fixtures."
    )
    parser.add_argument("--days-forward", type=int, default=10)
    parser.add_argument("--model-version", choices=["v1", "v2"], default="v2")
    parser.add_argument("--model-name", default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    run_upcoming_prediction_generation(
        days_forward=args.days_forward,
        model_version=args.model_version,
        model_name=args.model_name,
    )
