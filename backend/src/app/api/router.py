from fastapi import APIRouter

from backend.src.app.api.routes import (
    auth,
    betting_slips,
    global_update,
    imports,
    live_beta_dashboard,
    predictions,
    prematch_odds_snapshots,
    published_predictions,
    single_match_value,
    telegram,
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
api_router.include_router(published_predictions.router)
api_router.include_router(prematch_odds_snapshots.router)
api_router.include_router(live_beta_dashboard.router)
