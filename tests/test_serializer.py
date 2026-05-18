"""Serializer is the wire-format boundary — the one component that must match
Avaturn Live's protocol exactly. Unit-test it independently of the pipeline."""

import json

import pytest
from pipecat.frames.frames import (
    InputAudioRawFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    OutputTransportMessageFrame,
)
from pipecat_avaturn.frames import (
    SpeechSegmentClosedFrame,
    SpeechSegmentCreatedFrame,
    SpeechSegmentPlaybackEndedFrame,
    SpeechSegmentPlaybackInterruptedFrame,
    SpeechSegmentPlaybackStartedFrame,
)
from pipecat_avaturn.serializer import AvaturnLiveFrameSerializer

# ----- outbound (Pipecat frame → Avaturn Live wire) -----------------------


async def test_audio_frame_serializes_to_raw_bytes():
    audio = b"\x00\x01" * 240
    serializer = AvaturnLiveFrameSerializer(user_sample_rate=16_000)

    out = await serializer.serialize(
        OutputAudioRawFrame(audio=audio, sample_rate=24_000, num_channels=1)
    )

    assert out == audio


async def test_transport_message_serializes_to_json():
    serializer = AvaturnLiveFrameSerializer(user_sample_rate=16_000)
    msg = {"type": "avatar.speech.segment.create", "segment_uid": "abc"}

    out = await serializer.serialize(OutputTransportMessageFrame(message=msg))

    assert isinstance(out, str)
    assert json.loads(out) == msg


async def test_interruption_serializes_to_speech_interrupt():
    serializer = AvaturnLiveFrameSerializer(user_sample_rate=16_000)

    out = await serializer.serialize(InterruptionFrame())

    assert isinstance(out, str)
    assert json.loads(out) == {"type": "avatar.speech.interrupt"}


# ----- inbound (Avaturn Live wire → Pipecat frame) ------------------------


async def test_binary_deserializes_to_input_audio():
    serializer = AvaturnLiveFrameSerializer(user_sample_rate=16_000)
    audio = b"\xff" * 320

    frame = await serializer.deserialize(audio)

    assert isinstance(frame, InputAudioRawFrame)
    assert frame.audio == audio
    assert frame.sample_rate == 16_000
    assert frame.num_channels == 1


@pytest.mark.parametrize(
    ("event_type", "frame_cls"),
    [
        ("avatar.speech.segment.created", SpeechSegmentCreatedFrame),
        ("avatar.speech.segment.closed", SpeechSegmentClosedFrame),
        ("avatar.speech.segment.playback.started", SpeechSegmentPlaybackStartedFrame),
        ("avatar.speech.segment.playback.ended", SpeechSegmentPlaybackEndedFrame),
        ("avatar.speech.segment.playback.interrupted", SpeechSegmentPlaybackInterruptedFrame),
    ],
)
async def test_event_deserializes_to_matching_frame(event_type: str, frame_cls: type):
    serializer = AvaturnLiveFrameSerializer(user_sample_rate=16_000)

    frame = await serializer.deserialize(json.dumps({"type": event_type}))

    assert isinstance(frame, frame_cls)


async def test_segment_ids_round_trip_from_payload():
    serializer = AvaturnLiveFrameSerializer(user_sample_rate=16_000)
    raw = json.dumps(
        {
            "type": "avatar.speech.segment.playback.started",
            "segment_id": "seg_42",
            "segment_uid": "uid-abc",
        }
    )

    frame = await serializer.deserialize(raw)

    assert isinstance(frame, SpeechSegmentPlaybackStartedFrame)
    assert frame.segment_id == "seg_42"
    assert frame.segment_uid == "uid-abc"


async def test_interrupted_includes_played_duration():
    serializer = AvaturnLiveFrameSerializer(user_sample_rate=16_000)
    raw = json.dumps(
        {
            "type": "avatar.speech.segment.playback.interrupted",
            "segment_id": "seg_7",
            "played_duration": 1.25,
        }
    )

    frame = await serializer.deserialize(raw)

    assert isinstance(frame, SpeechSegmentPlaybackInterruptedFrame)
    assert frame.segment_id == "seg_7"
    assert frame.played_duration == 1.25


async def test_unknown_event_returns_none():
    serializer = AvaturnLiveFrameSerializer(user_sample_rate=16_000)

    assert await serializer.deserialize(json.dumps({"type": "totally.unrelated"})) is None


async def test_malformed_json_returns_none():
    serializer = AvaturnLiveFrameSerializer(user_sample_rate=16_000)

    assert await serializer.deserialize("not json at all {{") is None


async def test_non_dict_json_returns_none():
    # Avaturn Live shouldn't send these, but the boundary must stay defensive.
    serializer = AvaturnLiveFrameSerializer(user_sample_rate=16_000)

    assert await serializer.deserialize(json.dumps([1, 2, 3])) is None
    assert await serializer.deserialize(json.dumps("string-payload")) is None
