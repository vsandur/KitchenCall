from __future__ import annotations

import asyncio
import base64
import json
from html import escape

from fastapi import APIRouter, Depends, Form, Response, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.config import settings
from app.db import repo
from app.db.database import get_db
from app.services.twilio_media_outbound import push_assistant_speech
from app.services.twilio_media_turn import run_telephony_utterance
from app.services.twilio_utterance import UtteranceBuffer

router = APIRouter(prefix="/telephony/twilio", tags=["telephony"])


def _twiml(body: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>'


def _default_wait_message() -> str:
    return (
        '<Say voice="alice">Thanks for calling. Connecting you now.</Say>'
        '<Pause length="1"/>'
        '<Say voice="alice">If you hear silence, please hold while the voice agent joins.</Say>'
    )


def _ordering_greeting_twiml() -> str:
    """Spoken before Media Stream connects — real PSTN ordering intro."""
    base = (settings.twilio_voice_greeting or "").strip()
    if not base:
        base = "Thanks for calling. I'm your phone ordering assistant."
    hint = (
        " After the tone, speak clearly. For example: large pepperoni pizza for pickup, "
        "or tell me if you want delivery."
    )
    full = base + hint
    return f'<Say voice="alice">{escape(full)}</Say><Pause length="1"/>'


def _bridge_twiml(*, session_id: str, call_sid: str) -> str:
    mode = (settings.twilio_bridge_mode or "say_only").strip().lower()
    if mode == "stream":
        if not settings.twilio_media_stream_url:
            return (
                '<Say voice="alice">Sorry, voice bridge is not configured. Please call again later.</Say>'
                "<Hangup/>"
            )
        sep = "&" if "?" in settings.twilio_media_stream_url else "?"
        stream_url = f"{settings.twilio_media_stream_url}{sep}session_id={session_id}&call_sid={call_sid}"
        track = (settings.twilio_stream_track or "inbound_track").strip()
        if track not in ("inbound_track", "outbound_track", "both_tracks"):
            track = "inbound_track"
        return (
            _ordering_greeting_twiml()
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

    body = _bridge_twiml(session_id=session.id, call_sid=CallSid)
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
    return {"ok": True, "mapped": True, "session_id": row.session_id, "status": row.status}


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
    media_chunks = 0
    stt_turns = 0
    mapped_session_id = ""
    stream_sid = ""

    from app.db.database import get_session_factory

    db = get_session_factory()()
    buffer = UtteranceBuffer(
        silence_ms=settings.twilio_utterance_silence_ms,
        max_ms=settings.twilio_utterance_max_ms,
        rms_threshold=settings.twilio_utterance_rms_threshold,
    )
    stt_on = _stt_enabled()

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
            tts = " tts=on" if _tts_out_enabled() else " tts=off"
            repo.append_transcript(
                db,
                mapped_session_id,
                role="system",
                text=f"twilio_stream_connected call_sid={call_sid or 'unknown'}{extra}{tts}",
                is_partial=False,
            )

        async def _handle_utterance_pcm(pcm_done: bytes) -> None:
            nonlocal stt_turns
            try:
                reply = await asyncio.to_thread(run_telephony_utterance, mapped_session_id, pcm_done)
            except Exception:
                logger.exception(
                    "twilio_media utterance handler failed call_sid=%s", call_sid or "unknown"
                )
                buffer.reset()
                return
            stt_turns += 1
            buffer.reset()
            if reply and stream_sid and _tts_out_enabled():
                try:
                    await push_assistant_speech(websocket, stream_sid, reply)
                except Exception:
                    logger.exception(
                        "twilio_media TTS push failed call_sid=%s", call_sid or "unknown"
                    )
            buffer.reset()

        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            event = msg.get("event")
            if event == "start":
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
                        repo.update_telephony_call_status(db, call_sid=call_sid, status="stream_started")
            elif event == "media":
                media_chunks += 1
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
                        await _handle_utterance_pcm(pcm_done)
            elif event == "stop":
                if call_sid:
                    repo.update_telephony_call_status(db, call_sid=call_sid, status="stream_stopped")
                if stt_on and mapped_session_id:
                    pcm_done = buffer.flush()
                    if pcm_done:
                        await _handle_utterance_pcm(pcm_done)
                break
    except WebSocketDisconnect:
        if stt_on and mapped_session_id:
            pcm_done = buffer.flush()
            if pcm_done:
                await _handle_utterance_pcm(pcm_done)
    finally:
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
