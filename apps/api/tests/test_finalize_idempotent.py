from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def _drive_session_to_confirming(client: TestClient, sid: str) -> None:
    for text in (
        "large pepperoni for pickup",
        "garlic knots",
        "Coke",
        "name is Alex",
        "phone is 555-123-4567",
        "that's all",
        "yes",
    ):
        r = client.post(f"/sessions/{sid}/process-turn", json={"text": text})
        assert r.status_code == 200, (text, r.status_code, r.text)


def test_finalize_twice_returns_same_order_and_flag(monkeypatch) -> None:
    monkeypatch.setattr(settings, "logic_extractor", "rules", raising=False)
    client = TestClient(app)
    sid = client.post("/sessions", json={}).json()["id"]
    _drive_session_to_confirming(client, sid)

    r1 = client.post(f"/sessions/{sid}/finalize", json={"affirmed": True})
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["ok"] is True
    assert "idempotent_replay" not in b1
    oid = b1["saved_order_id"]

    r2 = client.post(f"/sessions/{sid}/finalize", json={"affirmed": True})
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["ok"] is True
    assert b2["saved_order_id"] == oid
    assert b2.get("idempotent_replay") is True

    orders = client.get("/orders").json()
    matching = [o for o in orders if o["session_id"] == sid]
    assert len(matching) == 1
