"""Temporary debug ingest for agent session 839b99 — remove after verification."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel


router = APIRouter(prefix="/debug", tags=["debug"])
_LOG_PATH = Path(r"c:\Users\trott\git\tennis_oracle\debug-839b99.log")


class AgentLogPayload(BaseModel):
    sessionId: str | None = None
    runId: str | None = None
    hypothesisId: str | None = None
    location: str | None = None
    message: str | None = None
    data: dict | None = None
    timestamp: int | None = None


@router.post("/agent-log")
def write_agent_log(payload: AgentLogPayload) -> dict[str, bool]:
    row = payload.model_dump()
    if row.get("timestamp") is None:
        row["timestamp"] = int(datetime.now().timestamp() * 1000)
    _LOG_PATH.open("a", encoding="utf-8").write(json.dumps(row, default=str) + "\n")
    return {"ok": True}
