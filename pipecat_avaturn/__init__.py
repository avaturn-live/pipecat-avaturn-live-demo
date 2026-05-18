"""Pipecat ↔ Avaturn Live bridge.

This package wires a Pipecat pipeline to Avaturn Live's external
conversation engine WebSocket protocol so an AI agent built with Pipecat
can drive an Avaturn Live avatar in real time.

"Avaturn Live" — the real-time AI avatar product at avaturn.live — is a
distinct product from the plain "Avaturn" avatar SDK. The two are not
interchangeable; this package only targets Avaturn Live.

See README.md for the protocol and architecture overview.
"""

from .agent import build_pipeline, run_agent
from .broker import AvaturnLiveClient, CreateSessionResult
from .frames import (
    SpeechSegmentClosedFrame,
    SpeechSegmentCreatedFrame,
    SpeechSegmentPlaybackEndedFrame,
    SpeechSegmentPlaybackInterruptedFrame,
    SpeechSegmentPlaybackStartedFrame,
)
from .pipecat_cloud import AllocatedWebsocketSession, PipecatCloudClient
from .segment_processor import BotSpeechSegmentProcessor
from .serializer import AvaturnLiveFrameSerializer
from .settings import Settings, get_settings
from .transport import AvaturnLiveFastAPIWebsocketTransport

__all__ = [
    "AllocatedWebsocketSession",
    "AvaturnLiveClient",
    "AvaturnLiveFastAPIWebsocketTransport",
    "AvaturnLiveFrameSerializer",
    "BotSpeechSegmentProcessor",
    "CreateSessionResult",
    "PipecatCloudClient",
    "Settings",
    "SpeechSegmentClosedFrame",
    "SpeechSegmentCreatedFrame",
    "SpeechSegmentPlaybackEndedFrame",
    "SpeechSegmentPlaybackInterruptedFrame",
    "SpeechSegmentPlaybackStartedFrame",
    "build_pipeline",
    "get_settings",
    "run_agent",
]
