from __future__ import annotations

import asyncio
import base64
import json
import logging
from html import escape
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db import repo
from app.db.database import get_db
from app.services.menu_catalog import MenuCatalog
from app.services.twilio_media_outbound import push_assistant_speech
from app.services.twilio_media_turn import run_telephony_utterance
from app.services.twilio_utterance import UtteranceBuffer
from app.services.personaplex_bridge import (
    PersonaPlexSession,
    build_menu_prompt_from_catalog,
)
from app.services.twilio_mulaw import pcm16_tone_ms_to_mulaw

router = APIRouter(prefix="/telephony/twilio", tags=["telephony"])
logger = logging.getLogger(__name__)

# Silence frames for keepalive / padding (20 ms @ 8 kHz mu-law).
_TWILIO_MULAW_FRAME = 160


def _twiml(body: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>'


def _default_wait_message() -> str:
    return (
        '<Say voice="alice">Thanks for calling. Connecting you now.</Say>'
        '<Pause length="1"/>'
        '<Say voice="alice">If you hear silence, please hold while the voice agent joins.</Say>'
    )


def _ordering_greeting_twiml(*, restaurant_name: str) -> str:
    """Spoken before Media Stream connects — short intro so callers can speak quickly."""
    custom = (settings.twilio_voice_greeting or "").strip()
    if custom:
        welcome = escape(custom)
    else:
        name = (restaurant_name or "our restaurant").strip() or "our restaurant"
        welcome = escape(
            f"Thanks for calling {name}! "
            "Just tell me what you'd like to order, or say menu to hear our options. "
            "Go ahead after the tone."
        )
    return f'<Say voice="alice">{welcome}</Say><Pause length="1"/>'


def _public_https_origin_from_stream_url() -> str:
    """Derive https://host for TwiML <Play> URLs from the configured wss media URL."""
    raw = (settings.twilio_media_stream_url or "").strip()
    if not raw:
        return ""
    u = urlsplit(raw)
    if u.scheme == "wss" and u.netloc:
        return f"https://{u.netloc}"
    if u.scheme == "https" and u.netloc:
        return f"https://{u.netloc}"
    return ""


def _pre_connect_beep_twiml() -> str:
    """Short beep over HTTPS so the caller hears a real tone before the media stream."""
    origin = _public_https_origin_from_stream_url()
    if not origin:
        return ""
    beep_url = f"{origin}/telephony/twilio/assets/phone-beep.wav"
    return f'<Play>{escape(beep_url, quote=True)}</Play><Pause length="1"/>'


def _twilio_connect_stream_url() -> str:
    """
    Twilio Stream `url` must not include query strings — use <Parameter> for metadata.
    See: https://www.twilio.com/docs/voice/twiml/stream#url
    """
    raw = (settings.twilio_media_stream_url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    path = parts.path if parts.path else "/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _bridge_twiml(*, session_id: str, call_sid: str, restaurant_name: str) -> str:
    mode = (settings.twilio_bridge_mode or "say_only").strip().lower()
    if mode == "stream":
        stream_url = _twilio_connect_stream_url()
        if not stream_url:
            return (
                '<Say voice="alice">Sorry, voice bridge is not configured. Please call again later.</Say>'
                "<Hangup/>"
            )
        # Bidirectional <Connect><Stream>: Twilio default track is inbound_track; omit attribute
        # to match docs sample and avoid parser quirks.
        # timeout="600" keeps the stream open for 10 minutes (default is 30 seconds).
        
        # Add immediate greeting for PersonaPlex to mask warmup delay
        greeting_twiml = ""
        if _personaplex_enabled() and settings.twilio_pp_immediate_greeting:
            greeting_twiml = f'<Say voice="alice">Please hold, connecting you to {restaurant_name}.</Say>'
        
        stream_block = (
            f'<Connect timeout="600"><Stream url="{escape(stream_url, quote=True)}">'
            f'<Parameter name="session_id" value="{escape(session_id, quote=True)}" />'
            f'<Parameter name="call_sid" value="{escape(call_sid, quote=True)}" />'
            "</Stream></Connect>"
            "<Hangup/>"
        )
        if _personaplex_enabled():
            return greeting_twiml + stream_block
        return (
            _ordering_greeting_twiml(restaurant_name=restaurant_name)
            + _pre_connect_beep_twiml()
            + stream_block
        )

    if mode == "sip":
        if not settings.twilio_sip_uri:
            return (
                '<Say voice="alice">Sorry, transfer destination is not configured. Please call again later.</Say>'
                "<Hangup/>"
            )
        return _default_wait_message() + f"<Dial><Sip>{escape(settings.twilio_sip_uri)}</Sip></Dial>"

    return _default_wait_message()


@router.get("/debug-status")
def twilio_debug_status() -> dict:
    """Quick diagnostic: shows what STT/TTS/stream config the running instance sees."""
    import shutil
    import os

    stt = (settings.twilio_stream_stt_backend or "off").strip().lower()
    tts = (settings.twilio_stream_tts_backend or "auto").strip().lower()
    mode = (settings.twilio_bridge_mode or "say_only").strip().lower()
    media_url = (settings.twilio_media_stream_url or "").strip()
    beep_path = (settings.menu_path.parent / "phone_beep.wav").resolve()
    whisper_model = (settings.twilio_whisper_model or "base").strip()
    logic = (settings.logic_extractor or "rules").strip().lower()

    faster_whisper_available = False
    try:
        import faster_whisper  # noqa: F401
        faster_whisper_available = True
    except ImportError:
        pass

    stt_key_set = bool((settings.stt_api_key or "").strip())
    pp_enabled = _personaplex_enabled()
    return {
        "bridge_mode": mode,
        "media_stream_url": media_url,
        "personaplex_enabled": pp_enabled,
        "personaplex_ws_url": (settings.personaplex_ws_url or "").strip() if pp_enabled else "(disabled)",
        "personaplex_voice": settings.personaplex_voice if pp_enabled else "(disabled)",
        "twilio_pp_silence_keepalive": settings.twilio_pp_silence_keepalive if pp_enabled else "(n/a)",
        "twilio_pp_debug_tone_ms": settings.twilio_pp_debug_tone_ms,
        "personaplex_prompt_max_chars": settings.personaplex_prompt_max_chars,
        "stt_backend": stt,
        "stt_enabled": stt not in ("", "off", "none"),
        "stt_api_key_set": stt_key_set,
        "faster_whisper_installed": faster_whisper_available,
        "whisper_model": whisper_model,
        "tts_backend": tts,
        "tts_enabled": _tts_out_enabled() and not pp_enabled,
        "ffmpeg_on_path": shutil.which("ffmpeg") is not None,
        "espeak_on_path": shutil.which("espeak-ng") is not None or shutil.which("espeak") is not None,
        "beep_wav_exists": beep_path.is_file(),
        "logic_extractor": logic,
        "llm_base_url": (settings.llm_base_url or "").strip() if logic == "llm" else "(not used)",
        "env_stt_raw": os.environ.get("KITCHENCALL_TWILIO_STREAM_STT_BACKEND", "(not set)"),
        "utterance_max_ms": settings.twilio_utterance_max_ms,
        "utterance_silence_ms": settings.twilio_utterance_silence_ms,
        "utterance_rms_threshold": settings.twilio_utterance_rms_threshold,
    }


@router.get("/personaplex-probe")
async def personaplex_probe() -> dict:
    """Open a minimal PersonaPlex WebSocket and confirm the 0x00 handshake (no phone call required)."""
    import aiohttp

    if not _personaplex_enabled():
        return {"ok": False, "error": "KITCHENCALL_PERSONAPLEX_ENABLED is not set"}
    url = (settings.personaplex_ws_url or "").strip()
    if not url:
        return {"ok": False, "error": "KITCHENCALL_PERSONAPLEX_WS_URL is empty"}
    voice = (settings.personaplex_voice or "NATF2").strip()
    params = {"voice_prompt": voice, "text_prompt": "Short probe message."}
    try:
        to = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=to) as session:
            ws = await session.ws_connect(
                url,
                params=params,
                timeout=aiohttp.ClientWSTimeout(ws_close=15.0),
            )
            try:

                async def _first_binary_handshake() -> aiohttp.WSMessage:
                    while True:
                        msg = await ws.receive()
                        if msg.type == aiohttp.WSMsgType.BINARY and msg.data:
                            return msg
                        if msg.type in (
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.CLOSING,
                            aiohttp.WSMsgType.CLOSED,
                        ):
                            raise ConnectionError(
                                "PersonaPlex closed the WebSocket before sending binary "
                                "handshake (0x00). Check the PersonaPlex process logs, "
                                "`async with lock` contention, or voice prompt resolution."
                            )
                        if msg.type == aiohttp.WSMsgType.ERROR:
                            raise ConnectionError("PersonaPlex WebSocket error frame")
                        # TEXT / PING / etc. — keep reading until first binary frame
                        continue

                try:
                    msg = await asyncio.wait_for(_first_binary_handshake(), timeout=12.0)
                except asyncio.TimeoutError:
                    return {
                        "ok": False,
                        "error": (
                            "timeout waiting for binary handshake — start PersonaPlex on "
                            "8998 and ensure apps/personaplex local_web.py is current."
                        ),
                    }
                except ConnectionError as e:
                    return {"ok": False, "error": str(e)}
                tag = msg.data[0]
                return {
                    "ok": tag == 0,
                    "handshake_first_byte": tag,
                    "hint": "first byte must be 0 (handshake) before inbound audio",
                }
            finally:
                await ws.close()
    except aiohttp.WSServerHandshakeError as e:
        return {
            "ok": False,
            "error": f"WebSocket handshake failed (HTTP {e.status})",
            "detail": str(e),
            "hint": "PersonaPlex often returns 400 when voice_prompt file is missing (e.g. NATF2.pt).",
        }
    except aiohttp.ClientResponseError as e:
        return {
            "ok": False,
            "error": f"HTTP {e.status}",
            "detail": str(e.message) if getattr(e, "message", None) else str(e),
        }
    except aiohttp.ClientError as e:
        return {"ok": False, "error": f"connection failed: {e}"}
    except Exception as e:
        logger.exception("personaplex-probe failed")
        return {"ok": False, "error": str(e)}


@router.get("/assets/phone-beep.wav")
def twilio_phone_beep_asset() -> FileResponse:
    """Short tone Twilio fetches over HTTPS (before <Connect><Stream>)."""
    path = (settings.menu_path.parent / "phone_beep.wav").resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="phone_beep.wav missing")
    return FileResponse(path, media_type="audio/wav", filename="phone-beep.wav")


@router.get("/inbound")
@router.head("/inbound")
def twilio_inbound_get(
    CallSid: str = Query(default=""),
    From: str = Query(default=""),
    To: str = Query(default=""),
    db: Session = Depends(get_db),
) -> Response:
    """Handle GET/HEAD requests from Twilio.
    
    HEAD requests are for validation (return empty 200).
    GET requests with CallSid are actual calls (return TwiML).
    GET requests without CallSid are validation checks (return simple OK).
    """
    # HEAD request - return empty response for validation
    from fastapi import Request
    from starlette.requests import Request as StarletteRequest
    
    # For HEAD requests, return minimal response
    if CallSid and From and To:
        # Actual call via GET - treat like POST
        session = repo.create_session(db)
        room_name = f"kc-{session.id}"
        repo.upsert_twilio_call(
            db,
            call_sid=CallSid,
            session_id=session.id,
            from_number=From,
            to_number=To,
            room_name=room_name,
            status="inbound_received",
        )
        
        catalog = MenuCatalog.load(settings.menu_path)
        repo.append_transcript(
            db,
            session.id,
            role="call",
            text=(
                f"Phone call started — from {From or 'unknown'}, to {To or 'unknown'}. "
                f"Call SID {CallSid}."
            ),
            is_partial=False,
        )
        
        body = _bridge_twiml(
            session_id=session.id,
            call_sid=CallSid,
            restaurant_name=catalog.restaurant_name,
        )
        return Response(content=_twiml(body), media_type="application/xml")
    
    # Validation request - return simple OK
    return Response(content="OK", status_code=200)


@router.post("/inbound")
def twilio_inbound(
    CallSid: str = Form(...),
    From: str = Form(default=""),
    To: str = Form(default=""),
    db: Session = Depends(get_db),
) -> Response:
    """Maps inbound Twilio call SID to a KitchenCall session and returns TwiML."""
    session = repo.create_session(db)
    room_name = f"kc-{session.id}"
    repo.upsert_twilio_call(
        db,
        call_sid=CallSid,
        session_id=session.id,
        from_number=From,
        to_number=To,
        room_name=room_name,
        status="inbound_received",
    )

    catalog = MenuCatalog.load(settings.menu_path)
    repo.append_transcript(
        db,
        session.id,
        role="call",
        text=(
            f"Phone call started — from {From or 'unknown'}, to {To or 'unknown'}. "
            f"Call SID {CallSid}."
        ),
        is_partial=False,
    )

    body = _bridge_twiml(
        session_id=session.id,
        call_sid=CallSid,
        restaurant_name=catalog.restaurant_name,
    )
    return Response(content=_twiml(body), media_type="application/xml")


@router.post("/status")
def twilio_status_callback(
    CallSid: str = Form(...),
    CallStatus: str = Form(default="unknown"),
    db: Session = Depends(get_db),
) -> dict:
    row = repo.update_telephony_call_status(db, call_sid=CallSid, status=CallStatus)
    if row is None:
        # status callback can race before inbound route in some setups; keep idempotent
        return {"ok": True, "mapped": False}
    if repo.get_session_row(db, row.session_id):
        repo.append_transcript(
            db,
            row.session_id,
            role="call",
            text=f"Twilio call status: {CallStatus} (call {CallSid}).",
            is_partial=False,
        )
    return {"ok": True, "mapped": True, "session_id": row.session_id, "status": row.status}


@router.get("/calls")
def list_twilio_calls(db: Session = Depends(get_db), limit: int = 50) -> list[dict]:
    """Recent phone calls with full session timeline (transcript lines + timestamps) for the dashboard."""
    rows = repo.list_telephony_calls(db, limit=min(limit, 100))
    out: list[dict] = []
    for r in rows:
        tr = repo.list_transcripts(db, r.session_id)
        out.append(
            {
                "call_sid": r.call_sid,
                "session_id": r.session_id,
                "from_number": r.from_number,
                "to_number": r.to_number,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
                "timeline": [
                    {
                        "id": t.id,
                        "role": t.role,
                        "text": t.text,
                        "created_at": t.created_at.isoformat(),
                        "is_partial": t.is_partial,
                    }
                    for t in tr
                ],
            }
        )
    return out


@router.get("/calls/{call_sid}")
def get_twilio_call(call_sid: str, db: Session = Depends(get_db)) -> dict:
    row = repo.get_telephony_call_by_sid(db, call_sid)
    if row is None:
        return {"found": False}
    return {
        "found": True,
        "provider": row.provider,
        "call_sid": row.call_sid,
        "session_id": row.session_id,
        "from_number": row.from_number,
        "to_number": row.to_number,
        "room_name": row.room_name,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _personaplex_enabled() -> bool:
    return bool(settings.personaplex_enabled) and bool(
        (settings.personaplex_ws_url or "").strip()
    )


def _stt_enabled() -> bool:
    b = (settings.twilio_stream_stt_backend or "off").strip().lower()
    return b not in ("", "off", "none")


def _tts_out_enabled() -> bool:
    v = (settings.twilio_stream_tts_backend or "auto").strip().lower()
    if v in ("off", "none", ""):
        return False
    if v == "auto":
        return _stt_enabled()
    return v in ("on", "yes", "true", "ffmpeg", "say", "1")


@router.websocket("/media")
async def twilio_media_bridge(websocket: WebSocket) -> None:
    """
    Twilio Media Streams WebSocket handler.

    Two modes based on KITCHENCALL_PERSONAPLEX_ENABLED:

    **PersonaPlex mode (dual-loop)**:
      - Inbound audio → PersonaPlex (natural full-duplex voice)
      - Inbound audio → shadow STT pipeline (Whisper → cart updates, no TTS)
      - PersonaPlex output audio → Twilio (natural voice back to caller)

    **Legacy mode**:
      - Inbound audio → Whisper STT → process-turn → TTS → Twilio
    """
    await websocket.accept()
    call_sid = websocket.query_params.get("call_sid", "")
    session_hint = websocket.query_params.get("session_id", "")
    logger.info(
        "twilio_media websocket accepted call_sid=%s session_hint=%s",
        call_sid or "unknown",
        session_hint or "none",
    )
    media_chunks = 0
    stt_turns = 0
    mapped_session_id = ""
    stream_sid = ""
    pp_mode = _personaplex_enabled()

    from app.db.database import get_session_factory
    from collections import deque

    db = get_session_factory()()
    buffer = UtteranceBuffer(
        silence_ms=settings.twilio_utterance_silence_ms,
        max_ms=settings.twilio_utterance_max_ms,
        rms_threshold=settings.twilio_utterance_rms_threshold,
    )
    stt_on = _stt_enabled()
    tts_on = _tts_out_enabled() and not pp_mode
    logger.info(
        "twilio_media config: personaplex=%s stt_on=%s tts_on=%s backend=%s",
        pp_mode, stt_on, tts_on, settings.twilio_stream_stt_backend,
    )

    pp_session: PersonaPlexSession | None = None
    silence_task: asyncio.Task | None = None
    # PersonaPlex often speaks before Twilio sends `start` (streamSid). Buffer until then.
    _pp_audio_pending: deque[bytes] = deque(maxlen=600)
    # Bidirectional Media Streams: Twilio expects a `mark` after outbound `media` for playback flow.
    _twilio_pp_mark_seq: int = 0
    _pp_packets_sent: int = 0
    # Interrupt detection state (no type hints - will be nonlocal)
    _customer_is_speaking = False
    _last_customer_audio_time = 0.0

    async def _emit_pp_mulaw_to_twilio(mulaw: bytes) -> None:
        """Send PersonaPlex mu-law to Twilio: one `media` + one `mark` per chunk.

        Twilio allows any payload size; flooding tiny frames + marks can stall playback.
        """
        nonlocal _twilio_pp_mark_seq
        if not stream_sid or not mulaw:
            return
        payload = base64.b64encode(mulaw).decode("ascii")
        msg = json.dumps(
            {"event": "media", "streamSid": stream_sid, "media": {"payload": payload}}
        )
        try:
            await websocket.send_text(msg)
        except Exception:
            logger.warning(
                "twilio_media failed to send outbound media stream_sid=%s bytes=%d",
                stream_sid[:8] if stream_sid else "",
                len(mulaw),
                exc_info=True,
            )
            return
        _twilio_pp_mark_seq += 1
        try:
            await websocket.send_text(
                json.dumps(
                    {
                        "event": "mark",
                        "streamSid": stream_sid,
                        "mark": {"name": f"kc_pp_{_twilio_pp_mark_seq}"},
                    }
                )
            )
        except Exception:
            logger.warning(
                "twilio_media failed to send mark after media stream_sid=%s",
                stream_sid[:8] if stream_sid else "",
                exc_info=True,
            )

    async def _flush_pp_audio_pending() -> None:
        if not stream_sid or not _pp_audio_pending:
            return
        n = len(_pp_audio_pending)
        logger.info(
            "twilio_media flushing %d PersonaPlex mu-law blocks buffered before streamSid",
            n,
        )
        while _pp_audio_pending:
            await _emit_pp_mulaw_to_twilio(_pp_audio_pending.popleft())

    async def _send_pp_audio_to_twilio(mulaw: bytes) -> None:
        """Callback: PersonaPlex decoded audio → Twilio as mu-law media frames."""
        nonlocal _pp_packets_sent
        if not stream_sid:
            _pp_audio_pending.append(mulaw)
            return
        
        _pp_packets_sent += 1
        if _pp_packets_sent % 100 == 1:
            logger.info("PersonaPlex → Twilio: packet #%d (%d bytes)", _pp_packets_sent, len(mulaw))
        await _emit_pp_mulaw_to_twilio(mulaw)

    async def _send_silence_keepalive() -> None:
        """Send mu-law silence frames to Twilio every 100ms to keep the stream alive
        until PersonaPlex sends real audio (handshake may arrive before model output)."""
        nonlocal _twilio_pp_mark_seq
        _SILENCE_CHUNK = b"\xFF" * 160  # 20ms of mu-law digital silence
        try:
            while (
                not pp_session
                or not pp_session.outbound_audio_started.is_set()
            ):
                if not stream_sid:
                    await asyncio.sleep(0.1)
                    continue
                payload = base64.b64encode(_SILENCE_CHUNK).decode("ascii")
                msg = json.dumps(
                    {"event": "media", "streamSid": stream_sid, "media": {"payload": payload}}
                )
                try:
                    await websocket.send_text(msg)
                    _twilio_pp_mark_seq += 1
                    await websocket.send_text(
                        json.dumps(
                            {
                                "event": "mark",
                                "streamSid": stream_sid,
                                "mark": {"name": f"kc_fill_{_twilio_pp_mark_seq}"},
                            }
                        )
                    )
                except Exception:
                    logger.warning("twilio_media silence keepalive send failed", exc_info=True)
                    return
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        logger.info("silence keepalive done — PersonaPlex ready")

    pp_text_fragments: list[str] = []

    def _on_pp_text(token: str) -> None:
        pp_text_fragments.append(token)

    try:
        if call_sid:
            row = repo.get_telephony_call_by_sid(db, call_sid)
            if row is not None:
                mapped_session_id = row.session_id
                repo.update_telephony_call_status(db, call_sid=call_sid, status="stream_connected")
        if not mapped_session_id:
            mapped_session_id = session_hint

        if mapped_session_id and repo.get_session_row(db, mapped_session_id):
            mode_label = "personaplex" if pp_mode else ("stt" if stt_on else "passive")
            repo.append_transcript(
                db,
                mapped_session_id,
                role="system",
                text=f"twilio_stream_connected call_sid={call_sid or 'unknown'} mode={mode_label}",
                is_partial=False,
            )

        # --- PersonaPlex setup ---
        if pp_mode:
            menu_prompt = build_menu_prompt_from_catalog(settings.menu_path)
            pp_session = PersonaPlexSession(
                on_mulaw_out=_send_pp_audio_to_twilio,
                on_text_token=_on_pp_text,
                menu_prompt=menu_prompt,
            )
            pp_ok = await pp_session.connect()
            if not pp_ok:
                logger.error("personaplex connection failed — falling back to legacy STT/TTS")
                pp_mode = False
                pp_session = None
                tts_on = _tts_out_enabled()
            else:
                logger.info("personaplex connected for call_sid=%s", call_sid)

        if pp_mode and pp_session and settings.twilio_pp_silence_keepalive:
            silence_task = asyncio.create_task(_send_silence_keepalive())

        # --- Shadow STT pipeline (runs in both modes) ---
        pending_task: asyncio.Task | None = None
        utterance_queue: deque[bytes] = deque(maxlen=3)

        def _is_silence(pcm_done: bytes) -> bool:
            from app.services.twilio_mulaw import rms_pcm16_le
            rms = rms_pcm16_le(pcm_done)
            if rms < 180.0:
                logger.info("twilio_media skipping silent buffer rms=%.0f len=%d", rms, len(pcm_done))
                return True
            return False

        async def _handle_utterance_pcm(pcm_done: bytes) -> None:
            """Shadow pipeline: STT → process_turn for cart updates.
            In PersonaPlex mode, TTS reply is suppressed (PersonaPlex handles voice).
            """
            nonlocal stt_turns
            logger.info(
                "twilio_media utterance detected: %d bytes (%.1f s) call_sid=%s session=%s",
                len(pcm_done), len(pcm_done) / (8000 * 2),
                call_sid, mapped_session_id,
            )
            try:
                reply = await asyncio.to_thread(
                    run_telephony_utterance, mapped_session_id, pcm_done
                )
            except Exception:
                logger.exception(
                    "twilio_media utterance handler failed call_sid=%s",
                    call_sid or "unknown",
                )
                return
            stt_turns += 1
            logger.info(
                "twilio_media STT turn #%d reply=%s call_sid=%s",
                stt_turns,
                repr(reply[:120]) if reply else "(empty)",
                call_sid,
            )
            if reply and stream_sid and tts_on and not pp_mode:
                try:
                    await push_assistant_speech(websocket, stream_sid, reply)
                except Exception:
                    logger.exception(
                        "twilio_media TTS push failed call_sid=%s",
                        call_sid or "unknown",
                    )

        async def _drain_queue() -> None:
            nonlocal pending_task
            while utterance_queue:
                pcm = utterance_queue.popleft()
                await _handle_utterance_pcm(pcm)
            pending_task = None

        def _fire_utterance(pcm_done: bytes) -> None:
            nonlocal pending_task
            if _is_silence(pcm_done):
                return
            if pending_task and not pending_task.done():
                utterance_queue.append(pcm_done)
                logger.info(
                    "twilio_media queued utterance (queue=%d) — previous STT still running",
                    len(utterance_queue),
                )
                return
            utterance_queue.append(pcm_done)
            pending_task = asyncio.create_task(_drain_queue())

        # --- Main event loop ---
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue
            try:
                event = msg.get("event")
                if event == "connected":
                    logger.info("twilio_media 'connected' event received")
                elif event == "start":
                    start = msg.get("start") or {}
                    call_sid = start.get("callSid", call_sid)
                    custom = (start.get("customParameters") or {}) if isinstance(start, dict) else {}
                    stream_sid = (
                        start.get("streamSid", "")
                        or (custom.get("streamSid", "") if isinstance(custom, dict) else "")
                        or msg.get("streamSid", "")
                        or stream_sid
                    )
                    if not mapped_session_id and isinstance(custom, dict):
                        mapped_session_id = custom.get("session_id", "") or mapped_session_id
                    if call_sid:
                        row = repo.get_telephony_call_by_sid(db, call_sid)
                        if row is not None:
                            mapped_session_id = row.session_id
                            repo.update_telephony_call_status(
                                db, call_sid=call_sid, status="stream_started"
                            )
                    logger.info(
                        "twilio_media 'start' event: call_sid=%s stream_sid=%s session=%s custom=%s",
                        call_sid, stream_sid, mapped_session_id, custom,
                    )
                    if mapped_session_id and repo.get_session_row(db, mapped_session_id):
                        repo.append_transcript(
                            db,
                            mapped_session_id,
                            role="system",
                            text=(
                                f"twilio_stream_started call_sid={call_sid} "
                                f"stream_sid={stream_sid} mode={'personaplex' if pp_mode else 'legacy'}"
                            ),
                            is_partial=False,
                        )
                    if pp_mode and stream_sid:
                        await _flush_pp_audio_pending()
                        if settings.twilio_pp_debug_tone_ms > 0:
                            tone = pcm16_tone_ms_to_mulaw(
                                duration_ms=float(settings.twilio_pp_debug_tone_ms)
                            )
                            logger.info(
                                "twilio_media playing debug tone %d ms",
                                settings.twilio_pp_debug_tone_ms,
                            )
                            await _emit_pp_mulaw_to_twilio(tone)
                elif event == "media":
                    media_chunks += 1
                    if media_chunks in (1, 50, 200, 500):
                        logger.info(
                            "twilio_media chunk #%d call_sid=%s pp=%s stt=%s session=%s",
                            media_chunks, call_sid, pp_mode, stt_on, mapped_session_id,
                        )
                    media = msg.get("media") or {}
                    trk = media.get("track", "inbound")
                    # Twilio uses `inbound` / `outbound` in docs; some legs send `inbound_track`.
                    if trk in ("outbound", "outbound_track"):
                        continue
                    if trk not in ("inbound", "inbound_track", "", None):
                        logger.warning("twilio_media skipping unknown media track=%r", trk)
                        continue
                    payload = media.get("payload")
                    if not isinstance(payload, str):
                        continue
                    try:
                        mulaw = base64.b64decode(payload)
                    except Exception:
                        continue

                    if pp_mode and pp_session and pp_session.is_connected:
                        pp_session.send_mulaw(mulaw)
                    # Shadow STT disabled in PersonaPlex mode to avoid CPU contention
                    elif stt_on and mapped_session_id:
                        pcm_done = buffer.add_mulaw(mulaw)
                        if pcm_done:
                            _fire_utterance(pcm_done)

                elif event == "stop":
                    logger.info("twilio_media 'stop' event received call_sid=%s", call_sid or "unknown")
                    if call_sid:
                        repo.update_telephony_call_status(
                            db, call_sid=call_sid, status="stream_stopped"
                        )
                    # Shadow STT disabled in PersonaPlex mode
                    if stt_on and mapped_session_id and not pp_mode:
                        pcm_done = buffer.flush()
                        if pcm_done:
                            _fire_utterance(pcm_done)
                    break
            except Exception:
                logger.exception(
                    "twilio_media message handling failed call_sid=%s", call_sid or "unknown"
                )
    except WebSocketDisconnect:
        logger.info("twilio_media WebSocketDisconnect call_sid=%s", call_sid or "unknown")
        if stt_on and mapped_session_id:
            pcm_done = buffer.flush()
            if pcm_done:
                _fire_utterance(pcm_done)
    except Exception:
        logger.exception(
            "twilio_media UNHANDLED exception call_sid=%s session=%s media_chunks=%d",
            call_sid or "unknown", mapped_session_id or "none", media_chunks,
        )
    finally:
        if silence_task and not silence_task.done():
            silence_task.cancel()
        if pp_session:
            logger.info("personaplex closing session call_sid=%s", call_sid or "unknown")
            pp_text = "".join(pp_text_fragments).strip()
            if pp_text and mapped_session_id and repo.get_session_row(db, mapped_session_id):
                repo.append_transcript(
                    db,
                    mapped_session_id,
                    role="assistant",
                    text=f"[PersonaPlex voice] {pp_text[:2000]}",
                    is_partial=False,
                )
            await pp_session.close()
        if pending_task and not pending_task.done():
            logger.info("twilio_media waiting for final STT task to complete…")
            try:
                await asyncio.wait_for(pending_task, timeout=30.0)
            except (asyncio.TimeoutError, Exception):
                logger.warning("twilio_media final STT task timed out or failed")
        if mapped_session_id and repo.get_session_row(db, mapped_session_id):
            repo.append_transcript(
                db,
                mapped_session_id,
                role="system",
                text=(
                    f"twilio_stream_disconnected call_sid={call_sid or 'unknown'} "
                    f"media_chunks={media_chunks} stt_turns={stt_turns} "
                    f"mode={'personaplex' if pp_mode else 'legacy'}"
                ),
                is_partial=False,
            )
        db.close()
        logger.info(
            "twilio_media handler exiting call_sid=%s session=%s chunks=%d turns=%d mode=%s",
            call_sid or "unknown", mapped_session_id or "none", media_chunks, stt_turns,
            "personaplex" if pp_mode else "legacy",
        )
