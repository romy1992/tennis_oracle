from __future__ import annotations

from datetime import date
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
            return response.json()
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
        slip_count: int = 5,
        picks_per_slip: int = 5,
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
