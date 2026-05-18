"""Client for Pipecat Cloud's session-start REST endpoint.

PCC's "generic WebSocket" deployments are session-scoped: every call
opens a new pod and an HMAC token that is one-time-use, expires in five
minutes, and is verified by the platform *before* the WebSocket reaches
``bot()``. Our session broker calls this once per Avaturn Live session,
then hands Avaturn Live the per-session URL.

The endpoint contract — see
https://docs.pipecat.ai/pipecat-cloud/guides/websocket-authentication:

    POST https://api.pipecat.daily.co/v1/public/{agent}/start
    Authorization: Bearer {public_key}
    { "transport": "websocket" }
        →
    { "token": "...", "wsUrl": "wss://.../ws/generic/agent.org", "sessionId": "..." }

Avaturn Live then opens ``f"{wsUrl}/{token}"`` (URL-path attachment is
the recommended option from the docs).
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel


class AllocatedWebsocketSession(BaseModel):
    ws_url: str
    token: str
    session_id: str

    @property
    def url_with_token(self) -> str:
        return f"{self.ws_url.rstrip('/')}/{self.token}"


class PipecatCloudClient:
    def __init__(
        self,
        public_key: str,
        api_url: str = "https://api.pipecat.daily.co",
        timeout: float = 30.0,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=api_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {public_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "PipecatCloudClient":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.aclose()

    async def allocate_websocket_session(self, agent_name: str) -> AllocatedWebsocketSession:
        response = await self._client.post(
            f"/v1/public/{agent_name}/start",
            json={"transport": "websocket"},
        )
        response.raise_for_status()
        body = response.json()
        return AllocatedWebsocketSession(
            ws_url=body["wsUrl"],
            token=body["token"],
            session_id=body["sessionId"],
        )
