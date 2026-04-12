"""Session orchestration: transcript -> logic extract -> state engine -> persist."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import repo
from app.schemas.action import ConfirmOrderAction
from app.schemas.cart import Cart
from app.services.logic_extract import extract_actions_for_turn
from app.services.logic_loop import is_affirmation
from app.services.menu_catalog import MenuCatalog
from app.services.response_builder import build_assistant_response
from app.services.state_engine import apply_action, apply_actions_sequence, parse_action, phase_from_state


def process_user_final_text(
    db: Session,
    session_id: str,
    text: str,
    catalog: MenuCatalog,
) -> tuple[Cart, list[str], list[str], bool, str]:
    """
    Caller appends transcript first. Returns:
    (cart, errors, intents, transfer_requested, assistant_response).
    """
    row = repo.get_session_row(db, session_id)
    if row is None:
        raise ValueError("session_not_found")

    cart = repo.cart_from_row(row)
    if cart.metadata.status == "confirming" and is_affirmation(text):
        actions = [ConfirmOrderAction()]
    else:
        actions = extract_actions_for_turn(text, cart, catalog)
    intents = [a.intent for a in actions]

    if not actions:
        phase = phase_from_state(transfer_requested=row.transfer_requested, cart=cart)
        repo.save_cart(db, row, cart, phase=phase, transfer_requested=row.transfer_requested)
        assistant_response = "Got it. What can I get started for you?"
        return cart, [], [], row.transfer_requested, assistant_response

    out = apply_actions_sequence(cart, actions, catalog)
    xfer = out.session_transfer_requested or row.transfer_requested
    phase = phase_from_state(transfer_requested=xfer, cart=out.cart)
    repo.save_cart(db, row, out.cart, phase=phase, transfer_requested=xfer)

    assistant_response = build_assistant_response(
        actions=actions,
        cart=out.cart,
        errors=out.errors,
        transfer_requested=xfer,
        catalog=catalog,
    )
    return out.cart, out.errors, intents, xfer, assistant_response


def apply_single_action(
    db: Session,
    session_id: str,
    action_payload: dict,
    catalog: MenuCatalog,
) -> tuple[Cart, list[str], bool]:
    row = repo.get_session_row(db, session_id)
    if row is None:
        raise ValueError("session_not_found")
    cart = repo.cart_from_row(row)
    action = parse_action(action_payload)
    out = apply_action(cart, action, catalog)
    xfer = out.session_transfer_requested or row.transfer_requested
    phase = phase_from_state(transfer_requested=xfer, cart=out.cart)
    if not out.errors:
        repo.save_cart(db, row, out.cart, phase=phase, transfer_requested=xfer)
    return out.cart, out.errors, xfer
