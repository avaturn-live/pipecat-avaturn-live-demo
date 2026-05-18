"""Pipecat frames that mirror Avaturn Live's segment lifecycle events.

Avaturn Live emits JSON events over the conversation-engine WebSocket
whenever the avatar acknowledges, plays, or interrupts a speech
segment. The serializer turns those into the typed frames below so
downstream processors can react to them (logging, analytics, custom
barge-in logic, etc.) — nothing in the default demo pipeline reads
them, but extensions can subscribe.

Field semantics come from Avaturn Live's wire format:

* ``segment_uid``  — the uid we set when we opened the segment via
  ``segment.create``. Used to correlate with what we sent.
* ``segment_id``   — Avaturn Live's own server-side id for the segment.
  Useful for log correlation against the session logs in Avaturn Live's
  dashboard.
* ``played_duration`` — seconds of speech actually played before
  interruption; only set on ``playback.interrupted``.
"""

from dataclasses import dataclass

from pipecat.frames.frames import Frame


@dataclass
class SpeechSegmentCreatedFrame(Frame):
    """Avaturn Live acknowledged a new speech segment we created."""

    segment_id: str | None = None
    segment_uid: str | None = None


@dataclass
class SpeechSegmentClosedFrame(Frame):
    """Avaturn Live finished receiving audio for the current segment."""

    segment_id: str | None = None
    segment_uid: str | None = None


@dataclass
class SpeechSegmentPlaybackStartedFrame(Frame):
    """The avatar started speaking the segment on screen."""

    segment_id: str | None = None
    segment_uid: str | None = None


@dataclass
class SpeechSegmentPlaybackEndedFrame(Frame):
    """The avatar finished speaking the segment on screen."""

    segment_id: str | None = None
    segment_uid: str | None = None


@dataclass
class SpeechSegmentPlaybackInterruptedFrame(Frame):
    """Playback of the current segment was cut short (e.g. by user barge-in)."""

    segment_id: str | None = None
    segment_uid: str | None = None
    played_duration: float | None = None
