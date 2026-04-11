from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def test_twilio_inbound_maps_call_to_session_and_returns_twiml() -> None:
    client = TestClient(app)
    r = client.post(
        "/telephony/twilio/inbound",
        data={
            "CallSid": "CA1234567890",
            "From": "+14155550123",
            "To": "+14155550999",
        },
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    assert "<Response>" in r.text
    assert "Connecting you now" in r.text

    mapped = client.get("/telephony/twilio/calls/CA1234567890")
    assert mapped.status_code == 200
    body = mapped.json()
    assert body["found"] is True
    assert body["provider"] == "twilio"
    assert body["call_sid"] == "CA1234567890"
    assert body["session_id"]
    assert body["room_name"].startswith("kc-")
    assert body["status"] == "inbound_received"


def test_twilio_status_updates_existing_call() -> None:
    client = TestClient(app)
    client.post(
        "/telephony/twilio/inbound",
        data={"CallSid": "CASTATUS1", "From": "+10000000001", "To": "+10000000002"},
    )
    r = client.post("/telephony/twilio/status", data={"CallSid": "CASTATUS1", "CallStatus": "completed"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["mapped"] is True
    assert body["status"] == "completed"

    mapped = client.get("/telephony/twilio/calls/CASTATUS1").json()
    assert mapped["status"] == "completed"


def test_twilio_status_for_unknown_call_is_idempotent() -> None:
    client = TestClient(app)
    r = client.post("/telephony/twilio/status", data={"CallSid": "UNKNOWN", "CallStatus": "ringing"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "mapped": False}


def test_twilio_inbound_stream_mode_includes_connect_stream() -> None:
    client = TestClient(app)
    with patch("app.api.routes_telephony.settings.twilio_bridge_mode", "stream"), patch(
        "app.api.routes_telephony.settings.twilio_media_stream_url",
        "wss://example.test/twilio-media",
    ):
        r = client.post(
            "/telephony/twilio/inbound",
            data={"CallSid": "CASTREAM1", "From": "+10000000001", "To": "+10000000002"},
        )
    assert r.status_code == 200
    assert "<Connect><Stream" in r.text
    assert 'track="both_tracks"' in r.text
    assert "session_id=" in r.text
    assert "call_sid=CASTREAM1" in r.text


def test_twilio_inbound_sip_mode_includes_dial_sip() -> None:
    client = TestClient(app)
    with patch("app.api.routes_telephony.settings.twilio_bridge_mode", "sip"), patch(
        "app.api.routes_telephony.settings.twilio_sip_uri",
        "sip:voice-agent@example.sip.twilio.com",
    ):
        r = client.post(
            "/telephony/twilio/inbound",
            data={"CallSid": "CASIP1", "From": "+10000000001", "To": "+10000000002"},
        )
    assert r.status_code == 200
    assert "<Dial><Sip>sip:voice-agent@example.sip.twilio.com</Sip></Dial>" in r.text


def test_twilio_media_websocket_updates_status_and_transcript() -> None:
    client = TestClient(app)
    client.post(
        "/telephony/twilio/inbound",
        data={"CallSid": "CAMEDIA1", "From": "+10000000001", "To": "+10000000002"},
    )
    mapped = client.get("/telephony/twilio/calls/CAMEDIA1").json()
    session_id = mapped["session_id"]

    with client.websocket_connect(f"/telephony/twilio/media?call_sid=CAMEDIA1&session_id={session_id}") as ws:
        ws.send_json({"event": "start", "start": {"callSid": "CAMEDIA1"}})
        ws.send_json({"event": "media", "media": {"payload": "AAAA"}})
        ws.send_json({"event": "media", "media": {"payload": "BBBB"}})
        ws.send_json({"event": "stop"})

    mapped_after = client.get("/telephony/twilio/calls/CAMEDIA1").json()
    assert mapped_after["status"] == "stream_stopped"

    session = client.get(f"/sessions/{session_id}").json()
    texts = [t["text"] for t in session["transcript"] if t["role"] == "system"]
    assert any("twilio_stream_connected" in t and "stt=off" in t and "tts=off" in t for t in texts)
    assert any(
        "twilio_stream_disconnected" in t and "media_chunks=2" in t and "stt_turns=0" in t for t in texts
    )
