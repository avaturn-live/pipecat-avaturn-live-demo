"""Entry point for Pipecat Cloud's base image.

Pipecat Cloud's base image accepts the WebSocket, validates the HMAC
session token (when ``websocket_auth = "token"`` is set in
``pcc-deploy.toml``), and then invokes ``bot(args)`` with the canonical
``WebSocketRunnerArguments`` from pipecat-ai.

Deployment:

    pcc auth login
    pcc deploy avaturn-live-demo --dockerfile Dockerfile
    pcc secrets set OPENAI_API_KEY=sk-...

Your session broker then calls
``POST https://api.pipecat.daily.co/v1/public/avaturn-live-demo/start``
with ``{"transport": "websocket"}`` to get a per-session ``wsUrl`` /
``token`` and passes ``{wsUrl}/{token}`` as Avaturn Live's
``conversation_engine.url`` (see ``pipecat_avaturn.pipecat_cloud``).
"""

from __future__ import annotations

from loguru import logger
from pipecat.runner.types import WebSocketRunnerArguments
from pipecat_avaturn import get_settings, run_agent


async def bot(args: WebSocketRunnerArguments) -> None:
    logger.info("Avaturn Live session {} started", args.session_id)
    await run_agent(args.websocket, settings=get_settings())
