from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def test_twilio_inbound_maps_call_to_session_and_returns_twiml() -> None:
    client = TestClient(app)
    with patch("app.api.routes_telephony.settings.personaplex_enabled", False):
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
    assert "<Say" in r.text

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
    with patch("app.api.routes_telephony.settings.personaplex_enabled", False), patch(
        "app.api.routes_telephony.settings.twilio_bridge_mode", "stream"
    ), patch(
        "app.api.routes_telephony.settings.twilio_media_stream_url",
        "wss://example.test/twilio-media",
    ):
        r = client.post(
            "/telephony/twilio/inbound",
            data={"CallSid": "CASTREAM1", "From": "+10000000001", "To": "+10000000002"},
        )
    assert r.status_code == 200
    assert "<Connect><Stream" in r.text
    assert 'Stream url="wss://example.test/twilio-media"' in r.text
    assert "https://example.test/telephony/twilio/assets/phone-beep.wav" in r.text
    assert "<Play>" in r.text
    assert 'Parameter name="session_id"' in r.text
    assert 'Parameter name="call_sid"' in r.text
    assert 'value="CASTREAM1"' in r.text


def test_twilio_phone_beep_asset_served() -> None:
    client = TestClient(app)
    r = client.get("/telephony/twilio/assets/phone-beep.wav")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("audio/")
    assert len(r.content) > 100


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


def test_list_twilio_calls_includes_call_timeline() -> None:
    client = TestClient(app)
    client.post(
        "/telephony/twilio/inbound",
        data={"CallSid": "CALIST99", "From": "+15551110001", "To": "+15551110002"},
    )
    r = client.get("/telephony/twilio/calls?limit=20")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    row = next((c for c in data if c.get("call_sid") == "CALIST99"), None)
    assert row is not None
    assert row["from_number"] == "+15551110001"
    assert "timeline" in row
    assert any(e.get("role") == "call" and "Phone call started" in e.get("text", "") for e in row["timeline"])
    assert all("created_at" in e for e in row["timeline"])


def test_twilio_media_websocket_updates_status_and_transcript(monkeypatch) -> None:
    from app.config import settings as _settings
    monkeypatch.setattr(_settings, "personaplex_enabled", False, raising=False)

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
    assert any("twilio_stream_connected" in t for t in texts)
    assert any("twilio_stream_disconnected" in t for t in texts)
