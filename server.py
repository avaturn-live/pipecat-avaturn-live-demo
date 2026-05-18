"""Standalone FastAPI app: Avaturn Live session broker + Pipecat conversation engine.

Run with:  uv run uvicorn server:app --host 0.0.0.0 --port 8000

Endpoints
---------
GET  /healthz                       → liveness probe
POST /api/sessions                  → create Avaturn Live session (returns sessionToken)
WS   /avaturn-live/ws               → conversation engine WebSocket (self-host only)
GET  /                              → demo frontend (single-file HTML)

Two deployment modes
--------------------
* **Self-host** (default): the engine is this process. Avaturn Live opens
  ``CONVERSATION_ENGINE_PUBLIC_URL + CONVERSATION_ENGINE_WS_PATH`` and we
  authenticate it with ``CONVERSATION_ENGINE_SHARED_SECRET``.
* **Pipecat Cloud**: set ``PIPECAT_CLOUD_PUBLIC_KEY`` and
  ``PIPECAT_CLOUD_AGENT_NAME``. Per session the broker calls PCC's
  ``/v1/public/{agent}/start`` (transport=websocket), gets a ``wsUrl`` +
  HMAC token, and hands Avaturn Live ``{wsUrl}/{token}``. PCC validates
  the token, so the agent itself stays auth-free.
"""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger
from pipecat_avaturn import (
    AvaturnLiveClient,
    CreateSessionResult,
    PipecatCloudClient,
    Settings,
    get_settings,
    run_agent,
)
from pydantic import BaseModel

logging.getLogger("uvicorn.access").addFilter(lambda record: "/healthz" not in record.getMessage())


@asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: ARG001
    s = get_settings()
    if not s.avaturn_live_api_key.get_secret_value():
        logger.warning("AVATURN_LIVE_API_KEY is empty — POST /api/sessions will fail.")

    if s.uses_pipecat_cloud:
        logger.info(
            "Using Pipecat Cloud agent {!r}; conversation engine is allocated per-session.",
            s.pipecat_cloud_agent_name,
        )
    else:
        if not s.openai_api_key.get_secret_value():
            logger.warning("OPENAI_API_KEY is empty — the WS endpoint will fail.")
        if s.conversation_engine_shared_secret is None:
            logger.warning(
                "CONVERSATION_ENGINE_SHARED_SECRET is not set — anyone who finds "
                "your WS URL can attach to the pipeline. Set a random value "
                "(`openssl rand -hex 32`) before exposing this service."
            )

    yield


app = FastAPI(title="Pipecat × Avaturn Live demo", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateSessionRequest(BaseModel):
    avatar_id: str | None = None


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


async def _resolve_engine_target(s: Settings) -> tuple[str, dict[str, str] | None]:
    """Return ``(ws_url, optional_headers)`` for Avaturn Live's conversation engine."""

    if s.uses_pipecat_cloud:
        assert s.pipecat_cloud_public_key is not None  # narrowed by uses_pipecat_cloud
        assert s.pipecat_cloud_agent_name is not None
        async with PipecatCloudClient(
            s.pipecat_cloud_public_key.get_secret_value(),
            api_url=s.pipecat_cloud_api_url,
        ) as pcc:
            allocated = await pcc.allocate_websocket_session(s.pipecat_cloud_agent_name)
        return allocated.url_with_token, None

    secret = (
        s.conversation_engine_shared_secret.get_secret_value()
        if s.conversation_engine_shared_secret
        else None
    )
    headers = {"Authorization": f"Bearer {secret}"} if secret else None
    return s.conversation_engine_ws_url, headers


@app.post("/api/sessions", response_model=CreateSessionResult)
async def create_session(req: CreateSessionRequest) -> CreateSessionResult:
    s = get_settings()
    api_key = s.avaturn_live_api_key.get_secret_value()
    if not api_key:
        raise HTTPException(503, "AVATURN_LIVE_API_KEY is not configured on the server")

    avatar_id = req.avatar_id or s.avaturn_live_default_avatar_id

    try:
        ws_url, headers = await _resolve_engine_target(s)
        async with AvaturnLiveClient(s.avaturn_live_api_url, api_key) as avaturn_live:
            return await avaturn_live.create_session_with_external_engine(
                avatar_id=avatar_id,
                conversation_engine_ws_url=ws_url,
                user_sample_rate=s.user_audio_sample_rate,
                headers=headers,
            )
    except httpx.HTTPStatusError as exc:
        logger.error(
            "upstream {} failed: {} {}",
            exc.request.url,
            exc.response.status_code,
            exc.response.text,
        )
        raise HTTPException(exc.response.status_code, exc.response.text) from exc


def _check_shared_secret(websocket: WebSocket) -> bool:
    s = get_settings()
    if s.conversation_engine_shared_secret is None:
        return True
    expected = f"Bearer {s.conversation_engine_shared_secret.get_secret_value()}"
    presented = websocket.headers.get("authorization", "")
    return secrets.compare_digest(expected, presented)


@app.websocket("/avaturn-live/ws")
async def avaturn_live_ws(websocket: WebSocket) -> None:
    """Self-host conversation engine endpoint.

    Not used in Pipecat Cloud deployments — there, the engine runs on PCC
    and this process is purely a session broker.
    """
    if get_settings().uses_pipecat_cloud:
        await websocket.close(code=1008, reason="engine runs on pipecat cloud, not here")
        return

    if not _check_shared_secret(websocket):
        logger.warning("rejecting Avaturn Live WS: shared-secret mismatch")
        await websocket.close(code=1008, reason="unauthorized")
        return

    await websocket.accept()
    await run_agent(websocket, settings=get_settings())


_FRONTEND_DIR = Path(__file__).parent / "frontend"


@app.get("/", response_model=None)
async def index() -> FileResponse | JSONResponse:
    index_path = _FRONTEND_DIR / "index.html"
    if not index_path.exists():
        return JSONResponse({"error": "frontend/index.html missing"}, status_code=404)
    return FileResponse(index_path)


@app.exception_handler(Exception)
async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error: {}", exc)
    return JSONResponse({"error": str(exc)}, status_code=500)
