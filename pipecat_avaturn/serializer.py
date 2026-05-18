"""WebSocket frame serializer that speaks Avaturn Live's protocol.

Wire protocol (between Avaturn Live and this conversation engine):

    Binary frames
        - From Avaturn Live → engine: user microphone audio,
          PCM16LE @ user.sample_rate (configured at session create).
        - From engine → Avaturn Live: avatar speech audio,
          PCM16LE @ 24 kHz. Each binary chunk belongs to the currently open
          speech segment.

    Text frames (JSON)
        Outgoing (engine → Avaturn Live):
            { "type": "avatar.speech.segment.create", "segment_uid": "..." }
            { "type": "avatar.speech.segment.close",  "segment_uid": "..." }
            { "type": "avatar.speech.interrupt" }
            { "type": "sdk.message.send", "data": {...} }            # optional

        Incoming (Avaturn Live → engine):
            { "type": "avatar.speech.segment.created",   "segment_id": "...", "segment_uid": "..." }
            { "type": "avatar.speech.segment.closed",    "segment_id": "...", "segment_uid": "..." }
            { "type": "avatar.speech.segment.playback.started",     ... }
            { "type": "avatar.speech.segment.playback.ended",       ... }
            { "type": "avatar.speech.segment.playback.interrupted", ... }
            { "type": "sdk.message.receive", "data": {...} }         # optional
            { "type": "error", "subtype": "...", "reason": "..." }

The serializer is bidirectional: a single class handles both audio (binary)
and control (JSON), matching the two modes the WebSocket carries.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Final

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    OutputTransportMessageFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer

from .frames import (
    SpeechSegmentClosedFrame,
    SpeechSegmentCreatedFrame,
    SpeechSegmentPlaybackEndedFrame,
    SpeechSegmentPlaybackInterruptedFrame,
    SpeechSegmentPlaybackStartedFrame,
)

AVATURN_LIVE_AUDIO_OUT_SAMPLE_RATE: Final[int] = 24_000


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _float_or_none(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


# Each factory takes the parsed JSON payload and returns the Pipecat frame
# that mirrors it. Listing them explicitly avoids reflection (and the type
# erasure that comes with it) and keeps every incoming event auditable in
# one place — read the dict, you know the whole protocol.
_EVENT_FACTORIES: Final[dict[str, Callable[[dict[str, object]], Frame]]] = {
    "avatar.speech.segment.created": lambda p: SpeechSegmentCreatedFrame(
        segment_id=_str_or_none(p.get("segment_id")),
        segment_uid=_str_or_none(p.get("segment_uid")),
    ),
    "avatar.speech.segment.closed": lambda p: SpeechSegmentClosedFrame(
        segment_id=_str_or_none(p.get("segment_id")),
        segment_uid=_str_or_none(p.get("segment_uid")),
    ),
    "avatar.speech.segment.playback.started": lambda p: SpeechSegmentPlaybackStartedFrame(
        segment_id=_str_or_none(p.get("segment_id")),
        segment_uid=_str_or_none(p.get("segment_uid")),
    ),
    "avatar.speech.segment.playback.ended": lambda p: SpeechSegmentPlaybackEndedFrame(
        segment_id=_str_or_none(p.get("segment_id")),
        segment_uid=_str_or_none(p.get("segment_uid")),
    ),
    "avatar.speech.segment.playback.interrupted": lambda p: SpeechSegmentPlaybackInterruptedFrame(
        segment_id=_str_or_none(p.get("segment_id")),
        segment_uid=_str_or_none(p.get("segment_uid")),
        played_duration=_float_or_none(p.get("played_duration")),
    ),
}


class AvaturnLiveFrameSerializer(FrameSerializer):
    """Bridges Pipecat frames ↔ Avaturn Live WebSocket messages.

    The ``user_sample_rate`` matches what was passed in
    ``conversation_engine.audio.user.sample_rate`` when the Avaturn Live
    session was created. Avaturn Live always sends avatar speech back at
    24 kHz mono, so ``OutputAudioRawFrame.audio`` must already be 24 kHz
    PCM16LE — the Pipecat pipeline is responsible for resampling its TTS
    output to that rate.

    Mono is hardcoded because Avaturn Live is mono-only on both sides;
    making it configurable would only invite silently-broken stereo
    deployments.
    """

    _NUM_CHANNELS: Final[int] = 1

    def __init__(self, user_sample_rate: int) -> None:
        # user_sample_rate is fixed at construction time so it matches whatever the
        # broker advertised to Avaturn Live in conversation_engine.audio.user.sample_rate.
        # Mutating it later from a StartFrame would silently desync the two ends.
        self.user_sample_rate = user_sample_rate

    async def serialize(self, frame: Frame) -> bytes | str | None:
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio

        if isinstance(frame, OutputTransportMessageFrame):
            return json.dumps(frame.message)

        if isinstance(frame, InterruptionFrame):
            return json.dumps({"type": "avatar.speech.interrupt"})

        return None

    async def deserialize(self, data: bytes | str) -> Frame | None:
        if isinstance(data, bytes | bytearray):
            return InputAudioRawFrame(
                audio=bytes(data),
                num_channels=self._NUM_CHANNELS,
                sample_rate=self.user_sample_rate,
            )

        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            logger.warning("Avaturn Live sent non-JSON text frame: {!r}", data[:200])
            return None

        if not isinstance(payload, dict):
            return None

        event_type = payload.get("type")
        if not isinstance(event_type, str):
            return None

        factory = _EVENT_FACTORIES.get(event_type)
        if factory is None:
            if event_type == "error":
                logger.error("Avaturn Live reported error: {}", payload)
            return None

        return factory(payload)
