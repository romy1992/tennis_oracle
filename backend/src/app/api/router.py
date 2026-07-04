from fastapi import APIRouter

from backend.src.app.api.routes import betting_slips, imports, predictions


api_router = APIRouter()
api_router.include_router(imports.router)
api_router.include_router(predictions.router)
api_router.include_router(predictions.predictions_stats_router)
api_router.include_router(betting_slips.router)
