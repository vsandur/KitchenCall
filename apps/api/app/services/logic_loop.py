"""MVP rule-based extractor: final transcript → structured actions (not a planner)."""

from __future__ import annotations

import re

from app.schemas.action import (
    AddItemAction,
    AskClarificationAction,
    CancelOrderAction,
    ConfirmOrderAction,
    ModifyItemAction,
    SetCustomerInfoAction,
    SetOrderTypeAction,
    TransferToStaffAction,
)
from app.schemas.cart import Cart
from app.services.menu_catalog import MenuCatalog


def is_affirmation(text: str) -> bool:
    t = text.lower().strip()
    if not t or len(t) > 120:
        return False
    if t in ("yes", "yeah", "yep", "ok", "okay", "sure", "correct", "right", "perfect"):
        return True
    phrases = ("that's right", "thats right", "sounds good", "looks good", "all good")
    return any(p in t for p in phrases)


def _qty(t: str) -> int:
    m = re.match(r"^(\d+)\s+", t.strip())
    if m:
        return max(1, min(20, int(m.group(1))))
    if re.search(r"\btwo\b", t):
        return 2
    if re.search(r"\bthree\b", t):
        return 3
    if re.search(r"\bfour\b", t):
        return 4
    return 1


def _pizza_size(t: str) -> str | None:
    for s in ("large", "medium", "small"):
        if re.search(rf"\b{s}\b", t):
            return s
    return None


def extract_actions(text: str, cart: Cart, catalog: MenuCatalog) -> list:
    """Return actions to apply in order (may be empty)."""
    t = text.lower().strip()
    actions: list = []
    if not t:
        return actions

    if re.search(r"\b(speak to|talk to a|talk to the|real person|human being|manager)\b", t):
        return [TransferToStaffAction(reason=text.strip()[:200])]
    if re.search(r"\bcancel\b", t) and "don't cancel" not in t and "do not cancel" not in t:
        return [CancelOrderAction()]

    if re.search(r"\bpickup\b", t) and re.search(r"\bdelivery\b", t):
        if t.rfind("pickup") > t.rfind("delivery"):
            actions.append(SetOrderTypeAction(order_type="pickup"))
        else:
            actions.append(SetOrderTypeAction(order_type="delivery"))
    elif re.search(r"\bdelivery\b", t):
        actions.append(SetOrderTypeAction(order_type="delivery"))
    elif re.search(r"\bpickup\b", t):
        actions.append(SetOrderTypeAction(order_type="pickup"))

    q = _qty(t)
    sz = _pizza_size(t)

    if re.search(r"\bpepperoni\b", t):
        if sz:
            actions.append(AddItemAction(menu_item_id="pizza_pepperoni", size=sz, qty=q))
        else:
            actions.append(AskClarificationAction(question="What size for the pepperoni pizza?"))
    elif "cheese" in t and "pizza" in t:
        actions.append(AddItemAction(menu_item_id="pizza_cheese", size=sz or "medium", qty=q))

    if "garlic" in t or "knots" in t:
        knot_size = "12 piece" if re.search(r"\b(12|dozen)\b", t) else "6 piece"
        actions.append(AddItemAction(menu_item_id="side_garlic_knots", size=knot_size, qty=1))

    if re.search(r"\bcoke\b", t) or "coca" in t:
        csize = "20oz" if "20" in t else "can"
        actions.append(AddItemAction(menu_item_id="drink_coke", size=csize, qty=q if q > 1 else 1))

    if "burger" in t:
        bsz = "double" if "double" in t else "single"
        actions.append(AddItemAction(menu_item_id="burger_classic", size=bsz, qty=q))

    if "chicken sandwich" in t or (re.search(r"\bchicken\b", t) and "sandwich" in t):
        actions.append(AddItemAction(menu_item_id="sandwich_chicken", size=None, qty=q))

    if cart.items and re.search(r"\b(actually|make that)\b", t):
        for s in ("medium", "small", "large"):
            if re.search(rf"\b{s}\b", t):
                lid = cart.items[-1].id
                actions.append(ModifyItemAction(target_item_id=lid, changes={"size": s}))
                break

    if cart.items and "extra cheese" in t:
        lid = cart.items[-1].id
        actions.append(ModifyItemAction(target_item_id=lid, changes={"modifiers_add": ["extra cheese"]}))

    if cart.items and re.search(r"\bno onions\b", t):
        lid = cart.items[-1].id
        actions.append(ModifyItemAction(target_item_id=lid, changes={"modifiers_add": ["no onions"]}))

    m = re.search(r"(?:name is|call me|i'?m)\s+([a-z][a-z\s'.-]{1,48})", text.strip(), re.I)
    if m:
        raw_name = re.sub(r"\s+", " ", m.group(1)).strip(" .")
        if raw_name:
            actions.append(SetCustomerInfoAction(name=raw_name.title()))

    if re.search(r"\bphone\b", t) or re.fullmatch(r"[\d\s().-]{10,}", text.strip()):
        digits = re.sub(r"\D", "", text)
        if len(digits) >= 10:
            actions.append(SetCustomerInfoAction(phone=digits[-10:]))

    if re.search(r"\baddress is\b", t):
        rest = text.split("address is", 1)[-1].strip()
        if rest:
            actions.append(SetCustomerInfoAction(address=rest[:300]))

    if re.search(r"\b(that'?s all|that is all|that'?s it|nothing else|ready to (?:order|check out))\b", t):
        actions.append(ConfirmOrderAction())

    _ = catalog  # reserved for future menu-driven clarification
    return actions
