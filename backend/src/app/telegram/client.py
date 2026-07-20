from __future__ import annotations

from datetime import date
import json
import time
from pathlib import Path
from typing import Any

import httpx


class BackendApiError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class BackendApiClient:
    def __init__(self, base_url: str, *, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        clean_params = {key: value for key, value in params.items() if value is not None}
        try:
            response = await self._client.get(f"{self.base_url}{path}", params=clean_params)
            response.raise_for_status()
            payload = response.json()
            # region agent log
            _agent_log(
                "H2,H3,H4",
                "backend/src/app/telegram/client.py:_get",
                "telegram backend response summary",
                {
                    "path": path,
                    "params": clean_params,
                    "summary": _payload_summary(payload),
                },
            )
            # endregion
            return payload
        except httpx.HTTPStatusError as exc:
            detail = _extract_error_detail(exc.response)
            raise BackendApiError(
                f"Il backend ha risposto con errore {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.RequestError as exc:
            raise BackendApiError(
                "Backend non disponibile. Verifica che FastAPI sia avviato e raggiungibile."
            ) from exc

    async def predictions(
        self,
        *,
        model_version: str,
        model_name: str | None = None,
        from_date: date,
        to_date: date,
        limit: int = 200,
        offset: int = 0,
        status: str = "upcoming",
        player: str | None = None,
    ) -> list[dict[str, Any]]:
        payload = await self._get(
            "/next-fixtures/predictions",
            {
                "model_version": model_version,
                "model_name": model_name,
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "limit": limit,
                "offset": offset,
                "status": status,
                "player": player,
            },
        )
        if isinstance(payload, dict):
            return payload.get("items", [])
        return []

    async def fixtures(
        self,
        *,
        from_date: date,
        to_date: date,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        payload = await self._get(
            "/next-fixtures",
            {
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "limit": limit,
            },
        )
        return payload if isinstance(payload, list) else []

    async def daily_betting_slips(
        self,
        *,
        slip_date: date,
        model_version: str,
        model_name: str | None,
        stake: float,
        slip_count: int = 9,
        picks_per_slip: int = 5,
        min_edge_percent: float = 2.0,
    ) -> dict[str, Any]:
        payload = await self._get(
            "/betting-slips/daily",
            {
                "date": slip_date.isoformat(),
                "model_version": model_version,
                "model_name": model_name,
                "stake": stake,
                "slip_count": slip_count,
                "picks_per_slip": picks_per_slip,
                "min_edge_percent": min_edge_percent,
            },
        )
        return payload if isinstance(payload, dict) else {}

    async def models_versions_results(self, *, target_date: date | None = None) -> dict[str, Any]:
        payload = await self._get(
            "/models-versions/results",
            {"date": target_date.isoformat() if target_date else None},
        )
        return payload if isinstance(payload, dict) else {}

    async def model_names_for_version(
        self,
        *,
        model_version: str,
        target_date: date | None = None,
        fallback: list[str] | None = None,
    ) -> list[str]:
        fallback_names = fallback or ["logistic_regression", "random_forest"]
        try:
            payload = await self.models_versions_results(target_date=target_date)
        except BackendApiError:
            return list(fallback_names)

        for entry in payload.get("versions") or []:
            if entry.get("version") != model_version:
                continue
            names = [
                str(model.get("model"))
                for model in (entry.get("models") or [])
                if model.get("model")
            ]
            return names or list(fallback_names)
        return list(fallback_names)

    async def single_match_value(
        self,
        *,
        from_date: date,
        to_date: date,
        model_version: str,
        model_name: str | None,
        min_edge_percent: float = 2.0,
        status: str = "upcoming",
        limit: int = 200,
    ) -> dict[str, Any]:
        payload = await self._get(
            "/single-match-value",
            {
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "model_version": model_version,
                "model_name": model_name,
                "min_edge_percent": min_edge_percent,
                "status": status,
                "limit": limit,
            },
        )
        return payload if isinstance(payload, dict) else {}

    async def prediction_summary(
        self,
        *,
        model_version: str,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        payload = await self._get(
            "/predictions/stats/summary",
            {
                "model_version": model_version,
                "model_name": model_name,
            },
        )
        return payload if isinstance(payload, dict) else {}

    async def betting_slip_stats_by_model(
        self,
        *,
        stake: float,
        all_time: bool = True,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> dict[str, Any]:
        payload = await self._get(
            "/betting-slips/stats/by-model",
            {
                "stake": stake,
                "all_time": all_time,
                "from": from_date.isoformat() if from_date else None,
                "to": to_date.isoformat() if to_date else None,
            },
        )
        return payload if isinstance(payload, dict) else {}


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or "errore non specificato"
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return str(detail or "errore non specificato")


def _payload_summary(payload: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        items = payload["items"]
        return {
            "item_count": len(items),
            "items_with_raw_odds": sum(1 for item in items if item.get("odds") is not None),
            "items_with_prediction": sum(1 for item in items if item.get("prediction")),
            "null_prediction_odds": sum(
                1
                for item in items
                if item.get("prediction") and item["prediction"].get("predicted_winner_odds") is None
            ),
            "model_versions": sorted(
                str(value)
                for value in {
                    item["prediction"].get("model_version")
                    for item in items
                    if item.get("prediction")
                }
                if value is not None
            ),
            "model_names": sorted(
                str(value)
                for value in {
                    item["prediction"].get("model_name")
                    for item in items
                    if item.get("prediction")
                }
                if value is not None
            ),
            "examples_null_odds": [
                {
                    "event_key": item.get("event_key"),
                    "event_date": item.get("event_date"),
                    "prediction_model_version": item.get("prediction", {}).get("model_version"),
                    "prediction_model_name": item.get("prediction", {}).get("model_name"),
                    "predicted_winner": item.get("prediction", {}).get("predicted_winner"),
                    "has_raw_odds": item.get("odds") is not None,
                }
                for item in items
                if item.get("prediction") and item["prediction"].get("predicted_winner_odds") is None
            ][:5],
        }
    if isinstance(payload, dict) and isinstance(payload.get("slips"), list):
        slips = payload["slips"]
        picks = [pick for slip in slips for pick in (slip.get("picks") or [])]
        return {
            "model_version": payload.get("model_version"),
            "model_name": payload.get("model_name"),
            "slip_count": len(slips),
            "pick_count": len(picks),
            "null_pick_odds": sum(1 for pick in picks if pick.get("odds") is None),
            "candidate_pool_size": payload.get("candidate_pool_size"),
            "warnings": payload.get("warnings"),
            "examples_null_pick_odds": [
                {
                    "event_key": pick.get("event_key"),
                    "player_1": pick.get("player_1"),
                    "player_2": pick.get("player_2"),
                    "predicted_winner": pick.get("predicted_winner"),
                }
                for pick in picks
                if pick.get("odds") is None
            ][:5],
        }
    return {"payload_type": type(payload).__name__}


def _agent_log(hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    try:
        with (Path(__file__).resolve().parents[4] / "debug-1f0f81.log").open("a", encoding="utf-8") as log_file:
            log_file.write(
                json.dumps(
                    {
                        "sessionId": "1f0f81",
                        "runId": "telegram-odds-nd-initial",
                        "hypothesisId": hypothesis_id,
                        "location": location,
                        "message": message,
                        "data": data,
                        "timestamp": int(time.time() * 1000),
                    },
                    default=str,
                )
                + "\n"
            )
    except Exception:
        pass
