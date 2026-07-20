from fastapi import APIRouter

from backend.src.app.api.routes import (
    auth,
    betting_slips,
    global_update,
    imports,
    predictions,
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
