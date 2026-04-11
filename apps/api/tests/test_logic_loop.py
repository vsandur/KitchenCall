from pathlib import Path

from app.schemas.cart import Cart, Customer, OrderMetadata
from app.services.logic_loop import extract_actions, is_affirmation
from app.services.menu_catalog import MenuCatalog

_MENU = Path(__file__).resolve().parent.parent / "data" / "menu.json"


def test_extract_pepperoni_pickup() -> None:
    catalog = MenuCatalog.load(_MENU)
    cart = Cart(order_id="s", customer=Customer(), metadata=OrderMetadata())
    actions = extract_actions("large pepperoni for pickup", cart, catalog)
    intents = [a.intent for a in actions]
    assert "set_order_type" in intents
    assert "add_item" in intents


def test_is_affirmation() -> None:
    assert is_affirmation("yes")
    assert is_affirmation("That's right")
    assert not is_affirmation("large pepperoni")
