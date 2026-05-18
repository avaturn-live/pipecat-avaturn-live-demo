"""FastAPI WebSocket transport tuned for Avaturn Live.

Avaturn Live runs its own playback scheduler and expects audio chunks
as fast as the conversation engine can produce them. Pipecat's stock
``FastAPIWebsocketOutputTransport`` paces audio writes to roughly
real-time so the client doesn't get a giant burst — that pacing
desynchronises Avaturn Live's segment timing and stalls speech.

The fix is a single private knob, ``_write_audio_sleep``, which we
replace with a no-op. We monkey-patch *after* construction so the
override is one obvious line in this file and not hidden inside a
re-implemented ``__init__``. The knob is private; track Pipecat
releases and adjust if it gets renamed.
"""

from __future__ import annotations

from fastapi import WebSocket
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)


async def _no_sleep(*_args: object, **_kwargs: object) -> None:
    return


class AvaturnLiveFastAPIWebsocketTransport(FastAPIWebsocketTransport):
    """Stock transport with output-pacing disabled for Avaturn Live."""

    def __init__(
        self,
        websocket: WebSocket,
        params: FastAPIWebsocketParams,
        input_name: str | None = None,
        output_name: str | None = None,
    ) -> None:
        super().__init__(
            websocket=websocket,
            params=params,
            input_name=input_name,
            output_name=output_name,
        )
        self._output._write_audio_sleep = _no_sleep  # noqa: SLF001
