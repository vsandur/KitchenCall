"""
LiveKit agent: subscribe to user audio, run STT, call KitchenCall API, speak assistant_response.

Room name must be ``kc-{kitchencall_session_id}`` (same convention as POST /livekit/token).

Environment:
  LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET — worker registration
  KITCHENCALL_API_BASE — e.g. http://127.0.0.1:8000
  KITCHENCALL_STT_BACKEND — "kyutai" (default) or "inference"
  KITCHENCALL_TTS_BACKEND — "inference" (default)
  KITCHENCALL_STT_MODEL — LiveKit Inference model for STT fallback
  KITCHENCALL_TTS_MODEL, KITCHENCALL_TTS_VOICE — LiveKit Inference TTS settings
  KYUTAI_API_KEY + KYUTAI_BASE_URL — for Kyutai/Moshi STT backend

Run (from apps/agent, venv active):
  python -m kitchencall_agent.worker dev
"""

from __future__ import annotations

import os
import re
import sys
import json
import threading
import time
from typing import Final

import httpx
from livekit.agents import AgentServer, JobContext, cli, inference
from livekit.agents.llm import ChatMessage
from livekit.agents.log import logger
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import silero

ROOM_PREFIX: Final[str] = "kc-"
SESSION_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def session_id_from_room(room_name: str) -> str | None:
    if not room_name.startswith(ROOM_PREFIX):
        logger.error("room name must start with %s; got %s", ROOM_PREFIX, room_name)
        return None
    sid = room_name[len(ROOM_PREFIX) :]
    if not SESSION_ID_RE.match(sid):
        logger.error("invalid KitchenCall session id in room name: %s", room_name)
        return None
    return sid


def _api_base() -> str:
    return os.environ.get("KITCHENCALL_API_BASE", "http://127.0.0.1:8000").rstrip("/")


def _stt_backend() -> str:
    return os.environ.get("KITCHENCALL_STT_BACKEND", "kyutai").strip().lower()


def _tts_backend() -> str:
    return os.environ.get("KITCHENCALL_TTS_BACKEND", "inference").strip().lower()


def _heartbeat_path() -> str:
    return os.environ.get("KITCHENCALL_AGENT_HEARTBEAT_PATH", "/tmp/kitchencall-agent-heartbeat.json")


def _heartbeat_interval_seconds() -> float:
    try:
        return max(1.0, float(os.environ.get("KITCHENCALL_AGENT_HEARTBEAT_INTERVAL_SECONDS", "5")))
    except ValueError:
        return 5.0


def _write_heartbeat() -> None:
    path = _heartbeat_path()
    payload = {
        "service": "kitchencall-agent",
        "pid": os.getpid(),
        "updated_at_epoch_s": time.time(),
        "stt_backend": _stt_backend(),
        "tts_backend": _tts_backend(),
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        logger.exception("Failed to write heartbeat", extra={"heartbeat_path": path})


def start_heartbeat_thread() -> None:
    interval = _heartbeat_interval_seconds()
    _write_heartbeat()

    def _run() -> None:
        while True:
            time.sleep(interval)
            _write_heartbeat()

    thread = threading.Thread(target=_run, name="kitchencall-heartbeat", daemon=True)
    thread.start()


def validate_runtime_config() -> list[str]:
    """Return config errors; empty list means startup config is valid."""
    errors: list[str] = []
    if not os.environ.get("LIVEKIT_URL"):
        errors.append("LIVEKIT_URL is required")
    if not os.environ.get("LIVEKIT_API_KEY"):
        errors.append("LIVEKIT_API_KEY is required")
    if not os.environ.get("LIVEKIT_API_SECRET"):
        errors.append("LIVEKIT_API_SECRET is required")

    api_base = _api_base()
    if not api_base.startswith(("http://", "https://")):
        errors.append("KITCHENCALL_API_BASE must start with http:// or https://")

    stt_backend = _stt_backend()
    if stt_backend not in {"kyutai", "inference"}:
        errors.append("KITCHENCALL_STT_BACKEND must be 'kyutai' or 'inference'")
    if stt_backend == "kyutai" and not os.environ.get("KYUTAI_API_KEY"):
        errors.append("KYUTAI_API_KEY is required when KITCHENCALL_STT_BACKEND=kyutai")

    tts_backend = _tts_backend()
    if tts_backend not in {"inference"}:
        errors.append("KITCHENCALL_TTS_BACKEND must be 'inference'")

    return errors


def ensure_runtime_config() -> None:
    errors = validate_runtime_config()
    if errors:
        raise RuntimeError("Invalid worker configuration:\n- " + "\n- ".join(errors))


def run_check_mode() -> int:
    """Validate env/config and return shell exit code."""
    errors = validate_runtime_config()
    if errors:
        print("KitchenCall worker config check: FAILED")
        for err in errors:
            print(f"- {err}")
        return 1
    print("KitchenCall worker config check: OK")
    return 0


def _inference_stt():
    model = os.environ.get("KITCHENCALL_STT_MODEL", "deepgram/flux-general")
    language = os.environ.get("KITCHENCALL_STT_LANGUAGE", "en")
    logger.info("Using LiveKit Inference STT backend (model=%s, language=%s)", model, language)
    return inference.STT(model=model, language=language)


def _inference_tts():
    model = os.environ.get("KITCHENCALL_TTS_MODEL", "cartesia/sonic-2")
    voice = os.environ.get(
        "KITCHENCALL_TTS_VOICE",
        "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
    )
    language = os.environ.get("KITCHENCALL_TTS_LANGUAGE", "en")
    logger.info("Using LiveKit Inference TTS backend (model=%s, voice=%s)", model, voice)
    return inference.TTS(model=model, voice=voice, language=language)


def _build_stt():
    backend = _stt_backend()
    if backend == "inference":
        return _inference_stt()

    if backend == "kyutai":
        try:
            from lasuite.plugins import kyutai
        except Exception:
            logger.warning("Kyutai plugin unavailable; falling back to LiveKit Inference STT")
            return _inference_stt()

        base_url = os.environ.get("KYUTAI_BASE_URL", "ws://127.0.0.1:8080/api/asr-streaming")
        try:
            logger.info("Using Kyutai/Moshi STT backend (%s)", base_url)
            return kyutai.STT(base_url=base_url)
        except Exception:
            logger.warning("Failed to initialize Kyutai/Moshi STT; falling back to LiveKit Inference STT")
            return _inference_stt()

    logger.warning("Unknown STT backend %r, using LiveKit Inference STT", backend)
    return _inference_stt()


def _build_tts():
    backend = _tts_backend()
    if backend == "inference":
        return _inference_tts()
    logger.warning("Unknown/unsupported TTS backend %r, using LiveKit Inference TTS", backend)
    return _inference_tts()


class KitchenCallAgent(Agent):
    """No LLM: final user text is sent to the KitchenCall HTTP API; replies are spoken with TTS."""

    def __init__(self, *, kitchencall_session_id: str, api_base: str) -> None:
        self._kc_session_id = kitchencall_session_id
        self._kc_api_base = api_base
        self._http = httpx.AsyncClient(timeout=60.0)
        super().__init__(
            instructions="KitchenCall restaurant ordering. Cart and menu logic are handled by the API.",
            stt=_build_stt(),
            vad=silero.VAD.load(),
            tts=_build_tts(),
        )

    async def on_user_turn_completed(self, _turn_ctx, new_message: ChatMessage) -> None:
        text = (new_message.text_content or "").strip()
        if not text:
            return
        url = f"{self._kc_api_base}/sessions/{self._kc_session_id}/process-turn"
        try:
            response = await self._http.post(url, json={"text": text})
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            logger.warning("KitchenCall API HTTP error: %s", e)
            self.session.say("Sorry, the order system returned an error. Please try again.")
            return
        except Exception:
            logger.exception("KitchenCall API request failed")
            self.session.say("Sorry, I could not reach the order system. Please try again.")
            return

        reply = (data.get("assistant_response") or "").strip()
        if reply:
            self.session.say(reply)

    async def on_exit(self) -> None:
        await self._http.aclose()


server = AgentServer()


@server.rtc_session(agent_name="kitchencall")
async def entrypoint(ctx: JobContext) -> None:
    room_name = ctx.job.room.name
    session_id = session_id_from_room(room_name)
    if session_id is None:
        logger.error("refusing job: could not parse KitchenCall session from room %r", room_name)
        return

    api_base = _api_base()
    logger.info("KitchenCall agent job room=%r session_id=%s api=%s", room_name, session_id, api_base)

    session = AgentSession(preemptive_generation=False)
    agent = KitchenCallAgent(kitchencall_session_id=session_id, api_base=api_base)
    await session.start(agent=agent, room=ctx.room)


def main() -> None:
    if "--check" in sys.argv:
        raise SystemExit(run_check_mode())
    ensure_runtime_config()
    start_heartbeat_thread()
    cli.run_app(server)


if __name__ == "__main__":
    main()
