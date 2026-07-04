from datetime import date, datetime

from pydantic import BaseModel, Field


class ImportStatusResponse(BaseModel):
    next_fixtures_last_imported_at: datetime | None = None
    next_fixtures_imported_today: bool = False
    next_fixtures_max_date: date | None = None
    next_fixtures_window_days: int = 10
    next_fixtures_window_until: date | None = None
    fixtures_last_match_date: date | None = None
    fixtures_last_imported_at: datetime | None = None


class RefreshMatchesResponse(BaseModel):
    next_fixtures_imported: bool
    next_fixtures_summary: dict | None = None
    predictions_summary: dict
    import_status: ImportStatusResponse


class ImportFixturesResponse(BaseModel):
    days_back: int
    import_status: ImportStatusResponse


class ImportFixturesRequest(BaseModel):
    days_back: int = Field(default=1, ge=0, le=30)
