from pathlib import Path
import json
import time

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.services.menu_catalog import MenuCatalog

router = APIRouter()


def _load_catalog() -> MenuCatalog:
    path: Path = settings.menu_path
    if not path.is_file():
        raise HTTPException(status_code=500, detail=f"Menu file not found: {path}")
    return MenuCatalog.load(path)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/menu")
def get_menu() -> dict:
    """Full menu catalog for dashboard and logic-loop validation."""
    catalog = _load_catalog()
    return catalog.model_dump()


@router.get("/agent/status")
def agent_status() -> dict:
    """Reports worker availability based on heartbeat file freshness."""
    hb_path = settings.agent_heartbeat_path
    if not hb_path.is_file():
        return {"available": False, "reason": "heartbeat_missing", "heartbeat_age_seconds": None}

    try:
        payload = json.loads(hb_path.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "reason": "heartbeat_invalid", "heartbeat_age_seconds": None}

    updated = payload.get("updated_at_epoch_s")
    if not isinstance(updated, (int, float)):
        return {"available": False, "reason": "heartbeat_missing_timestamp", "heartbeat_age_seconds": None}

    age = max(0.0, time.time() - float(updated))
    stale_after = float(settings.agent_heartbeat_stale_after_seconds)
    if age > stale_after:
        return {
            "available": False,
            "reason": "heartbeat_stale",
            "heartbeat_age_seconds": round(age, 2),
        }

    return {
        "available": True,
        "reason": "ok",
        "heartbeat_age_seconds": round(age, 2),
        "stt_backend": payload.get("stt_backend"),
        "tts_backend": payload.get("tts_backend"),
    }
