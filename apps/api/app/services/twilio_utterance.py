"""Buffer Twilio 8 kHz mu-law chunks; flush on fixed interval or silence."""

from __future__ import annotations

import logging

from app.services.twilio_mulaw import mulaw_payload_to_pcm16_le, rms_pcm16_le

logger = logging.getLogger(__name__)

# Mu-law 0xFF (digital silence) decodes to PCM ±124 → RMS ~124.
_MULAW_SILENCE_RMS = 140.0


class UtteranceBuffer:
    """
    Simple time-based chunking with silence detection.
    Accumulates PCM and flushes every `max_ms` milliseconds unconditionally,
    OR earlier if a quiet gap (`silence_ms`) follows any non-silent audio.
    Whisper decides whether the audio actually contains speech.
    """

    def __init__(
        self,
        *,
        silence_ms: int = 1200,
        max_ms: int = 5_000,
        chunk_ms: int = 20,
        rms_threshold: float = 500.0,
        silence_chunks: int | None = None,
    ) -> None:
        self._rms_threshold = max(rms_threshold, _MULAW_SILENCE_RMS + 20)
        sc = silence_chunks if silence_chunks is not None else max(1, silence_ms // max(1, chunk_ms))
        self._silence_chunks = sc
        self._max_chunks = max(1, max_ms // max(1, chunk_ms))
        self._bytes_per_chunk = 160 * 2

        self._pcm = bytearray()
        self._chunks = 0
        self._low_rms_streak = 0
        self._ever_voice = False
        self._total_chunks = 0

    def add_mulaw(self, mulaw: bytes) -> bytes | None:
        if not mulaw:
            return None
        pcm = mulaw_payload_to_pcm16_le(mulaw)
        rms = rms_pcm16_le(pcm)
        self._total_chunks += 1
        self._chunks += 1

        if self._total_chunks <= 5 or self._total_chunks % 500 == 0:
            logger.info(
                "utterance chunk=%d rms=%.0f threshold=%.0f voice=%s chunks_buf=%d",
                self._total_chunks, rms, self._rms_threshold,
                self._ever_voice, self._chunks,
            )

        if rms >= self._rms_threshold:
            self._ever_voice = True
            self._low_rms_streak = 0
        else:
            self._low_rms_streak += 1

        self._pcm.extend(pcm)

        # Always flush at max duration — let Whisper decide if there's speech
        if self._chunks >= self._max_chunks:
            logger.info(
                "utterance_flush reason=max_duration chunks=%d voice=%s",
                self._chunks, self._ever_voice,
            )
            return self._take_utterance()

        # Early flush on silence after detected voice
        if self._ever_voice and self._low_rms_streak >= self._silence_chunks:
            logger.info(
                "utterance_flush reason=silence chunks=%d",
                self._chunks,
            )
            return self._take_utterance()

        return None

    def flush(self) -> bytes | None:
        """Force-flush on stream end — always return audio if we have any."""
        if not self._pcm:
            self._reset()
            return None
        logger.info("utterance_flush reason=stream_end chunks=%d", self._chunks)
        return self._take_utterance()

    def reset(self) -> None:
        self._reset()

    def _take_utterance(self) -> bytes:
        raw = bytes(self._pcm)
        self._reset()
        return raw

    def _reset(self) -> None:
        self._pcm.clear()
        self._chunks = 0
        self._low_rms_streak = 0
        self._ever_voice = False
