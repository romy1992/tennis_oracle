from fastapi import APIRouter

from backend.src.app.api.routes import (
    auth,
    betting_slips,
    calibration,
    global_update,
    imports,
    live_beta_dashboard,
    ops,
    predictions,
    prematch_odds_snapshots,
    probability_bands,
    public_model_registry,
    published_predictions,
    segment_roi,
    single_match_value,
    telegram,
    telegram_feedback,
    telegram_users,
    walk_forward,
    weekly_beta_reports,
)


api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(imports.router)
api_router.include_router(predictions.router)
api_router.include_router(predictions.predictions_stats_router)
api_router.include_router(betting_slips.router)
api_router.include_router(single_match_value.router)
api_router.include_router(global_update.router)
api_router.include_router(global_update.results_router)
api_router.include_router(telegram.router)
api_router.include_router(telegram_users.router)
api_router.include_router(telegram_feedback.router)
api_router.include_router(published_predictions.router)
api_router.include_router(prematch_odds_snapshots.router)
api_router.include_router(live_beta_dashboard.router)
api_router.include_router(weekly_beta_reports.router)
api_router.include_router(walk_forward.router)
api_router.include_router(calibration.router)
api_router.include_router(public_model_registry.router)
api_router.include_router(probability_bands.router)
api_router.include_router(segment_roi.router)
api_router.include_router(ops.router)
