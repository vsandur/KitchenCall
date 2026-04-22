from __future__ import annotations

from typing import Any

from app.schemas.cart import Cart
from app.services.menu_catalog import MenuCatalog


def build_assistant_response(
    *,
    actions: list[Any],
    cart: Cart,
    errors: list[str],
    transfer_requested: bool,
    catalog: MenuCatalog,
) -> str:
    _ = catalog
    if transfer_requested:
        return "I'll connect you with a team member who can help."
    if errors:
        return " ".join(errors) + " What would you like to do next?"
    for a in actions:
        fu = getattr(a, "assistant_followup", None)
        if fu:
            return str(fu)
    if cart.metadata.status == "confirming":
        parts = []
        if cart.items:
            parts.append(
                "Your order: "
                + ", ".join(f"{it.qty}x {it.name}" + (f" ({it.size})" if it.size else "") for it in cart.items)
            )
        if cart.customer.name:
            parts.append(f"Name: {cart.customer.name}")
        if cart.customer.phone:
            parts.append(f"Phone: {cart.customer.phone}")
        summary = ". ".join(parts) if parts else "Here's your order."
        return f"{summary}. Does that all look right?"
    if cart.items:
        return f"I've got {len(cart.items)} item(s) on your order. Anything else?"
    return "Got it. What can I get started for you?"
