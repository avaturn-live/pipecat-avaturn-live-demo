"""Build and run the Pipecat pipeline that drives an Avaturn Live avatar.

Pipeline shape (OpenAI Realtime speech-to-speech):

    transport.input()  ──▶ user_aggregator
                            ▶ OpenAIRealtimeLLMService
                                ▶ BotSpeechSegmentProcessor
                                    ▶ transport.output()  ──▶ Avaturn Live
                        ◀── assistant_aggregator

OpenAI Realtime does STT + LLM + TTS in one service. Turn-detection lives
inside the realtime service (``SemanticTurnDetection``), and we wire the
user aggregator with ``ExternalUserTurnStrategies`` so Pipecat doesn't
run its own VAD/smart-turn in parallel — without that, the two would
fight each other on barge-in.

The realtime service emits ``TTSStartedFrame`` / ``TTSStoppedFrame`` around
each speech turn, which is exactly what ``BotSpeechSegmentProcessor``
needs to wrap audio in Avaturn Live ``segment.create`` / ``segment.close``
envelopes.

To swap in a cascaded STT → LLM → TTS pipeline, replace ``build_pipeline``
body following Pipecat's quickstart — only the segment processor and the
transport stay the same.

Lifecycle contract
------------------
``run_agent`` assumes the caller has already accepted the WebSocket and
already authenticated the peer. Both responsibilities live at the boundary
(``server.py`` for self-host, ``bot.py`` for Pipecat Cloud) so this module
contains only pipeline construction and lifecycle.
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from fastapi import WebSocket
from loguru import logger
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    AssistantTurnStoppedMessage,
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
    UserTurnStoppedMessage,
)
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams
from pipecat.turns.user_turn_strategies import ExternalUserTurnStrategies
from starlette.websockets import WebSocketState

from .segment_processor import BotSpeechSegmentProcessor
from .serializer import AVATURN_LIVE_AUDIO_OUT_SAMPLE_RATE, AvaturnLiveFrameSerializer
from .settings import Settings, get_settings
from .transport import AvaturnLiveFastAPIWebsocketTransport


def build_pipeline(
    websocket: WebSocket,
    *,
    settings: Settings,
) -> tuple[PipelineTask, AvaturnLiveFastAPIWebsocketTransport]:
    from pipecat.services.openai.realtime.events import (
        AudioConfiguration,
        AudioInput,
        AudioOutput,
        InputAudioTranscription,
        SemanticTurnDetection,
        SessionProperties,
    )
    from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService

    serializer = AvaturnLiveFrameSerializer(user_sample_rate=settings.user_audio_sample_rate)

    transport = AvaturnLiveFastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_out_sample_rate=AVATURN_LIVE_AUDIO_OUT_SAMPLE_RATE,
            add_wav_header=False,
            serializer=serializer,
        ),
    )

    realtime = OpenAIRealtimeLLMService(
        api_key=settings.openai_api_key.get_secret_value(),
        settings=OpenAIRealtimeLLMService.Settings(
            model=settings.openai_realtime_model,
            system_instruction=settings.system_prompt,
            session_properties=SessionProperties(
                audio=AudioConfiguration(
                    input=AudioInput(
                        transcription=InputAudioTranscription(
                            model=settings.openai_realtime_transcribe_model,
                        ),
                        turn_detection=SemanticTurnDetection(eagerness="high"),
                    ),
                    output=AudioOutput(voice=settings.openai_realtime_voice),
                ),
            ),
        ),
    )

    # OpenAI Realtime owns turn detection (SemanticTurnDetection above), so
    # the aggregator must defer to it via ExternalUserTurnStrategies instead
    # of running its own VAD / smart-turn analysis.
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        LLMContext(),
        user_params=LLMUserAggregatorParams(user_turn_strategies=ExternalUserTurnStrategies()),
    )

    @user_aggregator.event_handler("on_user_turn_stopped")
    async def _on_user_turn(_agg: Any, _strategy: Any, msg: UserTurnStoppedMessage) -> None:
        logger.info("user → {!r}", msg.content)

    @assistant_aggregator.event_handler("on_assistant_turn_stopped")
    async def _on_assistant_turn(_agg: Any, msg: AssistantTurnStoppedMessage) -> None:
        suffix = " [interrupted]" if msg.interrupted else ""
        logger.info("assistant → {!r}{}", msg.content, suffix)

    pipeline = Pipeline(
        [
            transport.input(),
            user_aggregator,
            realtime,
            BotSpeechSegmentProcessor(),
            transport.output(),
            assistant_aggregator,
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=settings.user_audio_sample_rate,
            audio_out_sample_rate=AVATURN_LIVE_AUDIO_OUT_SAMPLE_RATE,
        ),
    )

    return task, transport


async def run_agent(websocket: WebSocket, *, settings: Settings | None = None) -> None:
    """Drive the pipeline against one accepted Avaturn Live WebSocket.

    Preconditions:
        * ``websocket`` is already accepted (``await ws.accept()``).
        * Auth / rate-limit / origin checks have already been done by the
          route handler.
    """

    settings = settings or get_settings()
    task, transport = build_pipeline(websocket, settings=settings)

    @transport.event_handler("on_client_connected")
    async def _on_connected(_t: Any, _c: Any) -> None:
        logger.info("Avaturn Live connected to conversation engine")

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(_t: Any, _c: Any) -> None:
        logger.info("Avaturn Live disconnected from conversation engine")
        await task.cancel()

    try:
        # handle_sigint=False — uvicorn owns the process signal handlers.
        await PipelineRunner(handle_sigint=False).run(task)
    finally:
        # Suppress: pipecat's output transport may have already closed.
        if websocket.client_state != WebSocketState.DISCONNECTED:
            with suppress(RuntimeError):
                await websocket.close()
