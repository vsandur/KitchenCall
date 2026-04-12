from __future__ import annotations

from app.schemas.action import Action, AskClarificationAction
from app.schemas.cart import Cart
from app.services.menu_catalog import MenuCatalog


def _count_label(n: int, name: str) -> str:
    if n <= 1:
        return f"1 {name}"
    return f"{n} {name}s"


def _cart_quick_summary(cart: Cart) -> str:
    if not cart.items:
        return ""
    top = cart.items[:2]
    parts = [_count_label(x.qty, x.name) for x in top]
    if len(cart.items) > 2:
        parts.append(f"and {len(cart.items)-2} more")
    return ", ".join(parts)


def build_assistant_response(
    *,
    actions: list[Action],
    cart: Cart,
    errors: list[str],
    transfer_requested: bool,
    catalog: MenuCatalog | None = None,
) -> str:
    if transfer_requested:
        return "No problem, I will get someone from staff for you."

    for action in actions:
        if isinstance(action, AskClarificationAction):
            return action.question

    if errors:
        code = errors[0]
        if code == "size_required":
            return "Got it, what size would you like for that?"
        if code in {"invalid_size", "invalid_modifier", "unknown_item", "unknown_item_id"}:
            return "I did not catch that exactly. Can you say that one more time?"
        if code == "cart_empty":
            return "I do not have any items yet. What can I get started for you?"
        if code == "order_completed":
            return "Your order is already complete. Want to start a new one?"
        if code == "order_cancelled":
            return "This order is cancelled. Want to start a new one?"
        return "Can you repeat that for me?"

    intents = {a.intent for a in actions}
    if "confirm_order" in intents:
        summary = _cart_quick_summary(cart)
        order_type = "pickup" if cart.order_type == "pickup" else "delivery"
        if summary:
            return f"Perfect. I have {summary} for {order_type}. Is that right?"
        return "Perfect. Ready to confirm this order?"

    if "set_customer_info" in intents and cart.metadata.missing_info:
        if "customer_phone" in cart.metadata.missing_info:
            return "Thanks. What is the best phone number for this order?"
        if "customer_address" in cart.metadata.missing_info:
            return "Thanks. What is the delivery address?"

    if "add_item" in intents or "modify_item" in intents or "remove_item" in intents:
        summary = _cart_quick_summary(cart)
        if summary:
            return f"Got it. Right now I have {summary}. Anything else?"
        return "Got it. Anything else?"

    if "set_order_type" in intents:
        if cart.order_type == "delivery":
            if "customer_address" in cart.metadata.missing_info:
                return "Delivery, got it. What is the address?"
            return "Delivery, got it. Anything else for this order?"
        return "Pickup, got it. Anything else for this order?"

    if "cancel_order" in intents:
        return "Okay, I cancelled that order."

    if "answer_menu_question" in intents:
        if catalog is not None:
            menu_text = catalog.spoken_menu_summary()
            return (
                f"Happy to help. Here is our menu today. {menu_text} "
                "When you are ready, tell me what you would like, or say menu again if you need a reminder."
            )
        return "I can walk you through the menu. What kind of item are you in the mood for?"

    return "Got it. Anything else for your order?"
