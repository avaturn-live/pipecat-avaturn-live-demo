"""``BotSpeechSegmentProcessor`` is a tiny FSM: it watches Pipecat's TTS
lifecycle frames and emits ``avatar.speech.segment.create`` /
``avatar.speech.segment.close`` envelopes around them.

We subclass with a recording ``push_frame`` instead of monkey-patching, so the
test stays type-clean and the design pressure ("if testing is difficult, the
design is wrong") points to a clean subclass extension rather than a hack."""

from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    OutputTransportMessageFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat_avaturn.segment_processor import BotSpeechSegmentProcessor


class _RecordingProcessor(BotSpeechSegmentProcessor):
    """Same processor; ``push_frame`` records instead of forwarding."""

    def __init__(self) -> None:
        super().__init__()
        self.pushed: list[Frame] = []

    async def push_frame(
        self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM
    ) -> None:
        self.pushed.append(frame)


def _messages(proc: _RecordingProcessor) -> list[dict[str, object]]:
    return [f.message for f in proc.pushed if isinstance(f, OutputTransportMessageFrame)]


async def test_tts_started_opens_segment():
    proc = _RecordingProcessor()

    await proc.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

    messages = _messages(proc)
    assert len(messages) == 1
    assert messages[0]["type"] == "avatar.speech.segment.create"
    assert isinstance(messages[0]["segment_uid"], str)


async def test_tts_stopped_closes_open_segment():
    proc = _RecordingProcessor()

    await proc.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
    await proc.process_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM)

    types = [m["type"] for m in _messages(proc)]
    assert types == ["avatar.speech.segment.create", "avatar.speech.segment.close"]


async def test_interruption_closes_open_segment():
    proc = _RecordingProcessor()

    await proc.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
    await proc.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)

    types = [m["type"] for m in _messages(proc)]
    assert types == ["avatar.speech.segment.create", "avatar.speech.segment.close"]


async def test_close_with_no_open_segment_is_noop():
    proc = _RecordingProcessor()

    await proc.process_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM)

    assert _messages(proc) == []


async def test_only_one_segment_open_at_a_time():
    proc = _RecordingProcessor()

    await proc.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
    await proc.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

    # The second TTSStartedFrame while one's open must not open another.
    types = [m["type"] for m in _messages(proc)]
    assert types == ["avatar.speech.segment.create"]


async def test_segments_get_unique_uids():
    proc = _RecordingProcessor()

    await proc.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
    await proc.process_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM)
    await proc.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
    await proc.process_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM)

    creates = [m for m in _messages(proc) if m["type"] == "avatar.speech.segment.create"]
    uids = {m["segment_uid"] for m in creates}
    assert len(uids) == 2
