from pathlib import Path

import pytest

from app.schemas.action import AddItemAction, ModifyItemAction, RemoveItemAction, SetCustomerInfoAction
from app.schemas.cart import Cart, Customer, OrderMetadata
from app.services.menu_catalog import MenuCatalog
from app.services.state_engine import apply_action, parse_action, recompute_missing_info

_MENU = Path(__file__).resolve().parent.parent / "data" / "menu.json"


@pytest.fixture
def catalog() -> MenuCatalog:
    return MenuCatalog.load(_MENU)


def _empty_cart() -> Cart:
    return Cart(
        order_id="sess_test",
        customer=Customer(),
        metadata=OrderMetadata(),
    )


def test_add_and_modify_size(catalog: MenuCatalog) -> None:
    c = _empty_cart()
    out = apply_action(c, AddItemAction(menu_item_id="pizza_pepperoni", size="large", qty=1), catalog)
    assert out.ok
    assert len(out.cart.items) == 1
    lid = out.cart.items[0].id
    out2 = apply_action(
        out.cart,
        ModifyItemAction(target_item_id=lid, changes={"size": "medium"}),
        catalog,
    )
    assert out2.ok
    assert out2.cart.items[0].size == "medium"


def test_modify_modifiers(catalog: MenuCatalog) -> None:
    c = _empty_cart()
    c = apply_action(
        c,
        AddItemAction(menu_item_id="pizza_pepperoni", size="large", modifiers=["extra cheese"]),
        catalog,
    ).cart
    lid = c.items[0].id
    out = apply_action(
        c,
        ModifyItemAction(
            target_item_id=lid,
            changes={"modifiers_add": ["well done"], "modifiers_remove": ["extra cheese"]},
        ),
        catalog,
    )
    assert out.ok
    mods = [m.lower() for m in out.cart.items[0].modifiers]
    assert "well done" in mods
    assert "extra cheese" not in mods


def test_remove_unknown_line(catalog: MenuCatalog) -> None:
    c = _empty_cart()
    out = apply_action(c, RemoveItemAction(target_item_id="item_999"), catalog)
    assert not out.ok
    assert "unknown_item_id" in out.errors


def test_confirm_empty_cart_errors(catalog: MenuCatalog) -> None:
    from app.schemas.action import ConfirmOrderAction

    c = _empty_cart()
    out = apply_action(c, ConfirmOrderAction(), catalog)
    assert not out.ok
    assert "cart_empty" in out.errors


def test_completed_blocks_add(catalog: MenuCatalog) -> None:
    from app.schemas.action import ConfirmOrderAction

    c = _empty_cart()
    c = apply_action(c, AddItemAction(menu_item_id="drink_coke", size="can"), catalog).cart
    c.metadata.status = "completed"
    out = apply_action(c, AddItemAction(menu_item_id="drink_coke", size="can"), catalog)
    assert not out.ok


def test_swap_menu_item(catalog: MenuCatalog) -> None:
    c = _empty_cart()
    c = apply_action(c, AddItemAction(menu_item_id="burger_classic", size="single"), catalog).cart
    lid = c.items[0].id
    out = apply_action(
        c,
        ModifyItemAction(
            target_item_id=lid,
            changes={"menu_item_id": "sandwich_chicken", "modifiers_add": ["no mayo"]},
        ),
        catalog,
    )
    assert out.ok
    assert out.cart.items[0].menu_item_id == "sandwich_chicken"


def test_parse_action_roundtrip() -> None:
    raw = {
        "intent": "add_item",
        "menu_item_id": "pizza_pepperoni",
        "size": "small",
        "qty": 2,
        "modifiers": [],
    }
    a = parse_action(raw)
    assert isinstance(a, AddItemAction)
    assert a.qty == 2


def test_recompute_missing_delivery() -> None:
    c = Cart(order_id="x", customer=Customer(name="A", phone="1"), order_type="delivery")
    c.customer.address = None
    assert "customer_address" in recompute_missing_info(c)
