from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.schemas.action import AddItemAction
from app.schemas.cart import Cart, Customer, OrderMetadata
from app.services.logic_extract import extract_actions_for_turn
from app.services.menu_catalog import MenuCatalog

_MENU = Path(__file__).resolve().parent.parent / "data" / "menu.json"


def test_defaults_to_rules_without_llm_config() -> None:
    catalog = MenuCatalog.load(_MENU)
    cart = Cart(order_id="s", customer=Customer(), metadata=OrderMetadata())
    actions = extract_actions_for_turn("large pepperoni for pickup", cart, catalog)
    assert [a.intent for a in actions] == ["set_order_type", "add_item"]


def test_llm_success_returns_model_actions(monkeypatch) -> None:
    import app.services.logic_extract as le

    monkeypatch.setattr(le.settings, "logic_extractor", "llm")
    monkeypatch.setattr(le.settings, "llm_base_url", "http://127.0.0.1:11434/v1")

    fake = [AddItemAction(menu_item_id="drink_coke", size="can", qty=1)]

    with patch("app.services.logic_loop_llm.extract_actions_llm", return_value=fake):
        catalog = MenuCatalog.load(_MENU)
        cart = Cart(order_id="s", customer=Customer(), metadata=OrderMetadata())
        actions = extract_actions_for_turn("a coke please", cart, catalog)
    assert len(actions) == 1
    assert actions[0].intent == "add_item"


def test_legacy_openai_extractor_value_still_triggers_llm_path(monkeypatch) -> None:
    import app.services.logic_extract as le

    monkeypatch.setattr(le.settings, "logic_extractor", "openai")
    monkeypatch.setattr(le.settings, "llm_api_key", "any-key")

    fake = [AddItemAction(menu_item_id="drink_coke", size="can", qty=1)]
    with patch("app.services.logic_loop_llm.extract_actions_llm", return_value=fake):
        catalog = MenuCatalog.load(_MENU)
        cart = Cart(order_id="s", customer=Customer(), metadata=OrderMetadata())
        actions = extract_actions_for_turn("coke", cart, catalog)
    assert actions[0].intent == "add_item"


def test_llm_none_falls_back_to_rules(monkeypatch) -> None:
    import app.services.logic_extract as le

    monkeypatch.setattr(le.settings, "logic_extractor", "llm")
    monkeypatch.setattr(le.settings, "llm_base_url", "http://127.0.0.1:11434/v1")

    with patch("app.services.logic_loop_llm.extract_actions_llm", return_value=None):
        catalog = MenuCatalog.load(_MENU)
        cart = Cart(order_id="s", customer=Customer(), metadata=OrderMetadata())
        actions = extract_actions_for_turn("large pepperoni for pickup", cart, catalog)
    assert "add_item" in [a.intent for a in actions]


def test_llm_empty_substantive_falls_back_to_rules(monkeypatch) -> None:
    import app.services.logic_extract as le

    monkeypatch.setattr(le.settings, "logic_extractor", "llm")
    monkeypatch.setattr(le.settings, "llm_base_url", "http://127.0.0.1:11434/v1")

    with patch("app.services.logic_loop_llm.extract_actions_llm", return_value=[]):
        catalog = MenuCatalog.load(_MENU)
        cart = Cart(order_id="s", customer=Customer(), metadata=OrderMetadata())
        actions = extract_actions_for_turn("large pepperoni for pickup", cart, catalog)
    assert "add_item" in [a.intent for a in actions]


def test_remote_llm_requires_api_key(monkeypatch) -> None:
    import app.services.logic_extract as le

    monkeypatch.setattr(le.settings, "logic_extractor", "llm")
    monkeypatch.setattr(le.settings, "llm_base_url", "https://api.example.com/v1")
    monkeypatch.setattr(le.settings, "llm_api_key", "")

    catalog = MenuCatalog.load(_MENU)
    cart = Cart(order_id="s", customer=Customer(), metadata=OrderMetadata())
    with patch("app.services.logic_loop_llm.extract_actions_llm") as m:
        actions = extract_actions_for_turn("large pepperoni for pickup", cart, catalog)
        m.assert_not_called()
    assert "add_item" in [a.intent for a in actions]
