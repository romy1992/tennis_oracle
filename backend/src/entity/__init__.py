"""SQLAlchemy ORM entities for the operational domain (canonical table models).

``app.models`` re-exports many of these for convenience and adds ML-only models.
Prefer importing domain tables from this package in new code.
"""

from backend.src.entity.admin_user import AdminUser
from backend.src.entity.betting_slip import BettingSlip, BettingSlipDay, BettingSlipPick
from backend.src.entity.event import Event
from backend.src.entity.fixture import Fixture
from backend.src.entity.global_update_run import GlobalUpdateRun, GlobalUpdateRunItem
from backend.src.entity.match_prediction import MatchPrediction
from backend.src.entity.next_fixture import NextFixture
from backend.src.entity.pipeline_lock import PipelineLock
from backend.src.entity.player import Player
from backend.src.entity.prematch_odds_snapshot import PrematchOddsSnapshot
from backend.src.entity.published_prediction import PublishedPrediction
from backend.src.entity.rate_limit_bucket import RateLimitBucket
from backend.src.entity.standing import Standing
from backend.src.entity.telegram_bot_event import TelegramBotEvent
from backend.src.entity.tournaments import Tournament

__all__ = [
    "AdminUser",
    "Event",
    "Tournament",
    "Fixture",
    "NextFixture",
    "MatchPrediction",
    "PrematchOddsSnapshot",
    "PublishedPrediction",
    "BettingSlip",
    "BettingSlipDay",
    "BettingSlipPick",
    "GlobalUpdateRun",
    "GlobalUpdateRunItem",
    "PipelineLock",
    "Standing",
    "Player",
    "TelegramBotEvent",
    "RateLimitBucket",
]
