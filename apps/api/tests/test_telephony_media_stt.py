from __future__ import annotations

import asyncio
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


async def _immediate_to_thread(fn, /, *args, **kwargs):
    return fn(*args, **kwargs)


class _StubUtteranceBuffer:
    """Return one synthetic PCM chunk on first media frame so STT runs once."""

    def __init__(self, **kwargs) -> None:
        self._n = 0

    def add_mulaw(self, mulaw: bytes) -> bytes | None:
        self._n += 1
        if self._n == 1:
            return b"\x00\x10" * 8000
        return None

    def flush(self) -> bytes | None:
        return None

    def reset(self) -> None:
        self._n = 0


async def _noop_push(*_a, **_k) -> None:
    return None


def test_media_stream_with_stt_runs_process_turn(monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "to_thread", _immediate_to_thread)
    monkeypatch.setattr("app.api.routes_telephony.UtteranceBuffer", _StubUtteranceBuffer)
    monkeypatch.setattr(
        "app.services.twilio_media_turn.transcribe_pcm16_8k",
        lambda pcm: "Coke",
    )
    monkeypatch.setattr(settings, "twilio_stream_stt_backend", "faster_whisper", raising=False)
    monkeypatch.setattr(settings, "twilio_stream_tts_backend", "off", raising=False)
    monkeypatch.setattr("app.api.routes_telephony.push_assistant_speech", _noop_push)

    client = TestClient(app)
    client.post(
        "/telephony/twilio/inbound",
        data={"CallSid": "CASTTST1", "From": "+10000000001", "To": "+10000000002"},
    )
    mapped = client.get("/telephony/twilio/calls/CASTTST1").json()
    session_id = mapped["session_id"]

    with client.websocket_connect(f"/telephony/twilio/media?call_sid=CASTTST1&session_id={session_id}") as ws:
        ws.send_json({"event": "start", "start": {"callSid": "CASTTST1"}})
        ws.send_json({"event": "media", "media": {"track": "inbound", "payload": "AA=="}})
        ws.send_json({"event": "stop"})

    session = client.get(f"/sessions/{session_id}").json()
    user_lines = [t["text"] for t in session["transcript"] if t["role"] == "user"]
    assert "Coke" in user_lines
    sys_lines = [t["text"] for t in session["transcript"] if t["role"] == "system"]
    assert any("stt_turns=1" in t for t in sys_lines)


def test_media_stream_yes_while_confirming_finalizes_order(monkeypatch) -> None:
    """Phone STT 'yes' in confirming state saves order (same as POST /finalize)."""
    monkeypatch.setattr(settings, "logic_extractor", "rules", raising=False)
    monkeypatch.setattr(asyncio, "to_thread", _immediate_to_thread)
    monkeypatch.setattr("app.api.routes_telephony.UtteranceBuffer", _StubUtteranceBuffer)
    monkeypatch.setattr(
        "app.services.twilio_media_turn.transcribe_pcm16_8k",
        lambda pcm: "yes",
    )
    monkeypatch.setattr(settings, "twilio_stream_stt_backend", "faster_whisper", raising=False)
    monkeypatch.setattr(settings, "twilio_stream_tts_backend", "off", raising=False)
    monkeypatch.setattr("app.api.routes_telephony.push_assistant_speech", _noop_push)

    client = TestClient(app)
    client.post(
        "/telephony/twilio/inbound",
        data={"CallSid": "CASTFIN1", "From": "+10000000001", "To": "+10000000002"},
    )
    mapped = client.get("/telephony/twilio/calls/CASTFIN1").json()
    session_id = mapped["session_id"]

    for text in (
        "large pepperoni for pickup",
        "garlic knots",
        "Coke",
        "name is Alex",
        "phone is 555-123-4567",
        "that's all",
    ):
        r = client.post(f"/sessions/{session_id}/process-turn", json={"text": text})
        assert r.status_code == 200, (text, r.status_code, r.text)

    assert client.get(f"/sessions/{session_id}").json()["cart"]["metadata"]["status"] == "confirming"

    with client.websocket_connect(
        f"/telephony/twilio/media?call_sid=CASTFIN1&session_id={session_id}"
    ) as ws:
        ws.send_json({"event": "start", "start": {"callSid": "CASTFIN1"}})
        ws.send_json({"event": "media", "media": {"track": "inbound", "payload": "AA=="}})
        ws.send_json({"event": "stop"})

    session = client.get(f"/sessions/{session_id}").json()
    assert session["cart"]["metadata"]["status"] == "completed"
    orders = client.get("/orders").json()
    assert any(o["session_id"] == session_id for o in orders)


def test_mulaw_decode_non_empty() -> None:
    from app.services.twilio_mulaw import mulaw_payload_to_pcm16_le, rms_pcm16_le

    payload = bytes(range(0, 256, 3))
    pcm = mulaw_payload_to_pcm16_le(payload)
    assert len(pcm) == len(payload) * 2
    assert rms_pcm16_le(pcm) >= 0
