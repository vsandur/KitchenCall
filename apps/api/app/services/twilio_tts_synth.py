"""Synthesize short assistant text to 8 kHz mu-law (Twilio Media Streams outbound)."""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_CHARS = 600


def _which(name: str) -> str | None:
    return shutil.which(name)


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: float = 120.0) -> None:
    subprocess.run(cmd, check=True, capture_output=True, cwd=cwd, timeout=timeout)


def synthesize_speech_to_mulaw(text: str) -> bytes | None:
    """
    Produce raw mu-law mono 8 kHz bytes for Twilio outbound `media` payloads.
    Requires **ffmpeg** on PATH. Speech source (first available):
    macOS `say`, `espeak-ng`, `espeak`, or Python **pyttsx3**.
    """
    text = (text or "").strip()
    if not text:
        return None
    if len(text) > _MAX_CHARS:
        text = text[: _MAX_CHARS - 3] + "..."

    ffmpeg = _which("ffmpeg")
    if not ffmpeg:
        logger.error("twilio_tts: ffmpeg not found on PATH; install ffmpeg for phone replies")
        return None

    try:
        with tempfile.TemporaryDirectory(prefix="kc_tts_") as d:
            dpath = Path(d)
            words = dpath / "words.txt"
            words.write_text(text, encoding="utf-8")
            in_audio: Path | None = None

            if platform.system() == "Darwin" and _which("say"):
                in_audio = dpath / "in.aiff"
                _run(["say", "-f", str(words), "-o", str(in_audio)])
            elif _which("espeak-ng"):
                in_audio = dpath / "in.wav"
                _run(["espeak-ng", "-f", str(words), "-w", str(in_audio), "-s", "150"])
            elif _which("espeak"):
                in_audio = dpath / "in.wav"
                _run(["espeak", "-f", str(words), "-w", str(in_audio), "-s", "150"])
            else:
                try:
                    import pyttsx3  # type: ignore[import-untyped]

                    in_audio = dpath / "in.wav"
                    engine = pyttsx3.init()
                    engine.save_to_file(text, str(in_audio))
                    engine.runAndWait()
                    if not in_audio.exists() or in_audio.stat().st_size < 200:
                        in_audio = None
                except Exception:
                    logger.exception("twilio_tts: pyttsx3 failed")
                    in_audio = None

            if in_audio is None or not in_audio.exists():
                logger.error("twilio_tts: no local TTS engine (say / espeak / pyttsx3)")
                return None

            out_mulaw = dpath / "out.mulaw"
            _run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(in_audio),
                    "-ar",
                    "8000",
                    "-ac",
                    "1",
                    "-f",
                    "mulaw",
                    "-acodec",
                    "pcm_mulaw",
                    str(out_mulaw),
                ]
            )
            data = out_mulaw.read_bytes()
            return data if data else None
    except subprocess.CalledProcessError as e:
        logger.error("twilio_tts: ffmpeg/say failed: %s", e.stderr[-500:] if e.stderr else e)
        return None
    except Exception:
        logger.exception("twilio_tts: synthesis failed")
        return None
