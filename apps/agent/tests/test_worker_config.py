from __future__ import annotations

import os

import pytest

from kitchencall_agent.worker import (
    ensure_runtime_config,
    run_check_mode,
    session_id_from_room,
    validate_runtime_config,
)


def _set_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "lk_test_key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "lk_test_secret")
    monkeypatch.setenv("KITCHENCALL_API_BASE", "http://127.0.0.1:8000")
    monkeypatch.setenv("KITCHENCALL_STT_BACKEND", "inference")
    monkeypatch.setenv("KITCHENCALL_TTS_BACKEND", "inference")


def test_session_id_from_room_valid_uuid() -> None:
    sid = "123e4567-e89b-12d3-a456-426614174000"
    assert session_id_from_room(f"kc-{sid}") == sid


def test_session_id_from_room_invalid_values() -> None:
    assert session_id_from_room("wrong-prefix") is None
    assert session_id_from_room("kc-not-a-uuid") is None


def test_validate_runtime_config_ok_for_inference(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_base_env(monkeypatch)
    assert validate_runtime_config() == []


def test_validate_runtime_config_requires_kyutai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_base_env(monkeypatch)
    monkeypatch.setenv("KITCHENCALL_STT_BACKEND", "kyutai")
    monkeypatch.delenv("KYUTAI_API_KEY", raising=False)

    errors = validate_runtime_config()
    assert "KYUTAI_API_KEY is required when KITCHENCALL_STT_BACKEND=kyutai" in errors


def test_validate_runtime_config_invalid_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_base_env(monkeypatch)
    monkeypatch.setenv("KITCHENCALL_STT_BACKEND", "unknown")
    monkeypatch.setenv("KITCHENCALL_TTS_BACKEND", "unknown")

    errors = validate_runtime_config()
    assert "KITCHENCALL_STT_BACKEND must be 'kyutai' or 'inference'" in errors
    assert "KITCHENCALL_TTS_BACKEND must be 'inference'" in errors


def test_validate_runtime_config_bad_api_base(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_base_env(monkeypatch)
    monkeypatch.setenv("KITCHENCALL_API_BASE", "127.0.0.1:8000")

    errors = validate_runtime_config()
    assert "KITCHENCALL_API_BASE must start with http:// or https://" in errors


def test_ensure_runtime_config_raises_with_all_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "KITCHENCALL_API_BASE",
        "KITCHENCALL_STT_BACKEND",
        "KITCHENCALL_TTS_BACKEND",
        "KYUTAI_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(RuntimeError) as exc:
        ensure_runtime_config()

    msg = str(exc.value)
    assert "Invalid worker configuration:" in msg
    assert "LIVEKIT_URL is required" in msg
    assert "LIVEKIT_API_KEY is required" in msg
    assert "LIVEKIT_API_SECRET is required" in msg


def test_run_check_mode_ok(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _set_base_env(monkeypatch)
    code = run_check_mode()
    out = capsys.readouterr().out
    assert code == 0
    assert "KitchenCall worker config check: OK" in out


def test_run_check_mode_fail(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)
    code = run_check_mode()
    out = capsys.readouterr().out
    assert code == 1
    assert "KitchenCall worker config check: FAILED" in out
    assert "- LIVEKIT_URL is required" in out
