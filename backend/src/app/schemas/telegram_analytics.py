from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class TelegramBotEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    telegram_user_id: int | None = None
    chat_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    event_type: str
    action: str
    raw_text: str | None = None
    success: bool | None = None
    error_message: str | None = None


class TelegramBotEventsResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[TelegramBotEventRead]


class TelegramBotActionCount(BaseModel):
    action: str
    count: int


class TelegramBotDayCount(BaseModel):
    day: date
    count: int


class TelegramBotStatsResponse(BaseModel):
    total_events: int
    unique_users: int
    events_today: int
    top_action: str | None = None
    by_action: list[TelegramBotActionCount]
    by_day: list[TelegramBotDayCount]
