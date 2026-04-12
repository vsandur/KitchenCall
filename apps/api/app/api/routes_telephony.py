from __future__ import annotations

import asyncio
import base64
import json
import logging
from html import escape
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db import repo
from app.db.database import get_db
from app.services.menu_catalog import MenuCatalog
from app.services.twilio_media_outbound import push_assistant_speech
from app.services.twilio_media_turn import run_telephony_utterance
from app.services.twilio_utterance import UtteranceBuffer

router = APIRouter(prefix="/telephony/twilio", tags=["telephony"])
logger = logging.getLogger(__name__)


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
        # Bidirectional <Connect><Stream> may only use inbound_track (not both_tracks).
        # Outbound agent audio is sent as WebSocket media messages, not via track=.
        track = "inbound_track"
        return (
            _ordering_greeting_twiml(restaurant_name=restaurant_name)
            + _pre_connect_beep_twiml()
            + (
                f'<Connect><Stream url="{escape(stream_url, quote=True)}" track="{escape(track, quote=True)}">'
                f'<Parameter name="session_id" value="{escape(session_id, quote=True)}" />'
                f'<Parameter name="call_sid" value="{escape(call_sid, quote=True)}" />'
                "</Stream></Connect>"
            )
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
    return {
        "bridge_mode": mode,
        "media_stream_url": media_url,
        "stt_backend": stt,
        "stt_enabled": stt not in ("", "off", "none"),
        "stt_api_key_set": stt_key_set,
        "faster_whisper_installed": faster_whisper_available,
        "whisper_model": whisper_model,
        "tts_backend": tts,
        "tts_enabled": _tts_out_enabled(),
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


@router.get("/assets/phone-beep.wav")
def twilio_phone_beep_asset() -> FileResponse:
    """Short tone Twilio fetches over HTTPS (before <Connect><Stream>)."""
    path = (settings.menu_path.parent / "phone_beep.wav").resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="phone_beep.wav missing")
    return FileResponse(path, media_type="audio/wav", filename="phone-beep.wav")


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
    Twilio Media Streams WebSocket: maps lifecycle to sessions; optionally decodes mu-law,
    segments utterances, runs STT, and calls the same process-turn path as the dashboard.
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

    from app.db.database import get_session_factory
    from collections import deque

    db = get_session_factory()()
    buffer = UtteranceBuffer(
        silence_ms=settings.twilio_utterance_silence_ms,
        max_ms=settings.twilio_utterance_max_ms,
        rms_threshold=settings.twilio_utterance_rms_threshold,
    )
    stt_on = _stt_enabled()
    tts_on = _tts_out_enabled()
    logger.info(
        "twilio_media config: stt_on=%s tts_on=%s backend=%s whisper_model=%s rms_threshold=%s",
        stt_on, tts_on,
        settings.twilio_stream_stt_backend,
        settings.twilio_whisper_model,
        settings.twilio_utterance_rms_threshold,
    )

    try:
        if call_sid:
            row = repo.get_telephony_call_by_sid(db, call_sid)
            if row is not None:
                mapped_session_id = row.session_id
                repo.update_telephony_call_status(db, call_sid=call_sid, status="stream_connected")
        if not mapped_session_id:
            mapped_session_id = session_hint

        if mapped_session_id and repo.get_session_row(db, mapped_session_id):
            extra = " stt=on" if stt_on else " stt=off"
            tts = " tts=on" if tts_on else " tts=off"
            repo.append_transcript(
                db,
                mapped_session_id,
                role="system",
                text=f"twilio_stream_connected call_sid={call_sid or 'unknown'}{extra}{tts}",
                is_partial=False,
            )

        pending_task: asyncio.Task | None = None
        utterance_queue: deque[bytes] = deque(maxlen=3)

        def _is_silence(pcm_done: bytes) -> bool:
            """Skip buffers that are pure silence (below mu-law baseline)."""
            from app.services.twilio_mulaw import rms_pcm16_le
            rms = rms_pcm16_le(pcm_done)
            if rms < 180.0:
                logger.info("twilio_media skipping silent buffer rms=%.0f len=%d", rms, len(pcm_done))
                return True
            return False

        async def _handle_utterance_pcm(pcm_done: bytes) -> None:
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
            if reply and stream_sid and tts_on:
                try:
                    await push_assistant_speech(websocket, stream_sid, reply)
                except Exception:
                    logger.exception(
                        "twilio_media TTS push failed call_sid=%s",
                        call_sid or "unknown",
                    )

        async def _drain_queue() -> None:
            """Process one utterance, then drain any queued ones sequentially."""
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
                                f"stream_sid={stream_sid} stt={'on' if stt_on else 'off'} "
                                f"tts={'on' if tts_on else 'off'}"
                            ),
                            is_partial=False,
                        )
                elif event == "media":
                    media_chunks += 1
                    if media_chunks in (1, 50, 200, 500):
                        logger.info(
                            "twilio_media chunk #%d call_sid=%s stt_on=%s session=%s",
                            media_chunks, call_sid, stt_on, mapped_session_id,
                        )
                    if stt_on and mapped_session_id:
                        media = msg.get("media") or {}
                        trk = media.get("track", "inbound")
                        if trk == "outbound":
                            continue
                        if trk not in ("inbound", "", None):
                            continue
                        payload = media.get("payload")
                        if not isinstance(payload, str):
                            continue
                        try:
                            mulaw = base64.b64decode(payload)
                        except Exception:
                            continue
                        pcm_done = buffer.add_mulaw(mulaw)
                        if pcm_done:
                            _fire_utterance(pcm_done)
                elif event == "stop":
                    if call_sid:
                        repo.update_telephony_call_status(
                            db, call_sid=call_sid, status="stream_stopped"
                        )
                    if stt_on and mapped_session_id:
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
                    f"media_chunks={media_chunks} stt_turns={stt_turns}"
                ),
                is_partial=False,
            )
        db.close()
        logger.info(
            "twilio_media handler exiting call_sid=%s session=%s chunks=%d turns=%d",
            call_sid or "unknown", mapped_session_id or "none", media_chunks, stt_turns,
        )
