"""Shared finalize logic for POST /sessions/{id}/finalize and voice (Twilio) flow."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import repo
from app.schemas.cart import Cart
from app.services.state_engine import phase_from_state


def finalize_session_core(db: Session, session_id: str) -> dict:
    """
    Mark session completed and persist order (same as finalize with affirmed=true).
    Returns JSON-serializable dict like the HTTP handler.
    """
    row = repo.get_session_row(db, session_id)
    if row is None:
        raise KeyError("session_not_found")
    cart = repo.cart_from_row(row)
    if cart.metadata.status == "completed":
        existing = repo.get_latest_order_for_session(db, session_id)
        if existing is None:
            raise RuntimeError("session_marked_completed_without_saved_order")
        replay_cart = Cart.model_validate_json(existing.cart_json)
        return {
            "ok": True,
            "saved_order_id": existing.id,
            "cart": replay_cart.model_dump(),
            "idempotent_replay": True,
        }
    if cart.metadata.status != "confirming":
        raise ValueError("not_in_confirming_state")
    cart = cart.model_copy(deep=True)
    cart.metadata.status = "completed"
    order = repo.save_completed_order(db, session_id, cart)
    phase = phase_from_state(transfer_requested=row.transfer_requested, cart=cart)
    repo.save_cart(db, row, cart, phase=phase, transfer_requested=row.transfer_requested)
    repo.append_transcript(
        db, session_id, role="system", text="Order finalized and saved.", is_partial=False
    )
    return {"ok": True, "saved_order_id": order.id, "cart": cart.model_dump()}
