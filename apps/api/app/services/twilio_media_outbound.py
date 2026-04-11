"""Push mu-law audio to Twilio over the same Media Stream WebSocket (bidirectional)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging

from starlette.websockets import WebSocket

from app.services.twilio_tts_synth import synthesize_speech_to_mulaw

logger = logging.getLogger(__name__)

_FRAME_MS = 20
_CHUNK = 160  # 8 kHz mu-law bytes per 20 ms


async def push_assistant_speech(websocket: WebSocket, stream_sid: str, text: str) -> None:
    """Synthesize text in a worker thread, then send 20 ms mu-law frames to Twilio."""
    if not stream_sid or not (text or "").strip():
        return
    mulaw = await asyncio.to_thread(synthesize_speech_to_mulaw, text)
    if not mulaw:
        logger.warning("twilio_tts: no audio generated for reply")
        return
    try:
        for i in range(0, len(mulaw), _CHUNK):
            chunk = mulaw[i : i + _CHUNK]
            if len(chunk) < _CHUNK:
                chunk = chunk + (b"\xFF" * (_CHUNK - len(chunk)))
            payload = base64.b64encode(chunk).decode("ascii")
            msg = json.dumps(
                {"event": "media", "streamSid": stream_sid, "media": {"payload": payload}}
            )
            await websocket.send_text(msg)
            await asyncio.sleep(_FRAME_MS / 1000.0)
    except Exception:
        logger.exception("twilio_tts: failed while sending media to Twilio")


def mulaw_chunk_duration_seconds(nbytes: int) -> float:
    return max(0.0, (nbytes / _CHUNK) * (_FRAME_MS / 1000.0))
