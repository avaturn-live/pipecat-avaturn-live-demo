"""Tiny client that creates Avaturn Live sessions on behalf of the frontend.

Avaturn Live's session-create call needs the project API key, so it must
run server-side. The frontend hits this broker, the broker hits Avaturn
Live, and the resulting session token is what the AvaturnHead Web SDK
uses.

This module deliberately stays standalone — drop it into any FastAPI /
Express / Rails backend and adapt the imports.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel


class CreateSessionResult(BaseModel):
    session_id: str
    token: str
    # The Avaturn Live API host the session was created against. The Web SDK
    # defaults to the production host; if your broker is wired to staging
    # (or any other base URL), the SDK must be told explicitly via
    # AvaturnHead({ apiHost }) — otherwise its session-lookup calls hit
    # prod and 404. Echoed back from our own base_url, not from Avaturn's
    # response (which doesn't include it).
    api_host: str


class AvaturnLiveClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "AvaturnLiveClient":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.aclose()

    async def create_session_with_external_engine(
        self,
        *,
        avatar_id: str,
        conversation_engine_ws_url: str,
        user_sample_rate: int = 24_000,
        model: str = "delta",
        headers: dict[str, str] | None = None,
    ) -> CreateSessionResult:
        """Create a session whose conversation engine is our Pipecat WebSocket.

        Avaturn Live's ``external`` conversation engine connects to the
        supplied URL and exchanges binary audio plus JSON segment events
        with whatever lives at the other end — in our case, this demo's
        Pipecat agent. ``headers``, when provided, are forwarded by
        Avaturn Live on the upgrade request and let the engine
        authenticate the caller.
        """

        engine: dict[str, Any] = {
            "type": "external",
            "url": conversation_engine_ws_url,
            "audio": {"user": {"sample_rate": user_sample_rate}},
        }
        if headers:
            engine["headers"] = headers

        payload: dict[str, Any] = {
            "avatar_id": avatar_id,
            "model": model,
            "conversation_engine": engine,
        }

        response = await self._client.post("/api/v1/sessions", json=payload)
        response.raise_for_status()
        body = response.json()
        return CreateSessionResult(
            session_id=body["session_id"],
            token=body["token"],
            api_host=self._base_url,
        )

    async def terminate_session(self, session_id: str) -> None:
        response = await self._client.delete(f"/api/v1/sessions/{session_id}")
        response.raise_for_status()
