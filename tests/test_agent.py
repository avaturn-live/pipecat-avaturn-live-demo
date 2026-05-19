"""``build_pipeline`` dispatches by ``settings.pipeline`` to one of two
private builders. These tests prove both shapes construct against a stubbed
WebSocket and dummy API keys, without making any network calls.

Why this exists ("if testing is difficult, the design is wrong"): a
construction-time smoke test is the smallest signal that the dispatcher,
the Settings → service-constructor plumbing, and the imported service
classes all line up. If a future pipecat bump changes any of these, this
fails loudly with the offending traceback.

We walk ``PipelineTask._pipeline``'s nested processor tree to assert the
expected service classes appear in the pipeline. Those attributes are
private but stable enough — if pipecat renames them, this test breaks
visibly and the shape check moves to the new name. That's the right
failure mode.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocket
from pipecat_avaturn import build_pipeline
from pipecat_avaturn.settings import PipelineKind, Settings
from pydantic import SecretStr


def _settings(pipeline: PipelineKind) -> Settings:
    return Settings(
        pipeline=pipeline,
        openai_api_key=SecretStr("test-openai-key"),
        cartesia_api_key=SecretStr("test-cartesia-key"),
    )


def _stub_websocket() -> WebSocket:
    return AsyncMock(spec=WebSocket)


def _processor_type_names(task) -> set[str]:
    """Flatten the (possibly nested) processor tree into a set of class names."""
    names: set[str] = set()
    stack = list(task._pipeline._processors)  # noqa: SLF001
    while stack:
        processor = stack.pop()
        names.add(type(processor).__name__)
        nested = getattr(processor, "_processors", None)
        if nested:
            stack.extend(nested)
    return names


def test_build_pipeline_dispatches_to_openai_realtime() -> None:
    task, transport = build_pipeline(_stub_websocket(), settings=_settings("openai_realtime"))

    assert task is not None
    assert transport is not None
    names = _processor_type_names(task)
    assert "OpenAIRealtimeLLMService" in names
    assert "BotSpeechSegmentProcessor" in names
    # The cascaded-only services must NOT appear in the realtime pipeline.
    assert "CartesiaSTTService" not in names
    assert "CartesiaTTSService" not in names


def test_build_pipeline_dispatches_to_cascaded() -> None:
    task, transport = build_pipeline(_stub_websocket(), settings=_settings("cascaded"))

    assert task is not None
    assert transport is not None
    names = _processor_type_names(task)
    assert {
        "CartesiaSTTService",
        "OpenAIResponsesLLMService",
        "CartesiaTTSService",
        "BotSpeechSegmentProcessor",
    } <= names
    # And the realtime service must NOT be present.
    assert "OpenAIRealtimeLLMService" not in names


@pytest.mark.parametrize("pipeline", ["openai_realtime", "cascaded"])
def test_build_pipeline_returns_transport(pipeline: PipelineKind) -> None:
    """Transport is the second tuple element regardless of pipeline choice."""
    _task, transport = build_pipeline(_stub_websocket(), settings=_settings(pipeline))
    assert type(transport).__name__ == "AvaturnLiveFastAPIWebsocketTransport"
