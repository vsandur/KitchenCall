from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_menu_catalog
from app.db import repo
from app.db.database import get_db
from app.db.models import KitchenSession, TranscriptLine
from app.schemas.cart import Cart
from app.services.logic_loop import is_affirmation
from app.services.menu_catalog import MenuCatalog
from app.services import orchestrator
from app.services.session_finalize import finalize_session_core
from app.services.session_turn import execute_process_turn

router = APIRouter(prefix="/sessions", tags=["sessions"])
orders_router = APIRouter(tags=["orders"])


class TranscriptIn(BaseModel):
    role: str = "user"
    text: str
    is_partial: bool = False


class ProcessTurnIn(BaseModel):
    text: str


class ActionBody(BaseModel):
    action: dict


class FinalizeBody(BaseModel):
    affirmed: bool = Field(..., description="Must be true per PRD §5.7 confirmation gate.")


def _session_response(row: KitchenSession, cart: Cart, transcripts: list[TranscriptLine]) -> dict:
    return {
        "id": row.id,
        "phase": row.phase,
        "transfer_requested": row.transfer_requested,
        "cart": cart.model_dump(),
        "transcript": [
            {
                "id": t.id,
                "role": t.role,
                "text": t.text,
                "is_partial": t.is_partial,
                "created_at": t.created_at.isoformat(),
            }
            for t in transcripts
        ],
    }


@router.post("", status_code=201)
def create_session(db: Session = Depends(get_db)) -> dict:
    row = repo.create_session(db)
    cart = repo.cart_from_row(row)
    return _session_response(row, cart, [])


@router.get("")
def list_sessions(db: Session = Depends(get_db), limit: int = 50) -> list[dict]:
    rows = repo.list_sessions(db, limit=limit)
    phone_ids = repo.session_ids_with_phone_calls(db)
    return [
        {
            "id": r.id,
            "phase": r.phase,
            "transfer_requested": r.transfer_requested,
            "updated_at": r.updated_at.isoformat(),
            "has_phone_call": r.id in phone_ids,
        }
        for r in rows
    ]


@router.get("/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db)) -> dict:
    row = repo.get_session_row(db, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    cart = repo.cart_from_row(row)
    tr = repo.list_transcripts(db, session_id)
    return _session_response(row, cart, tr)


@router.post("/{session_id}/transcript")
def post_transcript(session_id: str, body: TranscriptIn, db: Session = Depends(get_db)) -> dict:
    row = repo.get_session_row(db, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    line = repo.append_transcript(
        db,
        session_id,
        role=body.role,
        text=body.text,
        is_partial=body.is_partial,
    )
    return {"id": line.id, "role": line.role, "text": line.text, "is_partial": line.is_partial}


@router.post("/{session_id}/process-turn")
def process_turn(
    session_id: str,
    body: ProcessTurnIn,
    db: Session = Depends(get_db),
    catalog: MenuCatalog = Depends(get_menu_catalog),
) -> dict:
    row = repo.get_session_row(db, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    try:
        cart, errors, intents, _xfer, assistant_response = execute_process_turn(
            db, session_id, body.text, catalog
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="session_not_found") from None
    row = repo.get_session_row(db, session_id)
    assert row is not None
    tr = repo.list_transcripts(db, session_id)
    hint = None
    if cart.metadata.status == "confirming" and is_affirmation(body.text):
        hint = 'Call POST /sessions/{id}/finalize with {"affirmed": true} to complete.'

    return {
        **_session_response(row, cart, tr),
        "applied_intents": intents,
        "errors": errors,
        "affirmation_hint": hint,
        "assistant_response": assistant_response,
    }


@router.post("/{session_id}/actions")
def post_action(
    session_id: str,
    body: ActionBody,
    db: Session = Depends(get_db),
    catalog: MenuCatalog = Depends(get_menu_catalog),
) -> dict:
    try:
        cart, errors, _xfer = orchestrator.apply_single_action(db, session_id, body.action, catalog)
    except ValueError:
        raise HTTPException(status_code=404, detail="session_not_found") from None
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors, "cart": cart.model_dump()})
    row = repo.get_session_row(db, session_id)
    assert row is not None
    tr = repo.list_transcripts(db, session_id)
    return _session_response(row, cart, tr)


@router.post("/{session_id}/finalize")
def finalize_session(
    session_id: str,
    body: FinalizeBody,
    db: Session = Depends(get_db),
) -> dict:
    if not body.affirmed:
        raise HTTPException(status_code=400, detail="affirmed_must_be_true")
    try:
        return finalize_session_core(db, session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session_not_found") from None
    except ValueError as e:
        if str(e) == "not_in_confirming_state":
            raise HTTPException(status_code=409, detail="not_in_confirming_state") from None
        raise
    except RuntimeError:
        raise HTTPException(
            status_code=409,
            detail="session_marked_completed_without_saved_order",
        ) from None


@orders_router.get("/orders")
def list_completed_orders(db: Session = Depends(get_db), limit: int = 50) -> list[dict]:
    orders = repo.list_orders(db, limit=limit)
    out = []
    for o in orders:
        try:
            cart_dump = Cart.model_validate_json(o.cart_json).model_dump()
        except ValidationError:
            cart_dump = {}
        out.append(
            {
                "id": o.id,
                "session_id": o.session_id,
                "created_at": o.created_at.isoformat(),
                "cart": cart_dump,
            }
        )
    return out
