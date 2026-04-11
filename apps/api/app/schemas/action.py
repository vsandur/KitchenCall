from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class ModifyItemChanges(BaseModel):
    size: str | None = None
    qty: int | None = Field(default=None, ge=1)
    modifiers_add: list[str] = Field(default_factory=list)
    modifiers_remove: list[str] = Field(default_factory=list)
    menu_item_id: str | None = None
    name: str | None = None
    special_instructions: str | None = None


class AddItemAction(BaseModel):
    intent: Literal["add_item"] = "add_item"
    menu_item_id: str
    name: str | None = None
    size: str | None = None
    qty: int = Field(default=1, ge=1)
    modifiers: list[str] = Field(default_factory=list)
    special_instructions: str | None = None
    assistant_followup: str | None = None


class ModifyItemAction(BaseModel):
    intent: Literal["modify_item"] = "modify_item"
    target_item_id: str
    changes: ModifyItemChanges = Field(default_factory=ModifyItemChanges)
    assistant_followup: str | None = None


class RemoveItemAction(BaseModel):
    intent: Literal["remove_item"] = "remove_item"
    target_item_id: str
    assistant_followup: str | None = None


class AskClarificationAction(BaseModel):
    intent: Literal["ask_clarification"] = "ask_clarification"
    question: str
    assistant_followup: str | None = None


class AnswerMenuQuestionAction(BaseModel):
    intent: Literal["answer_menu_question"] = "answer_menu_question"
    topic: str | None = None
    assistant_followup: str | None = None


class SetOrderTypeAction(BaseModel):
    intent: Literal["set_order_type"] = "set_order_type"
    order_type: Literal["pickup", "delivery"]
    assistant_followup: str | None = None


class SetCustomerInfoAction(BaseModel):
    intent: Literal["set_customer_info"] = "set_customer_info"
    name: str | None = None
    phone: str | None = None
    address: str | None = None
    assistant_followup: str | None = None


class ConfirmOrderAction(BaseModel):
    intent: Literal["confirm_order"] = "confirm_order"
    assistant_followup: str | None = None


class CancelOrderAction(BaseModel):
    intent: Literal["cancel_order"] = "cancel_order"
    reason: str | None = None
    assistant_followup: str | None = None


class TransferToStaffAction(BaseModel):
    intent: Literal["transfer_to_staff"] = "transfer_to_staff"
    reason: str | None = None
    assistant_followup: str | None = None


Action = Annotated[
    Union[
        AddItemAction,
        ModifyItemAction,
        RemoveItemAction,
        AskClarificationAction,
        AnswerMenuQuestionAction,
        SetOrderTypeAction,
        SetCustomerInfoAction,
        ConfirmOrderAction,
        CancelOrderAction,
        TransferToStaffAction,
    ],
    Field(discriminator="intent"),
]
