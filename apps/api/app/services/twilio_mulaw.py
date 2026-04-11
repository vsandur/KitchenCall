"""G.711 mu-law (8 kHz) to linear PCM16 — Twilio Media Streams inbound payload."""

from __future__ import annotations


def _ulaw_to_linear(mu: int) -> int:
    """ITU-T G.711 mu-law decode to 16-bit signed sample."""
    mu = (~mu) & 0xFF
    sign = mu & 0x80
    exponent = (mu >> 4) & 0x07
    mantissa = mu & 0x0F
    sample = ((mantissa << 4) + 0x08) << exponent
    sample -= 0x84
    if sign:
        sample = -sample
    if sample > 32767:
        return 32767
    if sample < -32768:
        return -32768
    return sample


def mulaw_payload_to_pcm16_le(payload: bytes) -> bytes:
    """Each input byte is one 8-bit mu-law sample; output is little-endian int16."""
    out = bytearray(len(payload) * 2)
    j = 0
    for b in payload:
        s = _ulaw_to_linear(b)
        out[j] = s & 0xFF
        out[j + 1] = (s >> 8) & 0xFF
        j += 2
    return bytes(out)


def rms_pcm16_le(pcm: bytes) -> float:
    """RMS of int16 LE samples (rough voice-activity proxy)."""
    if len(pcm) < 2:
        return 0.0
    n = len(pcm) // 2
    acc = 0
    for i in range(0, len(pcm) - 1, 2):
        v = int.from_bytes(pcm[i : i + 2], "little", signed=True)
        acc += v * v
    return (acc / max(1, n)) ** 0.5
