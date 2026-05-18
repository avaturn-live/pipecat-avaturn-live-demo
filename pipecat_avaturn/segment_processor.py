"""Wraps each bot speech turn in Avaturn Live segment.create / segment.close.

Avaturn Live expects every burst of avatar audio to be framed by JSON
``segment.create`` (before any audio bytes) and ``segment.close`` (after
the last audio chunk). Inside a segment we can stream as many binary
chunks as we like; outside of a segment, audio is dropped with an error.

This processor sits *after* the TTS service (or any service that emits
``OutputAudioRawFrame``) and *before* ``transport.output()`` in the pipeline,
and observes Pipecat's existing ``TTSStartedFrame`` / ``TTSStoppedFrame`` /
``InterruptionFrame`` to know when to open and close segments.
"""

from __future__ import annotations

import uuid

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    OutputTransportMessageFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class BotSpeechSegmentProcessor(FrameProcessor):
    def __init__(self) -> None:
        super().__init__()
        self._current_segment_uid: str | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, TTSStartedFrame):
            if self._current_segment_uid is None:
                self._current_segment_uid = str(uuid.uuid4())
                logger.debug("opening Avaturn Live segment {}", self._current_segment_uid)
                await self.push_frame(
                    OutputTransportMessageFrame(
                        message={
                            "type": "avatar.speech.segment.create",
                            "segment_uid": self._current_segment_uid,
                        }
                    )
                )

        elif isinstance(frame, TTSStoppedFrame | InterruptionFrame):
            if self._current_segment_uid is not None:
                logger.debug("closing Avaturn Live segment {}", self._current_segment_uid)
                await self.push_frame(
                    OutputTransportMessageFrame(
                        message={
                            "type": "avatar.speech.segment.close",
                            "segment_uid": self._current_segment_uid,
                        }
                    )
                )
                self._current_segment_uid = None

        await self.push_frame(frame, direction)
