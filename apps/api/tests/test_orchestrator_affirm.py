from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.db import repo
from app.db.database import init_db
from app.schemas.cart import Cart, Customer, LineItem, OrderMetadata
from app.services.menu_catalog import MenuCatalog
from app.services import orchestrator

_MENU = Path(__file__).resolve().parent.parent / "data" / "menu.json"


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "orch_test.db"
    monkeypatch.setattr(settings, "database_path", db_path)
    import app.db.database as dbmod

    dbmod._engine = None
    dbmod._SessionLocal = None
    init_db()
    SessionLocal = dbmod.get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        dbmod._engine = None
        dbmod._SessionLocal = None


def test_yes_while_confirming_emits_confirm_intent(fresh_db) -> None:
    catalog = MenuCatalog.load(_MENU)
    row = repo.create_session(fresh_db)
    sid = row.id
    cart = Cart(
        order_id=sid,
        customer=Customer(name="Alex", phone="5551234567"),
        order_type="pickup",
        items=[
            LineItem(
                id="item_1",
                menu_item_id="pizza_pepperoni",
                name="Pepperoni Pizza",
                size="large",
                qty=1,
            )
        ],
        metadata=OrderMetadata(status="confirming", missing_info=[], last_action="confirm_order"),
    )
    repo.save_cart(fresh_db, row, cart, phase="confirming")

    out_cart, errors, intents, _xfer, _msg = orchestrator.process_user_final_text(
        fresh_db, sid, "yes", catalog
    )

    assert "confirm_order" in intents
    assert not errors
    assert out_cart.metadata.status == "confirming"
