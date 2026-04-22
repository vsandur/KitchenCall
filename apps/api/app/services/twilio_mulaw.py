"""Mu-law (G.711) to PCM-16 LE helpers for Twilio Media Streams."""

from __future__ import annotations

import math
import struct


def _linear_sample_to_ulaw_byte(sample: int) -> int:
    """PCM-16 signed ? G.711 mu-law byte (ITU-T)."""
    bias = 0x84
    max_v = 0x7FFF
    sign = 0
    if sample < 0:
        sign = 0x80
        sample = -sample
    if sample > max_v:
        sample = max_v
    sample += bias
    exponent = 7
    mask = 0x4000
    while exponent > 0 and not (sample & mask):
        exponent -= 1
        mask >>= 1
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


def pcm16_le_to_mulaw(pcm: bytes) -> bytes:
    """Encode PCM-16 LE mono bytes to mu-law (8 kHz)."""
    out = bytearray(len(pcm) // 2)
    for i in range(0, len(pcm) - 1, 2):
        s = int.from_bytes(pcm[i : i + 2], "little", signed=True)
        out[i // 2] = _linear_sample_to_ulaw_byte(s)
    return bytes(out)


def mulaw_payload_to_pcm16_le(mulaw: bytes) -> bytes:
    """Decode raw mu-law octets (8 kHz) to little-endian PCM-16."""
    out = bytearray(len(mulaw) * 2)
    for i, byte in enumerate(mulaw):
        sample = _mulaw_byte_to_linear(byte)
        struct.pack_into("<h", out, i * 2, sample)
    return bytes(out)


def _mulaw_byte_to_linear(u: int) -> int:
    """ITU-T G.711 mu-law decode to signed 16-bit."""
    u = ~u & 0xFF
    sign = u & 0x80
    exponent = (u >> 4) & 0x07
    mantissa = u & 0x0F
    magnitude = (((mantissa << 3) + 0x84) << exponent) - 0x84
    sample = magnitude if not sign else -magnitude
    if sample > 32767:
        sample = 32767
    if sample < -32768:
        sample = -32768
    return sample


def pcm16_tone_ms_to_mulaw(*, duration_ms: float, frequency_hz: float = 880.0, sample_rate: int = 8000) -> bytes:
    """Generate mu-law @ sample_rate for a sine tone (Twilio outbound path sanity check)."""
    n = max(1, int(sample_rate * duration_ms / 1000.0))
    pcm = bytearray(n * 2)
    amp = 10000
    for i in range(n):
        s = int(amp * math.sin(2 * math.pi * frequency_hz * i / sample_rate))
        s = max(-32767, min(32767, s))
        struct.pack_into("<h", pcm, i * 2, s)
    return pcm16_le_to_mulaw(bytes(pcm))


def rms_pcm16_le(pcm: bytes) -> float:
    """RMS of PCM-16 LE mono buffer."""
    if len(pcm) < 2:
        return 0.0
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    ss = 0.0
    for i in range(0, n * 2, 2):
        v = struct.unpack_from("<h", pcm, i)[0]
        ss += float(v) * float(v)
    return math.sqrt(ss / n)
