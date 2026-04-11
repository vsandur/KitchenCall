"""Run one STT + process-turn cycle for a phone utterance (blocking; call via asyncio.to_thread)."""

from __future__ import annotations

import logging

from app.config import settings
from app.db import repo
from app.db.database import get_session_factory
from app.services.logic_loop import is_affirmation
from app.services.menu_catalog import MenuCatalog
from app.services.session_finalize import finalize_session_core
from app.services.session_turn import execute_process_turn
from app.services.telephony_stt import transcribe_pcm16_8k

logger = logging.getLogger(__name__)


def run_telephony_utterance(session_id: str, pcm16_8k_le: bytes) -> str | None:
    """
    Transcribe PCM, run the same process-turn as the dashboard, persist transcripts.
    Returns assistant spoken reply text (for outbound TTS), or None.
    """
    text = transcribe_pcm16_8k(pcm16_8k_le)
    if not text or not text.strip():
        return None
    db = get_session_factory()()
    try:
        if repo.get_session_row(db, session_id) is None:
            logger.warning("telephony: session not found %s", session_id)
            return None
        catalog = MenuCatalog.load(settings.menu_path)
        norm = text.strip()
        _cart, _errors, _intents, _xfer, assistant_response = execute_process_turn(
            db, session_id, norm, catalog
        )
        logger.info("telephony_stt_turn session_id=%s text=%s", session_id, text[:240])
        if _cart.metadata.status == "confirming" and is_affirmation(norm):
            try:
                finalize_session_core(db, session_id)
                assistant_response = "Your order is placed. Thank you!"
            except (KeyError, ValueError, RuntimeError):
                logger.exception(
                    "telephony voice finalize failed session_id=%s", session_id
                )
        return assistant_response
    except ValueError:
        logger.warning("telephony: session gone mid-turn %s", session_id)
        return None
    except Exception:
        logger.exception("telephony process-turn failed session_id=%s", session_id)
        return None
    finally:
        db.close()
