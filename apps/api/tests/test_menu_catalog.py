from pathlib import Path

import pytest

from app.services.menu_catalog import MenuCatalog, MenuValidationError, validate_line_against_menu

_MENU = Path(__file__).resolve().parent.parent / "data" / "menu.json"


@pytest.fixture
def catalog() -> MenuCatalog:
    return MenuCatalog.load(_MENU)


def test_validate_pepperoni_medium_ok(catalog: MenuCatalog) -> None:
    validate_line_against_menu(
        catalog,
        "pizza_pepperoni",
        "medium",
        ["extra cheese"],
    )


def test_unknown_item(catalog: MenuCatalog) -> None:
    with pytest.raises(MenuValidationError, match="Unknown"):
        validate_line_against_menu(catalog, "not_real", "large", [])


def test_size_required(catalog: MenuCatalog) -> None:
    with pytest.raises(MenuValidationError, match="Size required"):
        validate_line_against_menu(catalog, "pizza_pepperoni", None, [])


def test_invalid_modifier(catalog: MenuCatalog) -> None:
    with pytest.raises(MenuValidationError, match="Modifier not allowed"):
        validate_line_against_menu(catalog, "pizza_pepperoni", "large", ["unicorn dust"])


def test_no_size_when_item_has_no_sizes(catalog: MenuCatalog) -> None:
    validate_line_against_menu(catalog, "sandwich_chicken", None, ["no mayo"])
