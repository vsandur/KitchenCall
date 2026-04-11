from functools import lru_cache

from app.config import settings
from app.services.menu_catalog import MenuCatalog


@lru_cache
def get_menu_catalog() -> MenuCatalog:
    return MenuCatalog.load(settings.menu_path)
