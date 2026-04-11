"""Dispatch transcript extraction: optional local LLM (OpenAI-compatible API), then rules."""

from __future__ import annotations

import logging

from app.config import settings
from app.schemas.cart import Cart
from app.services.logic_loop import extract_actions as extract_actions_rules
from app.services.menu_catalog import MenuCatalog

logger = logging.getLogger(__name__)


def _substantive_transcript(text: str) -> bool:
    """Heuristic: user likely meant something order-related (rules fallback if LLM returns [])."""
    t = text.strip().lower()
    if len(t) < 4:
        return False
    minimal = {
        "hi",
        "hey",
        "hello",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "bye",
        "hm",
        "hmm",
    }
    return t not in minimal


def _llm_extractor_enabled() -> bool:
    ext = settings.logic_extractor.strip().lower()
    if ext not in ("llm", "openai"):
        return False
    key = settings.llm_api_key.strip()
    if key:
        return True
    base = settings.llm_base_url.lower()
    # Local OSS servers (Ollama default) do not require an API key.
    return "127.0.0.1" in base or "localhost" in base or base.startswith("http://0.0.0.0")


def extract_actions_for_turn(text: str, cart: Cart, catalog: MenuCatalog) -> list:
    """
    If KITCHENCALL_LOGIC_EXTRACTOR is llm (or legacy alias openai) and a local/keyed LLM is
    configured, try extraction via OpenAI-compatible chat/completions (e.g. Ollama).
    On failure or mis-parse, fall back to deterministic rules (logic_loop).
    """
    if _llm_extractor_enabled():
        try:
            from app.services.logic_loop_llm import extract_actions_llm

            llm_actions = extract_actions_llm(text, cart, catalog)
            if llm_actions is not None:
                if not llm_actions and _substantive_transcript(text):
                    logger.info("LLM returned no actions for substantive turn; using rules")
                    return extract_actions_rules(text, cart, catalog)
                return llm_actions
        except Exception:
            logger.exception("LLM extractor raised; falling back to rules")
    return extract_actions_rules(text, cart, catalog)
