from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import TypeAdapter

from app.schemas.action import (
    Action,
    AddItemAction,
    AnswerMenuQuestionAction,
    AskClarificationAction,
    CancelOrderAction,
    ConfirmOrderAction,
    ModifyItemAction,
    RemoveItemAction,
    SetCustomerInfoAction,
    SetOrderTypeAction,
    TransferToStaffAction,
)
from app.schemas.cart import Cart, LineItem
from app.services.menu_catalog import MenuCatalog, MenuValidationError, item_display_name, validate_line_against_menu

_action_adapter: TypeAdapter[Action] = TypeAdapter(Action)


def parse_action(data: dict) -> Action:
    return _action_adapter.validate_python(data)


def _next_line_id(items: list[LineItem]) -> str:
    nums: list[int] = []
    for it in items:
        if it.id.startswith("item_"):
            try:
                nums.append(int(it.id.split("_", 1)[1]))
            except ValueError:
                pass
    return f"item_{max(nums, default=0) + 1}"


def _norm_mod(m: str) -> str:
    return m.strip().lower()


def _remove_modifiers(base: list[str], to_remove: list[str]) -> list[str]:
    rset = {_norm_mod(x) for x in to_remove}
    return [m for m in base if _norm_mod(m) not in rset]


def _merge_modifiers(base: list[str], add: list[str], remove: list[str]) -> list[str]:
    out = _remove_modifiers(base, remove)
    for a in add:
        if not any(_norm_mod(o) == _norm_mod(a) for o in out):
            out.append(a)
    return out


def recompute_missing_info(cart: Cart) -> list[str]:
    missing: list[str] = []
    if not cart.customer.name:
        missing.append("customer_name")
    if not cart.customer.phone:
        missing.append("customer_phone")
    if cart.order_type == "delivery" and not cart.customer.address:
        missing.append("customer_address")
    return missing


def _terminal_block_message(cart: Cart) -> str | None:
    if cart.metadata.status == "completed":
        return "order_completed"
    if cart.metadata.status == "cancelled":
        return "order_cancelled"
    return None


@dataclass
class ApplyOutcome:
    cart: Cart
    errors: list[str] = field(default_factory=list)
    session_transfer_requested: bool = False

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def apply_actions_sequence(cart: Cart, actions: list[Action], catalog: MenuCatalog) -> ApplyOutcome:
    """Apply actions in order; stop on first error. Aggregates transfer_requested."""
    cur = cart
    xfer = False
    for action in actions:
        out = apply_action(cur, action, catalog)
        cur = out.cart
        xfer = xfer or out.session_transfer_requested
        if out.errors:
            return ApplyOutcome(cart=cur, errors=out.errors, session_transfer_requested=xfer)
    return ApplyOutcome(cart=cur, errors=[], session_transfer_requested=xfer)


def phase_from_state(*, transfer_requested: bool, cart: Cart) -> str:
    """Derive session phase from cart + transfer flag (see docs/architecture.md)."""
    if transfer_requested:
        return "transfer_requested"
    if cart.metadata.status == "cancelled":
        return "cancelled"
    if cart.metadata.status == "completed":
        return "submitted"
    if cart.metadata.status == "confirming":
        return "confirming"
    if cart.metadata.missing_info:
        return "collecting_missing_info"
    if cart.items:
        return "ordering"
    return "greeting"


def apply_action(cart: Cart, action: Action, catalog: MenuCatalog) -> ApplyOutcome:
    """Apply a structured action to the cart. Cart is not mutated in-place; a new Cart is returned."""
    err = _terminal_block_message(cart)
    if err:
        if isinstance(action, (AskClarificationAction, AnswerMenuQuestionAction)):
            c = cart.model_copy(deep=True)
            c.metadata.last_action = action.intent
            return ApplyOutcome(cart=c)
        return ApplyOutcome(cart=cart.model_copy(deep=True), errors=[err])

    if isinstance(action, AddItemAction):
        return _apply_add(cart, action, catalog)
    if isinstance(action, ModifyItemAction):
        return _apply_modify(cart, action, catalog)
    if isinstance(action, RemoveItemAction):
        return _apply_remove(cart, action)
    if isinstance(action, SetOrderTypeAction):
        return _apply_set_order_type(cart, action)
    if isinstance(action, SetCustomerInfoAction):
        return _apply_set_customer(cart, action)
    if isinstance(action, ConfirmOrderAction):
        return _apply_confirm(cart, action)
    if isinstance(action, CancelOrderAction):
        return _apply_cancel(cart, action)
    if isinstance(action, TransferToStaffAction):
        return _apply_transfer(cart, action)
    if isinstance(action, (AskClarificationAction, AnswerMenuQuestionAction)):
        c = cart.model_copy(deep=True)
        c.metadata.last_action = action.intent
        return ApplyOutcome(cart=c)
    return ApplyOutcome(cart=cart.model_copy(deep=True), errors=["unknown_action"])


def _apply_add(cart: Cart, action: AddItemAction, catalog: MenuCatalog) -> ApplyOutcome:
    c = cart.model_copy(deep=True)
    if c.metadata.status == "confirming":
        c.metadata.status = "building"
    try:
        validate_line_against_menu(catalog, action.menu_item_id, action.size, action.modifiers)
    except MenuValidationError as e:
        return ApplyOutcome(cart=cart.model_copy(deep=True), errors=[e.code])
    name = action.name or item_display_name(catalog, action.menu_item_id)
    line = LineItem(
        id=_next_line_id(c.items),
        menu_item_id=action.menu_item_id,
        name=name,
        size=action.size,
        qty=action.qty,
        modifiers=list(action.modifiers),
        special_instructions=action.special_instructions,
    )
    c.items = [*c.items, line]
    c.metadata.last_action = "add_item"
    c.metadata.missing_info = recompute_missing_info(c)
    return ApplyOutcome(cart=c)


def _find_line(cart: Cart, target_id: str) -> tuple[int, LineItem] | None:
    for i, line in enumerate(cart.items):
        if line.id == target_id:
            return i, line
    return None


def _apply_modify(cart: Cart, action: ModifyItemAction, catalog: MenuCatalog) -> ApplyOutcome:
    found = _find_line(cart, action.target_item_id)
    if not found:
        return ApplyOutcome(cart=cart.model_copy(deep=True), errors=["unknown_item_id"])
    idx, line = found
    c = cart.model_copy(deep=True)
    if c.metadata.status == "confirming":
        c.metadata.status = "building"
    ch = action.changes
    new_menu_id = ch.menu_item_id if ch.menu_item_id is not None else line.menu_item_id
    new_size = ch.size if ch.size is not None else line.size
    new_qty = ch.qty if ch.qty is not None else line.qty
    new_name = ch.name if ch.name is not None else line.name
    new_si = ch.special_instructions if ch.special_instructions is not None else line.special_instructions
    new_mods = _merge_modifiers(line.modifiers, ch.modifiers_add, ch.modifiers_remove)
    if ch.menu_item_id is not None:
        new_name = item_display_name(catalog, new_menu_id)
    try:
        validate_line_against_menu(catalog, new_menu_id, new_size, new_mods)
    except MenuValidationError as e:
        return ApplyOutcome(cart=cart.model_copy(deep=True), errors=[e.code])
    updated = LineItem(
        id=line.id,
        menu_item_id=new_menu_id,
        name=new_name,
        size=new_size,
        qty=new_qty,
        modifiers=new_mods,
        special_instructions=new_si,
    )
    items = list(c.items)
    items[idx] = updated
    c.items = items
    c.metadata.last_action = "modify_item"
    c.metadata.missing_info = recompute_missing_info(c)
    return ApplyOutcome(cart=c)


def _apply_remove(cart: Cart, action: RemoveItemAction) -> ApplyOutcome:
    found = _find_line(cart, action.target_item_id)
    if not found:
        return ApplyOutcome(cart=cart.model_copy(deep=True), errors=["unknown_item_id"])
    c = cart.model_copy(deep=True)
    if c.metadata.status == "confirming":
        c.metadata.status = "building"
    c.items = [x for x in c.items if x.id != action.target_item_id]
    c.metadata.last_action = "remove_item"
    c.metadata.missing_info = recompute_missing_info(c)
    return ApplyOutcome(cart=c)


def _apply_set_order_type(cart: Cart, action: SetOrderTypeAction) -> ApplyOutcome:
    c = cart.model_copy(deep=True)
    if c.metadata.status == "confirming":
        c.metadata.status = "building"
    c.order_type = action.order_type
    c.metadata.last_action = "set_order_type"
    c.metadata.missing_info = recompute_missing_info(c)
    return ApplyOutcome(cart=c)


def _apply_set_customer(cart: Cart, action: SetCustomerInfoAction) -> ApplyOutcome:
    c = cart.model_copy(deep=True)
    if c.metadata.status == "confirming":
        c.metadata.status = "building"
    cu = c.customer.model_copy()
    if action.name is not None:
        cu.name = action.name
    if action.phone is not None:
        cu.phone = action.phone
    if action.address is not None:
        cu.address = action.address
    c.customer = cu
    c.metadata.last_action = "set_customer_info"
    c.metadata.missing_info = recompute_missing_info(c)
    return ApplyOutcome(cart=c)


def _apply_confirm(cart: Cart, action: ConfirmOrderAction) -> ApplyOutcome:
    if not cart.items:
        return ApplyOutcome(cart=cart.model_copy(deep=True), errors=["cart_empty"])
    c = cart.model_copy(deep=True)
    c.metadata.status = "confirming"
    c.metadata.last_action = "confirm_order"
    return ApplyOutcome(cart=c)


def _apply_cancel(cart: Cart, action: CancelOrderAction) -> ApplyOutcome:
    c = cart.model_copy(deep=True)
    c.metadata.status = "cancelled"
    c.metadata.last_action = "cancel_order"
    return ApplyOutcome(cart=c)


def _apply_transfer(cart: Cart, action: TransferToStaffAction) -> ApplyOutcome:
    c = cart.model_copy(deep=True)
    c.metadata.last_action = "transfer_to_staff"
    return ApplyOutcome(cart=c, session_transfer_requested=True)
