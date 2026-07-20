from __future__ import annotations

from datetime import date
import logging
from typing import Any

import httpx

from backend.src.utility.sensitive_data import sanitize_payload, sanitize_text, sanitize_url

logger = logging.getLogger(__name__)


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
        url = f"{self.base_url}{path}"
        logger.debug(
            "Telegram backend request path=%s params=%s",
            path,
            sanitize_payload(clean_params),
        )
        try:
            response = await self._client.get(url, params=clean_params)
            response.raise_for_status()
            payload = response.json()
            return payload
        except httpx.TimeoutException as exc:
            logger.error(
                "Telegram backend timeout path=%s url=%s",
                path,
                sanitize_url(url),
            )
            raise BackendApiError(
                "Backend non raggiungibile (timeout). Verifica che FastAPI sia avviato."
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = _extract_error_detail(exc.response)
            logger.error(
                "Telegram backend HTTP error path=%s status=%s detail=%s",
                path,
                exc.response.status_code,
                detail,
            )
            raise BackendApiError(
                f"Il backend ha risposto con errore {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error(
                "Telegram backend network error path=%s url=%s",
                path,
                sanitize_url(url),
            )
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
        return sanitize_text(response.text, max_length=200) or "errore non specificato"
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return sanitize_text(str(detail or "errore non specificato"), max_length=200)
