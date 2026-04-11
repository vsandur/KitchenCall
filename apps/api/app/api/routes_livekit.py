from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from livekit.api import AccessToken, VideoGrants
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db import repo
from app.db.database import get_db

router = APIRouter(prefix="/livekit", tags=["livekit"])


class LiveKitTokenIn(BaseModel):
    session_id: str = Field(..., description="KitchenCall session UUID from POST /sessions")
    participant_identity: str | None = Field(
        default=None, description="LiveKit participant identity (defaults to kitchencall-user)"
    )
    participant_name: str | None = Field(default=None, description="Display name for the participant")


def _livekit_configured() -> bool:
    return bool(
        (settings.livekit_url or "").strip()
        and (settings.livekit_api_key or "").strip()
        and (settings.livekit_api_secret or "").strip()
    )


@router.post("/token")
def mint_participant_token(body: LiveKitTokenIn, db: Session = Depends(get_db)) -> dict:
    """Mint a short-lived JWT for the browser to join room `kc-{session_id}`. Requires LiveKit env on the API."""
    if not _livekit_configured():
        raise HTTPException(
            status_code=503,
            detail="livekit_not_configured",
        )
    row = repo.get_session_row(db, body.session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="session_not_found")

    room_name = f"kc-{body.session_id}"
    identity = (body.participant_identity or "").strip() or "kitchencall-user"
    name = (body.participant_name or "").strip() or "Guest"

    token = AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
    token.with_identity(identity)
    token.with_name(name)
    token.with_grants(
        VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )
    )

    return {
        "url": settings.livekit_url.strip(),
        "room_name": room_name,
        "token": token.to_jwt(),
    }
