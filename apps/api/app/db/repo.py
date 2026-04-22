from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import KitchenSession, SavedOrder, TelephonyCall, TranscriptLine
from app.schemas.cart import Cart, Customer, OrderMetadata


def create_session(db: Session) -> KitchenSession:
    sid = str(uuid.uuid4())
    cart = Cart(order_id=sid, customer=Customer(), metadata=OrderMetadata())
    row = KitchenSession(id=sid, phase="greeting", cart_json=cart.model_dump_json())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_session_row(db: Session, session_id: str) -> KitchenSession | None:
    return db.get(KitchenSession, session_id)


def save_cart(
    db: Session,
    row: KitchenSession,
    cart: Cart,
    *,
    phase: str | None = None,
    transfer_requested: bool | None = None,
) -> None:
    row.cart_json = cart.model_dump_json()
    if phase is not None:
        row.phase = phase
    if transfer_requested is not None:
        row.transfer_requested = transfer_requested
    db.add(row)
    db.commit()
    db.refresh(row)


def cart_from_row(row: KitchenSession) -> Cart:
    return Cart.model_validate_json(row.cart_json or "{}")


def append_transcript(
    db: Session,
    session_id: str,
    *,
    role: str,
    text: str,
    is_partial: bool,
) -> None:
    line = TranscriptLine(session_id=session_id, role=role, text=text, is_partial=is_partial)
    db.add(line)
    db.commit()


def list_transcripts(db: Session, session_id: str) -> Sequence[TranscriptLine]:
    stmt = (
        select(TranscriptLine)
        .where(TranscriptLine.session_id == session_id)
        .order_by(TranscriptLine.id.asc())
    )
    return db.scalars(stmt).all()


def list_sessions(db: Session, limit: int = 50) -> Sequence[KitchenSession]:
    stmt = select(KitchenSession).order_by(KitchenSession.updated_at.desc()).limit(limit)
    return db.scalars(stmt).all()


def upsert_twilio_call(
    db: Session,
    *,
    call_sid: str,
    session_id: str,
    from_number: str,
    to_number: str,
    room_name: str,
    status: str,
) -> TelephonyCall:
    row = db.scalars(select(TelephonyCall).where(TelephonyCall.call_sid == call_sid)).first()
    if row is None:
        row = TelephonyCall(
            call_sid=call_sid,
            session_id=session_id,
            from_number=from_number,
            to_number=to_number,
            room_name=room_name,
            status=status,
        )
        db.add(row)
    else:
        row.session_id = session_id
        row.from_number = from_number
        row.to_number = to_number
        row.room_name = room_name
        row.status = status
    db.commit()
    db.refresh(row)
    return row


def update_telephony_call_status(db: Session, *, call_sid: str, status: str) -> TelephonyCall | None:
    row = db.scalars(select(TelephonyCall).where(TelephonyCall.call_sid == call_sid)).first()
    if row is None:
        return None
    row.status = status
    db.commit()
    db.refresh(row)
    return row


def list_telephony_calls(db: Session, limit: int = 50) -> Sequence[TelephonyCall]:
    stmt = select(TelephonyCall).order_by(TelephonyCall.created_at.desc()).limit(limit)
    return db.scalars(stmt).all()


def get_telephony_call_by_sid(db: Session, call_sid: str) -> TelephonyCall | None:
    return db.scalars(select(TelephonyCall).where(TelephonyCall.call_sid == call_sid)).first()


def get_latest_order_for_session(db: Session, session_id: str) -> SavedOrder | None:
    stmt = (
        select(SavedOrder)
        .where(SavedOrder.session_id == session_id)
        .order_by(SavedOrder.id.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def save_completed_order(db: Session, session_id: str, cart: Cart) -> SavedOrder:
    order = SavedOrder(session_id=session_id, cart_json=cart.model_dump_json())
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def list_saved_orders(db: Session, limit: int = 50) -> Sequence[SavedOrder]:
    stmt = select(SavedOrder).order_by(SavedOrder.created_at.desc()).limit(limit)
    return db.scalars(stmt).all()
