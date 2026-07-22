"""Pydantic schemas for the append-only pre-match odds snapshot ledger."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SnapshotType = Literal["opening", "observed", "publication", "closing"]
SnapshotTypeOrAuto = Literal["opening", "observed", "publication", "closing", "auto"]

OddsSnapshotSource = Literal[
    "api_tennis",
    "import",
    "admin_api",
    "telegram",
    "global_update",
    "publication",
    "system",
    "manual",
]


class PrematchOddsSnapshotCreate(BaseModel):
    """Single detection to append (skipped if duplicate fingerprint)."""

    event_key: int
    selection: str = Field(min_length=1, max_length=255)
    bookmaker: str = Field(min_length=1, max_length=128)
    odds: float = Field(gt=1.0)
    implied_probability: float | None = Field(default=None, gt=0.0, lt=1.0)
    margin: float | None = None
    source: OddsSnapshotSource = "admin_api"
    snapshot_type: SnapshotType = "observed"
    captured_at: datetime | None = None
    market_side: str | None = Field(default=None, max_length=32)
    player_1_name: str | None = None
    player_2_name: str | None = None


class PrematchOddsSnapshotFromPayload(BaseModel):
    """Ingest Home/Away bookmaker matrix for a fixture (append-only, deduped)."""

    event_key: int
    odds: dict[str, Any]
    source: OddsSnapshotSource = "admin_api"
    snapshot_type: SnapshotTypeOrAuto = "auto"
    captured_at: datetime | None = None
    player_1_name: str | None = None
    player_2_name: str | None = None
    event_live: Any = None


class PrematchOddsSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_key: int
    selection: str
    bookmaker: str
    odds: float
    implied_probability: float
    margin: float
    captured_at: datetime
    source: str
    snapshot_type: str
    detection_hash: str
    market_side: str | None = None
    player_1_name: str | None = None
    player_2_name: str | None = None


class PrematchOddsSnapshotListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PrematchOddsSnapshotRead]


class PrematchOddsSnapshotIngestResponse(BaseModel):
    event_key: int
    inserted: int
    skipped_duplicates: int
    items: list[PrematchOddsSnapshotRead]
