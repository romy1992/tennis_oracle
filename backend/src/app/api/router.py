from fastapi import APIRouter

from backend.src.app.api.routes import matches, players, tournaments


api_router = APIRouter()
api_router.include_router(matches.router)
api_router.include_router(players.router)
api_router.include_router(tournaments.router)
