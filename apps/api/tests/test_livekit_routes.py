from __future__ import annotations

from unittest.mock import MagicMock, patch
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_livekit_token_returns_503_when_unconfigured() -> None:
    client = TestClient(app)
    r = client.post(
        "/livekit/token",
        json={"session_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 503
    assert r.json()["detail"] == "livekit_not_configured"


def _patched_livekit_settings():
    m = MagicMock()
    m.livekit_url = "wss://example.test"
    m.livekit_api_key = "testkey"
    m.livekit_api_secret = "testsecret_must_be_long_enough_hs256"
    return m


def test_livekit_token_returns_404_for_unknown_session() -> None:
    with patch("app.api.routes_livekit.settings", _patched_livekit_settings()):
        client = TestClient(app)
        r = client.post(
            "/livekit/token",
            json={"session_id": "00000000-0000-0000-0000-000000000000"},
        )
    assert r.status_code == 404


def test_livekit_token_mints_for_existing_session() -> None:
    with patch("app.api.routes_livekit.settings", _patched_livekit_settings()):
        client = TestClient(app)
        sid = client.post("/sessions").json()["id"]
        r = client.post("/livekit/token", json={"session_id": sid})
    assert r.status_code == 200
    body = r.json()
    assert body["url"] == "wss://example.test"
    assert body["room_name"] == f"kc-{sid}"
    assert isinstance(body["token"], str) and len(body["token"]) > 20


def test_agent_status_reports_missing_heartbeat() -> None:
    tmp = Path("/tmp/kitchencall-agent-heartbeat-test-missing.json")
    if tmp.exists():
        tmp.unlink()
    with patch("app.api.routes.settings.agent_heartbeat_path", tmp), patch(
        "app.api.routes.settings.agent_heartbeat_stale_after_seconds", 20
    ):
        client = TestClient(app)
        r = client.get("/agent/status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["reason"] == "heartbeat_missing"


def test_agent_status_reports_ok_when_fresh() -> None:
    tmp = Path("/tmp/kitchencall-agent-heartbeat-test-fresh.json")
    tmp.write_text(
        json.dumps(
            {
                "updated_at_epoch_s": time.time(),
                "stt_backend": "kyutai",
                "tts_backend": "inference",
            }
        ),
        encoding="utf-8",
    )
    with patch("app.api.routes.settings.agent_heartbeat_path", tmp), patch(
        "app.api.routes.settings.agent_heartbeat_stale_after_seconds", 20
    ):
        client = TestClient(app)
        r = client.get("/agent/status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["reason"] == "ok"
    assert body["stt_backend"] == "kyutai"
