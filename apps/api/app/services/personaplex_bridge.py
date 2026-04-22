"""Bridge between Twilio Media Streams (mu-law 8kHz) and PersonaPlex (Opus 24kHz).

Manages a per-call WebSocket connection to the local PersonaPlex server
and converts audio formats bidirectionally in real-time.

Audio flow:
  Twilio → mu-law 8kHz → PCM-16 8kHz → resample 24kHz → Opus → PersonaPlex
  PersonaPlex → Opus → PCM-float 24kHz → resample 8kHz → mu-law → Twilio

Key design: send_mulaw() is non-blocking — it enqueues audio for a background
task so the Twilio receive loop is never stalled by PersonaPlex backpressure.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Callable

import aiohttp
import numpy as np
import sphn

from app.config import settings
from app.services.twilio_mulaw import mulaw_payload_to_pcm16_le, pcm16_le_to_mulaw

logger = logging.getLogger(__name__)

_TWILIO_RATE = 8000
_PP_RATE = 24000
_PP_FRAME = 1920  # PersonaPlex expects 80ms frames at 24kHz
_TWILIO_CHUNK = 160  # 20ms mu-law frame for Twilio outbound


def _resample_8k_to_24k(pcm16_le: bytes) -> np.ndarray:
    """Upsample 8kHz PCM-16 LE to 24kHz float32 (clean 3x factor)."""
    samples = np.frombuffer(pcm16_le, dtype=np.int16).astype(np.float32) / 32768.0
    return np.repeat(samples, 3)


def _resample_24k_to_8k(pcm_float: np.ndarray) -> bytes:
    """Downsample 24kHz float32 to 8kHz PCM-16 LE (clean 3x factor)."""
    downsampled = pcm_float[::3]
    clipped = np.clip(downsampled * 32768.0, -32768, 32767).astype(np.int16)
    return clipped.tobytes()


def _truncate_personaplex_prompt(text: str) -> str:
    """Keep WebSocket GET URL within safe line limits (encoding expands length)."""
    max_c = max(512, int(settings.personaplex_prompt_max_chars))
    if len(text) <= max_c:
        return text
    suffix = "\n...[truncated for PersonaPlex URL limit; raise KITCHENCALL_PERSONAPLEX_PROMPT_MAX_CHARS or shorten menu]"
    head = max_c - len(suffix)
    if head < 256:
        head = 256
    out = text[:head] + suffix
    logger.warning(
        "personaplex text_prompt truncated: %d -> %d chars (max=%d)",
        len(text),
        len(out),
        max_c,
    )
    return out


def _build_text_prompt(menu_json_prompt: str) -> str:
    """Build PersonaPlex system prompt from menu data."""
    custom = (settings.personaplex_text_prompt or "").strip()
    if custom:
        return custom
    # Optimized for phone: conversational but concise
    return (
        f"You're Alex at Sandur's Pizza. Be friendly and helpful.\n\n"
        f"{menu_json_prompt}\n\n"
        f"Keep responses brief and natural. When asked about the menu, mention "
        f"2-3 popular items like Margherita, Quattro Formaggi pizzas, or Carbonara pasta. "
        f"Confirm orders clearly. Be warm but concise - you're on the phone."
    )


class PersonaPlexSession:
    """One PersonaPlex WebSocket session per Twilio call.

    Handles bidirectional audio streaming and format conversion.
    All sends to PersonaPlex go through an asyncio.Queue so the caller
    (Twilio receive loop) is never blocked by PersonaPlex backpressure
    or the model's system-prompt warmup.
    """

    def __init__(
        self,
        *,
        on_mulaw_out: Callable[[bytes], asyncio.Future],
        on_text_token: Callable[[str], None] | None = None,
        menu_prompt: str = "",
    ):
        self._on_mulaw_out = on_mulaw_out
        self._on_text_token = on_text_token
        self._menu_prompt = menu_prompt
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._recv_task: asyncio.Task | None = None
        self._send_task: asyncio.Task | None = None
        self._closed = False
        self._opus_writer = sphn.OpusStreamWriter(_PP_RATE)
        self._opus_reader = sphn.OpusStreamReader(_PP_RATE)
        self._inbound_buf = np.array([], dtype=np.float32)
        self._ready = asyncio.Event()
        # Set when first outbound audio (0x01) is decoded — use for Twilio filler until model speaks.
        self._outbound_audio_started = asyncio.Event()
        # Extra headroom while Twilio audio arrives before PersonaPlex handshake completes.
        self._send_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=400)

    async def connect(self) -> bool:
        """Open WebSocket to PersonaPlex server. Returns True on success."""
        url = (settings.personaplex_ws_url or "").strip()
        if not url:
            logger.error("personaplex_ws_url not configured")
            return False

        voice = (settings.personaplex_voice or "NATF2").strip()
        text_prompt = _truncate_personaplex_prompt(_build_text_prompt(self._menu_prompt))

        params = {"voice_prompt": voice, "text_prompt": text_prompt}
        logger.info(
            "personaplex connecting to %s voice=%s prompt_len=%d (max_chars=%d)",
            url,
            voice,
            len(text_prompt),
            settings.personaplex_prompt_max_chars,
        )

        try:
            self._session = aiohttp.ClientSession()
            self._ws = await self._session.ws_connect(
                url, params=params, timeout=aiohttp.ClientWSTimeout(ws_close=60.0)
            )
        except Exception:
            logger.exception("personaplex connection failed")
            await self._cleanup()
            return False

        self._recv_task = asyncio.create_task(self._receive_loop())
        self._send_task = asyncio.create_task(self._send_loop())
        return True

    async def _receive_loop(self) -> None:
        """Read from PersonaPlex WS: audio (0x01) and text (0x02) messages."""
        ws = self._ws
        if ws is None:
            return
        try:
            async for msg in ws:
                if self._closed:
                    break
                if msg.type == aiohttp.WSMsgType.BINARY:
                    data = msg.data
                    if not data:
                        continue
                    tag = data[0]
                    payload = data[1:]

                    if tag == 0x00:
                        logger.info("personaplex session ready (handshake byte received)")
                        self._ready.set()

                    elif tag == 0x01 and payload:
                        try:
                            pcm_float = self._opus_reader.append_bytes(payload)
                        except Exception:
                            logger.exception("personaplex: opus decode failed")
                            continue
                        if pcm_float.shape[-1] > 0:
                            pcm_8k = _resample_24k_to_8k(pcm_float)
                            mulaw = pcm16_le_to_mulaw(pcm_8k)
                            if len(mulaw) > 0:
                                if not self._outbound_audio_started.is_set():
                                    logger.info("PersonaPlex first audio packet received")
                                    self._outbound_audio_started.set()
                            try:
                                await self._on_mulaw_out(mulaw)
                            except Exception:
                                logger.exception("personaplex: mulaw callback failed")

                    elif tag == 0x02 and payload:
                        text = payload.decode("utf-8", errors="replace")
                        if self._on_text_token:
                            try:
                                self._on_text_token(text)
                            except Exception:
                                pass

                elif msg.type in (
                    aiohttp.WSMsgType.ERROR,
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                ):
                    logger.info("personaplex WS closed/error: %s", msg.type)
                    break
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("personaplex receive loop error")
        finally:
            if not self._ready.is_set():
                logger.error(
                    "personaplex closed before handshake (0x00): server dropped the socket "
                    "(restart PersonaPlex with current apps/personaplex local_web.py: handshake "
                    "early + recv_loop before tokenize). If this persists, shorten the prompt "
                    "(KITCHENCALL_PERSONAPLEX_PROMPT_MAX_CHARS) or check PersonaPlex logs."
                )
            logger.info("personaplex receive loop ended")
            self._closed = True

    async def _send_loop(self) -> None:
        """Drain the send queue → Opus-encode → forward to PersonaPlex WS.

        Waits for the PersonaPlex handshake (0x00) before sending any audio,
        so audio sent during system-prompt warmup is queued, not dropped.
        """
        try:
            logger.info("personaplex send loop: waiting for handshake…")
            try:
                await asyncio.wait_for(self._ready.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                logger.error("personaplex handshake timed out after 30s")
                self._closed = True
                return
            logger.info("personaplex send loop: handshake received, draining queue")

            while not self._closed:
                try:
                    mulaw = await asyncio.wait_for(self._send_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if mulaw is None:
                    break

                pcm16 = mulaw_payload_to_pcm16_le(mulaw)
                pcm_24k = _resample_8k_to_24k(pcm16)
                self._inbound_buf = np.concatenate([self._inbound_buf, pcm_24k])

                while len(self._inbound_buf) >= _PP_FRAME:
                    frame = self._inbound_buf[:_PP_FRAME]
                    self._inbound_buf = self._inbound_buf[_PP_FRAME:]
                    opus_bytes = self._opus_writer.append_pcm(frame)
                    if len(opus_bytes) > 0:
                        ws = self._ws
                        if ws is None or ws.closed:
                            self._closed = True
                            return
                        try:
                            await ws.send_bytes(b"\x01" + opus_bytes)
                        except Exception:
                            logger.exception("personaplex: failed to send audio frame")
                            self._closed = True
                            return
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("personaplex send loop error")
        finally:
            logger.info("personaplex send loop ended")

    def send_mulaw(self, mulaw: bytes) -> None:
        """Enqueue mu-law audio for PersonaPlex — never blocks the caller."""
        if self._closed:
            return
        try:
            self._send_queue.put_nowait(mulaw)
        except asyncio.QueueFull:
            pass

    async def close(self) -> None:
        """Gracefully shut down the PersonaPlex session."""
        self._closed = True
        try:
            self._send_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        for task in (self._recv_task, self._send_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        await self._cleanup()

    async def _cleanup(self) -> None:
        if self._ws and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._session and not self._session.closed:
            try:
                await self._session.close()
            except Exception:
                pass
        self._ws = None
        self._session = None

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and not self._ws.closed and not self._closed

    @property
    def ready(self) -> asyncio.Event:
        return self._ready

    @property
    def outbound_audio_started(self) -> asyncio.Event:
        return self._outbound_audio_started


def build_menu_prompt_from_catalog(menu_path) -> str:
    """Build a concise menu description string from the JSON catalog for PersonaPlex."""
    from app.services.menu_catalog import MenuCatalog

    try:
        catalog = MenuCatalog.load(menu_path)
    except Exception:
        logger.warning("Could not load menu catalog for PersonaPlex prompt")
        return ""

    lines = [catalog.restaurant_name]
    
    # Group by category - show key items only
    categories = {}
    for item in catalog.items.values():
        cat = item.category or "other"
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(item)
    
    # Show up to 4 items per category (was 3, now 4 for better coverage)
    for cat_name, items in categories.items():
        lines.append(f"{cat_name.title()}: " + ", ".join(
            item.name for item in items[:4] if not item.unavailable
        ))
    
    return "\n".join(lines)
