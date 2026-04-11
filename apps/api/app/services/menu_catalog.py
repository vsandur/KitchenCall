from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ModifierGroup(BaseModel):
    id: str
    name: str
    options: list[str] = Field(default_factory=list)
    required: bool = False
    max_select: int | None = None


class MenuItemDef(BaseModel):
    id: str
    name: str
    category: str
    sizes: list[str] = Field(default_factory=list)
    modifiers_available: list[str] = Field(default_factory=list)
    modifier_groups: list[ModifierGroup] = Field(default_factory=list)
    unavailable: bool = False


class MenuCatalog(BaseModel):
    restaurant_name: str = "Demo Restaurant"
    items: dict[str, MenuItemDef]

    @classmethod
    def load(cls, path: Path) -> MenuCatalog:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls.model_validate(raw)


class MenuValidationError(Exception):
    def __init__(self, message: str, *, code: str = "menu_validation"):
        super().__init__(message)
        self.code = code


def validate_line_against_menu(
    catalog: MenuCatalog,
    menu_item_id: str,
    size: str | None,
    modifiers: list[str],
) -> None:
    """Raise MenuValidationError if the line is not allowed by the catalog."""
    item = catalog.items.get(menu_item_id)
    if not item:
        raise MenuValidationError(f"Unknown menu_item_id: {menu_item_id}", code="unknown_item")
    if item.unavailable:
        raise MenuValidationError(f"Item unavailable: {item.name}", code="unavailable")
    if item.sizes and not size:
        raise MenuValidationError(f"Size required for {item.name}", code="size_required")
    if size and item.sizes and size not in item.sizes:
        raise MenuValidationError(f"Invalid size '{size}' for {item.name}", code="invalid_size")

    allowed = set(item.modifiers_available)
    for m in modifiers:
        normalized = m.strip().lower()
        if not allowed:
            continue
        if not any(a.lower() == normalized for a in allowed):
            raise MenuValidationError(f"Modifier not allowed: {m}", code="invalid_modifier")


def item_display_name(catalog: MenuCatalog, menu_item_id: str) -> str:
    item = catalog.items.get(menu_item_id)
    return item.name if item else menu_item_id
