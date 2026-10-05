"""HTTP client for the Kairos optimization API."""

from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout


class KairosApiError(Exception):
    """An API request failed or returned an invalid response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class KairosApi:
    """Small client for Kairos health and optimization endpoints."""

    def __init__(self, session: ClientSession, api_url: str, timeout: int) -> None:
        self._session = session
        self._api_url = api_url.rstrip("/")
        self._timeout = ClientTimeout(total=timeout)

    async def async_optimize(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send an optimization request and return its response."""
        try:
            async with self._session.post(
                f"{self._api_url}/optimize", json=payload, timeout=self._timeout
            ) as response:
                body = await response.json(content_type=None)
                if response.status >= 400:
                    detail = body.get("detail", body) if isinstance(body, dict) else body
                    raise KairosApiError(
                        f"Kairos returned HTTP {response.status}: {detail}",
                        status_code=response.status,
                    )
        except (ClientError, TimeoutError, ValueError) as err:
            raise KairosApiError(f"Could not communicate with Kairos: {err}") from err

        if not isinstance(body, dict) or not isinstance(body.get("assets"), dict):
            raise KairosApiError("Kairos returned a response without an asset schedule.")
        return body
