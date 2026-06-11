from pydantic import BaseModel, ConfigDict


class TournamentRead(BaseModel):
    id_tournament: int
    tournament_key: int | None = None
    tournament_name: str | None = None
    event_type_key: int | None = None
    event_type_type: str | None = None
    tournament_sourface: str | None = None

    model_config = ConfigDict(from_attributes=True)
