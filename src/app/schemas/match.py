from datetime import date, time
from typing import Any

from pydantic import BaseModel, ConfigDict


class MatchRead(BaseModel):
    id_fixture: int
    event_key: int
    event_date: date | None = None
    event_time: time | None = None
    event_first_player: str | None = None
    first_player_key: int | None = None
    event_second_player: str | None = None
    second_player_key: int | None = None
    event_final_result: str | None = None
    event_game_result: str | None = None
    event_serve: str | None = None
    event_winner: str | None = None
    event_status: str | None = None
    event_type_type: str | None = None
    tournament_name: str | None = None
    tournament_key: int | None = None
    tournament_round: str | None = None
    tournament_season: str | None = None
    event_live: str | None = None
    event_first_player_logo: str | None = None
    event_second_player_logo: str | None = None
    event_qualification: str | None = None
    pointbypoint: Any | None = None
    scores: Any | None = None
    statistics: Any | None = None
    odds: Any | None = None

    model_config = ConfigDict(from_attributes=True)
