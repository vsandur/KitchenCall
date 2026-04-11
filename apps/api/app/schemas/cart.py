from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Customer(BaseModel):
    name: str | None = None
    phone: str | None = None
    address: str | None = None


class LineItem(BaseModel):
    id: str
    menu_item_id: str
    name: str
    size: str | None = None
    qty: int = Field(ge=1, default=1)
    modifiers: list[str] = Field(default_factory=list)
    special_instructions: str | None = None


OrderStatus = Literal["building", "confirming", "completed", "cancelled"]
OrderType = Literal["pickup", "delivery"]


class OrderMetadata(BaseModel):
    missing_info: list[str] = Field(default_factory=list)
    last_action: str | None = None
    status: OrderStatus = "building"


class Cart(BaseModel):
    order_id: str
    customer: Customer = Field(default_factory=Customer)
    order_type: OrderType = "pickup"
    items: list[LineItem] = Field(default_factory=list)
    metadata: OrderMetadata = Field(default_factory=OrderMetadata)
