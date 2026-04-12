"""Speech-to-text for telephony PCM16 8 kHz — optional faster-whisper or HTTP WAV endpoint."""

from __future__ import annotations

import io
import logging
import wave
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_whisper_model = None


def _get_whisper():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper is not installed. Run: pip install faster-whisper"
        ) from e
    name = (settings.twilio_whisper_model or "tiny").strip()
    logger.info("Loading Whisper model '%s' (first-time may download ~75-150 MB)…", name)
    _whisper_model = WhisperModel(name, device="cpu", compute_type="int8")
    logger.info("Whisper model '%s' loaded successfully.", name)
    return _whisper_model


def warmup_stt() -> None:
    """Pre-load the Whisper model so the first call isn't blocked by a download."""
    backend = (settings.twilio_stream_stt_backend or "off").strip().lower()
    if backend not in ("faster_whisper", "whisper", "faster-whisper"):
        return
    try:
        _get_whisper()
    except Exception:
        logger.exception("Whisper model warm-up failed (STT will retry on first call)")


def pcm16le_wav_bytes(pcm: bytes, sample_rate: int = 8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def transcribe_pcm16_8k(pcm: bytes) -> str | None:
    """
    Return trimmed transcript or None if backend is off / failure / empty audio.
    """
    if not pcm or len(pcm) < 320:
        return None
    backend = (settings.twilio_stream_stt_backend or "off").strip().lower()
    if backend in ("", "off", "none"):
        return None
    if backend == "http":
        return _transcribe_http(pcm)
    if backend in ("faster_whisper", "whisper", "faster-whisper"):
        return _transcribe_faster_whisper(pcm)
    logger.warning("Unknown twilio_stream_stt_backend: %s", backend)
    return None


def _transcribe_http(pcm: bytes) -> str | None:
    url = (settings.twilio_stt_http_url or "").strip()
    if not url:
        logger.warning("twilio_stt_http_url not set")
        return None
    wav = pcm16le_wav_bytes(pcm)
    try:
        with httpx.Client(timeout=settings.twilio_stt_http_timeout_seconds) as client:
            r = client.post(url, files={"file": ("chunk.wav", wav, "audio/wav")})
            r.raise_for_status()
            data = r.json()
    except Exception:
        logger.exception("HTTP STT request failed")
        return None
    text = data.get("text") if isinstance(data, dict) else None
    if isinstance(text, str) and text.strip():
        return text.strip()
    return None


def _transcribe_faster_whisper(pcm: bytes) -> str | None:
    try:
        import numpy as np
    except ImportError as e:
        raise RuntimeError("numpy required for faster-whisper path") from e
    model = _get_whisper()
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if audio.size < 160:
        return None
    try:
        segments, _info = model.transcribe(
            audio,
            language="en",
            vad_filter=True,
            beam_size=1,
        )
        parts = [s.text.strip() for s in segments if s.text and s.text.strip()]
    except Exception:
        logger.exception("faster-whisper transcribe failed")
        return None
    if not parts:
        return None
    return " ".join(parts).strip()


def describe_stt_backend() -> str:
    return (settings.twilio_stream_stt_backend or "off").strip().lower()
