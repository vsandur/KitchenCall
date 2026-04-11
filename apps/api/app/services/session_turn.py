"""Shared process-turn path for HTTP and telephony (same orchestrator + transcripts)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import repo
from app.schemas.cart import Cart
from app.services.menu_catalog import MenuCatalog
from app.services import orchestrator


def execute_process_turn(
    db: Session,
    session_id: str,
    text: str,
    catalog: MenuCatalog,
) -> tuple[Cart, list[str], list[str], bool, str | None]:
    """
    Append user transcript, run orchestrator, append assistant transcript when present.
    Raises ValueError if session is missing.
    """
    row = repo.get_session_row(db, session_id)
    if row is None:
        raise ValueError("session_not_found")
    repo.append_transcript(db, session_id, role="user", text=text, is_partial=False)
    cart, errors, intents, xfer, assistant_response = orchestrator.process_user_final_text(
        db, session_id, text, catalog
    )
    if assistant_response:
        repo.append_transcript(db, session_id, role="assistant", text=assistant_response, is_partial=False)
    return cart, errors, intents, xfer, assistant_response
