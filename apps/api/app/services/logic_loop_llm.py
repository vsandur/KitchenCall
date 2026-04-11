"""Optional local/OSS LLM extractor via OpenAI-compatible HTTP API (Ollama, vLLM, LocalAI, etc.)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import settings
from app.schemas.cart import Cart
from app.services.menu_catalog import MenuCatalog
from app.services.state_engine import parse_action

logger = logging.getLogger(__name__)

# Tests patch this to avoid network calls.
_post_chat_completions: Any = None


def _menu_prompt_lines(catalog: MenuCatalog) -> str:
    lines: list[str] = []
    for _mid, it in sorted(catalog.items.items(), key=lambda x: x[0]):
        sizes = ", ".join(it.sizes) if it.sizes else "(no size — omit size or use null)"
        mods = ", ".join(it.modifiers_available) if it.modifiers_available else "none"
        lines.append(
            f"- {it.id}: {it.name} | sizes: {sizes} | allowed modifiers: {mods}"
            + (" | UNAVAILABLE — do not add" if it.unavailable else "")
        )
    return "\n".join(lines)


def _cart_context(cart: Cart) -> dict[str, Any]:
    return {
        "order_type": cart.order_type,
        "metadata_status": cart.metadata.status,
        "items": [
            {
                "line_id": li.id,
                "menu_item_id": li.menu_item_id,
                "name": li.name,
                "size": li.size,
                "qty": li.qty,
                "modifiers": li.modifiers,
            }
            for li in cart.items
        ],
        "customer": cart.customer.model_dump(),
    }


_SYSTEM_PROMPT = """You are a strict order extractor for a phone-ordering assistant. You do NOT chat; you only output JSON.

Return a single JSON object: {"actions":[...]} . Each element of "actions" is one action object with field "intent" (required discriminator).

Allowed intents and required fields:
- add_item: menu_item_id (string from menu), optional name, size (must match menu if item has sizes), qty (int >=1, default 1), modifiers (string array, only from allowed list), special_instructions
- modify_item: target_item_id (must be a line_id from current cart), changes: { size?, qty?, modifiers_add[], modifiers_remove[], menu_item_id?, name?, special_instructions? }
- remove_item: target_item_id
- ask_clarification: question (short, for staff to read aloud)
- set_order_type: order_type "pickup" or "delivery"
- set_customer_info: optional name, phone (digits ok), address
- confirm_order: when user is done ordering (e.g. "that's all", "nothing else") OR affirms the readback ("yes", "sounds good", "correct") while metadata_status is "confirming"
- cancel_order: optional reason
- transfer_to_staff: optional reason — user wants a human
- answer_menu_question: optional topic — only if they ask what's on menu / hours / generic (POC: rarely needed)

Rules:
- Use ONLY menu_item_id values exactly as listed in the menu. Never invent ids.
- If the user wants an item but size is required and missing, use ask_clarification with one clear question.
- For "make it large / actually medium" without naming the item, modify the most recently added line (last in cart items) if unambiguous.
- Emit multiple actions in sensible order (e.g. set_order_type before add_item is fine).
- If the user says nothing order-related, return {"actions":[]}.
- Output ONLY valid JSON, no markdown fences."""


def _post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    poster = _post_chat_completions
    if poster is not None:
        return poster(url, headers, payload)
    with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
        r = client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()


def _message_content(data: dict[str, Any]) -> str | None:
    try:
        raw = data["choices"][0]["message"]["content"]
        return raw if isinstance(raw, str) else None
    except (KeyError, IndexError, TypeError) as e:
        logger.warning("Unexpected chat completion shape: %s", e)
        return None


def _call_llm_chat(messages: list[dict[str, str]]) -> str | None:
    base = settings.llm_base_url.rstrip("/")
    url = f"{base}/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    key = settings.llm_api_key.strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "temperature": 0.1,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    try:
        data = _post_json(url, headers, payload)
        content = _message_content(data)
        if content is not None:
            return content
    except httpx.HTTPStatusError as e:
        # Ollama / some OSS servers reject response_format on older builds or small models.
        if e.response.status_code == 400:
            logger.info("Retrying LLM chat without json response_format (400 from server)")
            try:
                payload.pop("response_format", None)
                data = _post_json(url, headers, payload)
                return _message_content(data)
            except Exception:
                logger.exception("LLM chat retry failed")
                return None
        logger.exception("LLM chat/completions HTTP error")
        return None
    except Exception:
        logger.exception("LLM chat/completions request failed")
        return None
    return None


def extract_actions_llm(text: str, cart: Cart, catalog: MenuCatalog) -> list | None:
    """
    Call a local or remote OpenAI-compatible API to extract actions.
    Returns None on failure (caller should fall back to rule-based extractor).
    """
    stripped = text.strip()
    if not stripped:
        return []

    user_payload = {
        "user_said": stripped,
        "cart": _cart_context(cart),
        "menu": _menu_prompt_lines(catalog),
    }
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "Extract actions from this turn.\n\n" + json.dumps(user_payload, indent=2),
        },
    ]
    raw = _call_llm_chat(messages)
    if raw is None:
        return None

    # Some models return JSON wrapped in markdown fences despite instructions.
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON")
        return None
    actions_raw = obj.get("actions")
    if not isinstance(actions_raw, list):
        logger.warning('LLM JSON missing "actions" array')
        return None

    out: list = []
    for i, row in enumerate(actions_raw):
        if not isinstance(row, dict):
            return None
        try:
            out.append(parse_action(row))
        except Exception as e:
            logger.warning("Invalid action at index %s: %s — %s", i, row, e)
            return None
    return out
