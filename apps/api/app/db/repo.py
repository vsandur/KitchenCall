from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import KitchenSession, SavedOrder, TelephonyCall, TranscriptLine
from app.schemas.cart import Cart, Customer, OrderMetadata


def new_cart(session_id: str) -> Cart:
    return Cart(order_id=session_id, customer=Customer(), metadata=OrderMetadata())


def create_session(db: Session) -> KitchenSession:
    sid = str(uuid.uuid4())
    cart = new_cart(sid)
    row = KitchenSession(
        id=sid,
        phase="greeting",
        cart_json=cart.model_dump_json(),
        transfer_requested=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_session_row(db: Session, session_id: str) -> KitchenSession | None:
    return db.get(KitchenSession, session_id)


def cart_from_row(row: KitchenSession) -> Cart:
    return Cart.model_validate_json(row.cart_json)


def save_cart(
    db: Session,
    row: KitchenSession,
    cart: Cart,
    *,
    phase: str | None = None,
    transfer_requested: bool | None = None,
) -> None:
    row.cart_json = cart.model_dump_json()
    row.updated_at = datetime.now(timezone.utc)
    if phase is not None:
        row.phase = phase
    if transfer_requested is not None:
        row.transfer_requested = transfer_requested
    db.commit()


def append_transcript(
    db: Session,
    session_id: str,
    *,
    role: str,
    text: str,
    is_partial: bool = False,
) -> TranscriptLine:
    line = TranscriptLine(session_id=session_id, role=role, text=text, is_partial=is_partial)
    db.add(line)
    db.commit()
    db.refresh(line)
    return line


def list_transcripts(db: Session, session_id: str, limit: int = 500) -> list[TranscriptLine]:
    q = (
        select(TranscriptLine)
        .where(TranscriptLine.session_id == session_id)
        .order_by(TranscriptLine.id.asc())
        .limit(limit)
    )
    return list(db.scalars(q).all())


def list_sessions(db: Session, limit: int = 50) -> list[KitchenSession]:
    q = select(KitchenSession).order_by(KitchenSession.updated_at.desc()).limit(limit)
    return list(db.scalars(q).all())


def save_completed_order(db: Session, session_id: str, cart: Cart) -> SavedOrder:
    order = SavedOrder(session_id=session_id, cart_json=cart.model_dump_json())
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def list_orders(db: Session, limit: int = 50) -> list[SavedOrder]:
    q = select(SavedOrder).order_by(SavedOrder.id.desc()).limit(limit)
    return list(db.scalars(q).all())


def get_latest_order_for_session(db: Session, session_id: str) -> SavedOrder | None:
    q = (
        select(SavedOrder)
        .where(SavedOrder.session_id == session_id)
        .order_by(SavedOrder.id.desc())
        .limit(1)
    )
    return db.scalars(q).first()


def get_telephony_call_by_sid(db: Session, call_sid: str) -> TelephonyCall | None:
    q = select(TelephonyCall).where(TelephonyCall.call_sid == call_sid)
    return db.scalars(q).first()


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
    row = get_telephony_call_by_sid(db, call_sid)
    if row is None:
        row = TelephonyCall(
            provider="twilio",
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
        row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def list_telephony_calls(db: Session, *, limit: int = 50) -> list[TelephonyCall]:
    q = select(TelephonyCall).order_by(TelephonyCall.updated_at.desc()).limit(limit)
    return list(db.scalars(q).all())


def session_ids_with_phone_calls(db: Session) -> set[str]:
    q = select(TelephonyCall.session_id).distinct()
    return set(db.scalars(q).all())


def update_telephony_call_status(db: Session, *, call_sid: str, status: str) -> TelephonyCall | None:
    row = get_telephony_call_by_sid(db, call_sid)
    if row is None:
        return None
    row.status = status
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row
