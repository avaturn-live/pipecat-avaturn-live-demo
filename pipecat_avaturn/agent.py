"""Build and run the Pipecat pipeline that drives an Avaturn Live avatar.

Two pipelines live behind one entry point. ``settings.pipeline`` is the
single source of truth for which one ``build_pipeline`` constructs:

* ``"openai_realtime"`` — OpenAI Realtime (speech-to-speech in one service).
  This is the default; turn detection lives inside the realtime service via
  ``SemanticTurnDetection`` and the user aggregator defers to it through
  ``ExternalUserTurnStrategies``.

* ``"cascaded"`` — Cartesia Ink Whisper STT → OpenAI LLM → Cartesia Sonic 3.5
  TTS, with Pipecat's local Smart Turn V3 ML classifier sitting on top of
  Silero VAD as the end-of-turn detector. Turn detection here is explicit
  because no single service owns it.

What is invariant across both pipelines:

* ``AvaturnLiveFastAPIWebsocketTransport`` — pacing-disabled FastAPI WS.
* ``AvaturnLiveFrameSerializer`` — Avaturn Live wire-format boundary.
* ``BotSpeechSegmentProcessor`` — wraps avatar audio in segment envelopes.
* 24 kHz mono PCM16LE output to Avaturn Live (``AVATURN_LIVE_AUDIO_OUT_SAMPLE_RATE``).
* User/assistant turn logging via ``_wire_turn_logging``.

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


def _build_transport(
    websocket: WebSocket, *, settings: Settings
) -> AvaturnLiveFastAPIWebsocketTransport:
    serializer = AvaturnLiveFrameSerializer(user_sample_rate=settings.user_audio_sample_rate)
    return AvaturnLiveFastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_out_sample_rate=AVATURN_LIVE_AUDIO_OUT_SAMPLE_RATE,
            add_wav_header=False,
            serializer=serializer,
        ),
    )


def _wire_turn_logging(user_agg: Any, assistant_agg: Any) -> None:
    """Attach identical user/assistant turn loggers to both pipelines."""

    @user_agg.event_handler("on_user_turn_stopped")
    async def _on_user_turn(_agg: Any, _strategy: Any, msg: UserTurnStoppedMessage) -> None:
        logger.info("user → {!r}", msg.content)

    @assistant_agg.event_handler("on_assistant_turn_stopped")
    async def _on_assistant_turn(_agg: Any, msg: AssistantTurnStoppedMessage) -> None:
        suffix = " [interrupted]" if msg.interrupted else ""
        logger.info("assistant → {!r}{}", msg.content, suffix)


def _pipeline_task(pipeline: Pipeline, *, settings: Settings) -> PipelineTask:
    return PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=settings.user_audio_sample_rate,
            audio_out_sample_rate=AVATURN_LIVE_AUDIO_OUT_SAMPLE_RATE,
        ),
    )


def _build_openai_realtime_pipeline(
    websocket: WebSocket, *, settings: Settings
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

    transport = _build_transport(websocket, settings=settings)

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

    _wire_turn_logging(user_aggregator, assistant_aggregator)

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

    return _pipeline_task(pipeline, settings=settings), transport


def _build_cascaded_pipeline(
    websocket: WebSocket, *, settings: Settings
) -> tuple[PipelineTask, AvaturnLiveFastAPIWebsocketTransport]:
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.services.cartesia.stt import CartesiaSTTService
    from pipecat.services.cartesia.tts import CartesiaTTSService
    from pipecat.services.openai.responses.llm import OpenAIResponsesLLMService
    from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
    from pipecat.turns.user_turn_strategies import UserTurnStrategies

    transport = _build_transport(websocket, settings=settings)

    stt = CartesiaSTTService(
        api_key=settings.cartesia_api_key.get_secret_value(),
        settings=CartesiaSTTService.Settings(
            model=settings.cartesia_stt_model,
            language=settings.cartesia_language,
        ),
    )

    # GPT-5.5 is recommended by OpenAI to run over the Responses API rather
    # than Chat Completions. reasoning.effort=none + text.verbosity=low keep
    # responses snappy and concise for a voice agent.
    llm = OpenAIResponsesLLMService(
        api_key=settings.openai_api_key.get_secret_value(),
        settings=OpenAIResponsesLLMService.Settings(
            model=settings.openai_llm_model,
            system_instruction=settings.system_prompt,
            extra={
                "reasoning": {"effort": "none"},
                "text": {"verbosity": "low"},
            },
        ),
    )

    # Cartesia copies sample_rate into the WebSocket output spec. Pin it to
    # AVATURN_LIVE_AUDIO_OUT_SAMPLE_RATE so the bytes arriving at the
    # serializer already match what Avaturn Live expects (24 kHz mono PCM16LE).
    tts = CartesiaTTSService(
        api_key=settings.cartesia_api_key.get_secret_value(),
        sample_rate=AVATURN_LIVE_AUDIO_OUT_SAMPLE_RATE,
        settings=CartesiaTTSService.Settings(
            model=settings.cartesia_tts_model,
            voice=settings.cartesia_voice,
            language=settings.cartesia_language,
        ),
    )

    # Cascaded path has no single owner of turn detection — pair Silero VAD
    # with Smart Turn V3 (ML end-of-turn). system_prompt enters via the
    # service's system_instruction above, not via LLMContext.
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        LLMContext(),
        user_params=LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(
                stop=[
                    TurnAnalyzerUserTurnStopStrategy(
                        turn_analyzer=LocalSmartTurnAnalyzerV3(),
                    ),
                ],
            ),
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    _wire_turn_logging(user_aggregator, assistant_aggregator)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            BotSpeechSegmentProcessor(),
            transport.output(),
            assistant_aggregator,
        ]
    )

    return _pipeline_task(pipeline, settings=settings), transport


def build_pipeline(
    websocket: WebSocket,
    *,
    settings: Settings,
) -> tuple[PipelineTask, AvaturnLiveFastAPIWebsocketTransport]:
    match settings.pipeline:
        case "openai_realtime":
            return _build_openai_realtime_pipeline(websocket, settings=settings)
        case "cascaded":
            return _build_cascaded_pipeline(websocket, settings=settings)


async def run_agent(websocket: WebSocket, *, settings: Settings | None = None) -> None:
    """Drive the pipeline against one accepted Avaturn Live WebSocket.

    Preconditions:
        * ``websocket`` is already accepted (``await ws.accept()``).
        * Auth / rate-limit / origin checks have already been done by the
          route handler.
    """

    settings = settings or get_settings()
    logger.info("building pipeline: {}", settings.pipeline)
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
