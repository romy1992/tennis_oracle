from typing import Any

from pydantic import BaseModel, ConfigDict


class PlayerRead(BaseModel):
    id_player: int
    player_key: int
    player_name: str | None = None
    player_full_name: str | None = None
    player_country: str | None = None
    player_bday: str | None = None
    player_logo: str | None = None
    stats: Any | None = None
    tournaments: Any | None = None

    model_config = ConfigDict(from_attributes=True)
