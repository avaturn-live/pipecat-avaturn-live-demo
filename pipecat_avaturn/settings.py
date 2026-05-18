"""Environment-driven configuration for the demo.

One settings object, one source of truth. The broker (``server.py``) and the
agent (``agent.py``) both consume the same ``Settings`` instance, so a value
like ``user_audio_sample_rate`` lives in exactly one place and is threaded
through both sides of the WebSocket.

Values not surfaced here are deliberate constants — Avaturn Live requires
mono audio and 24 kHz avatar output, so making them configurable would only
invite mismatched-config bugs.

Naming: every field tied to the Avaturn Live product is prefixed
``avaturn_live_`` (env: ``AVATURN_LIVE_*``). The plain "Avaturn" name refers
to a separate Avaturn product; the two are not interchangeable.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ----- Avaturn Live (used by the session broker) ------------------
    avaturn_live_api_url: str = Field(
        default="https://api.avaturn.live",
        description="Base URL of the Avaturn Live REST API.",
    )
    avaturn_live_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="Avaturn Live project API key. Required for the session broker.",
    )
    avaturn_live_default_avatar_id: str = Field(
        default="jane_20240829_white_realtime",
        description="Avatar id used when the frontend doesn't specify one.",
    )

    # ----- Conversation engine target ---------------------------------
    # Two modes:
    #
    # 1. Self-host (default): the engine lives in this same process at
    #    ``CONVERSATION_ENGINE_PUBLIC_URL + CONVERSATION_ENGINE_WS_PATH``.
    #    Avaturn Live opens that URL directly; the engine authenticates the
    #    caller against ``CONVERSATION_ENGINE_SHARED_SECRET``.
    #
    # 2. Pipecat Cloud: the engine runs as a PCC agent. When
    #    ``PIPECAT_CLOUD_PUBLIC_KEY`` and ``PIPECAT_CLOUD_AGENT_NAME`` are
    #    set, the broker calls PCC's ``/start`` per session to obtain a
    #    per-session ``wsUrl`` + HMAC ``token``, and points Avaturn Live at
    #    ``{wsUrl}/{token}``. PCC validates the token, so no shared secret
    #    is needed in that path.
    conversation_engine_public_url: str = Field(
        default="ws://localhost:8000",
        description="(self-host) Origin Avaturn Live opens the WS against.",
    )
    conversation_engine_ws_path: str = Field(default="/avaturn-live/ws")
    conversation_engine_shared_secret: SecretStr | None = Field(
        default=None,
        description=(
            "(self-host) Bearer token Avaturn Live forwards on the WS upgrade. "
            "Required for any internet-facing self-host deployment; without it "
            "anyone who finds the WS URL can attach to the pipeline."
        ),
    )

    pipecat_cloud_public_key: SecretStr | None = Field(
        default=None,
        description="(PCC) Project public key, used to call POST /v1/public/{agent}/start.",
    )
    pipecat_cloud_agent_name: str | None = Field(
        default=None,
        description="(PCC) The PCC agent name to allocate sessions on, e.g. 'avaturn-live-demo'.",
    )
    pipecat_cloud_api_url: str = Field(default="https://api.pipecat.daily.co")

    # ----- Audio -------------------------------------------------------
    # Mic-side sample rate; Avaturn Live supports 16 kHz or 24 kHz. Avatar
    # output is always 24 kHz mono (a constant in serializer.py).
    user_audio_sample_rate: int = Field(default=24000)

    # ----- OpenAI Realtime (the default pipeline) ---------------------
    openai_api_key: SecretStr = Field(default=SecretStr(""))
    openai_realtime_model: str = Field(default="gpt-realtime-1.5")
    openai_realtime_voice: str = Field(default="alloy")
    openai_realtime_transcribe_model: str = Field(default="gpt-4o-transcribe")
    system_prompt: str = Field(
        default=(
            "You are a friendly AI avatar in a real-time video chat. Keep responses "
            "concise — one or two short sentences at a time — and let the user steer "
            "the conversation."
        )
    )

    # ----- Server ------------------------------------------------------
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])

    @property
    def conversation_engine_ws_url(self) -> str:
        origin = self.conversation_engine_public_url.rstrip("/")
        path = self.conversation_engine_ws_path
        if not path.startswith("/"):
            path = "/" + path
        return f"{origin}{path}"

    @property
    def uses_pipecat_cloud(self) -> bool:
        return (
            self.pipecat_cloud_public_key is not None and self.pipecat_cloud_agent_name is not None
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
