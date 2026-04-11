"""Buffer Twilio 8 kHz mu-law chunks; flush a completed utterance on silence timeout."""

from __future__ import annotations

from app.services.twilio_mulaw import mulaw_payload_to_pcm16_le, rms_pcm16_le


class UtteranceBuffer:
    """
    Twilio typically sends ~20 ms of mu-law per media frame (160 B).
    We accumulate linear PCM16 until RMS stays below threshold for `silence_chunks` frames,
    or `max_pcm_bytes` is reached.
    """

    def __init__(
        self,
        *,
        silence_ms: int = 700,
        max_ms: int = 25_000,
        chunk_ms: int = 20,
        rms_threshold: float = 350.0,
        silence_chunks: int | None = None,
    ) -> None:
        self._rms_threshold = rms_threshold
        sc = silence_chunks if silence_chunks is not None else max(1, silence_ms // max(1, chunk_ms))
        self._silence_chunks = sc
        self._max_pcm = max(1, (max_ms // max(1, chunk_ms)) * 160 * 2)

        self._pcm = bytearray()
        self._low_rms_streak = 0
        self._high_rms_streak = 0
        self._ever_voice = False

    def add_mulaw(self, mulaw: bytes) -> bytes | None:
        """
        Append one frame; return completed utterance PCM16 LE (8 kHz mono) or None.
        """
        if not mulaw:
            return None
        pcm = mulaw_payload_to_pcm16_le(mulaw)
        rms = rms_pcm16_le(pcm)

        if rms >= self._rms_threshold:
            self._high_rms_streak += 1
            self._low_rms_streak = 0
            if self._high_rms_streak >= 2:
                self._ever_voice = True
        else:
            self._low_rms_streak += 1
            self._high_rms_streak = 0

        self._pcm.extend(pcm)

        if len(self._pcm) >= self._max_pcm and self._ever_voice:
            return self._take_utterance()

        if self._ever_voice and self._low_rms_streak >= self._silence_chunks:
            return self._take_utterance()

        return None

    def flush(self) -> bytes | None:
        """Force-flush if we had any voice (e.g. stream stop)."""
        if not self._ever_voice or not self._pcm:
            self._reset()
            return None
        return self._take_utterance()

    def reset(self) -> None:
        """Clear buffer (e.g. before/after assistant TTS to avoid echo bleed)."""
        self._reset()

    def _take_utterance(self) -> bytes:
        raw = bytes(self._pcm)
        self._reset()
        return raw

    def _reset(self) -> None:
        self._pcm.clear()
        self._low_rms_streak = 0
        self._high_rms_streak = 0
        self._ever_voice = False
