from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict


class NextFixtureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_key: int
    event_date: date | None
    event_time: time | None
    event_first_player: str | None
    first_player_key: int | None
    event_second_player: str | None
    second_player_key: int | None
    tournament_name: str | None
    tournament_key: int | None
    tournament_round: str | None
    surface: str | None
    event_status: str | None
    event_type_type: str | None
    odds: dict | list | None
    imported_at: datetime | None
    week_start: date | None
    week_end: date | None
    source: str | None
    is_completed: bool | None
    moved_to_fixture_at: datetime | None
    match_lifecycle_status: str | None = None
    match_lifecycle_label: str | None = None


class MatchPredictionRead(BaseModel):
    event_key: int
    model_version: str
    model_name: str | None = None
    predicted_at: datetime | None = None
    prob_player_1_win: float | None
    predicted_winner: str | None
    actual_winner: str | None = None
    is_correct: bool | None = None
    predicted_winner_odds: float | None = None
    odds_bookmaker_count: int | None = None
    confidence: float | None
    features_available: bool = True
    warnings: list[str] = []


class NextFixtureWithPrediction(NextFixtureRead):
    prediction: MatchPredictionRead | None = None
    prediction_warning: str | None = None


class FixturesWithPredictionsPage(BaseModel):
    items: list[NextFixtureWithPrediction]
    total: int
    offset: int
    limit: int


class DailyPredictionStatsDay(BaseModel):
    day_offset: int
    date: date
    predictions_total: int
    predictions_resolved: int
    predictions_correct: int
    predictions_lost: int
    accuracy_pct: float | None
    pending: int
    predictions_with_odds: int = 0
    avg_predicted_winner_odds: float | None = None
    avg_winning_odds: float | None = None
    theoretical_profit_units: float = 0.0
    theoretical_roi_pct: float | None = None


class DailyPredictionStatsResponse(BaseModel):
    model_version: str
    days: list[DailyPredictionStatsDay]


class PredictionModelBreakdown(BaseModel):
    model_version: str
    model_name: str | None = None
    predictions_total: int
    predictions_resolved: int
    predictions_correct: int
    predictions_lost: int
    accuracy_pct: float | None
    pending: int
    predictions_with_odds: int = 0
    avg_predicted_winner_odds: float | None = None
    avg_winning_odds: float | None = None
    theoretical_profit_units: float = 0.0
    theoretical_roi_pct: float | None = None


class PredictionSummaryResponse(BaseModel):
    model_version: str
    predictions_total: int
    predictions_resolved: int
    predictions_correct: int
    predictions_lost: int
    accuracy_pct: float | None
    pending: int
    predictions_with_odds: int = 0
    avg_predicted_winner_odds: float | None = None
    avg_winning_odds: float | None = None
    theoretical_profit_units: float = 0.0
    theoretical_roi_pct: float | None = None
    breakdown: list[PredictionModelBreakdown] = []
