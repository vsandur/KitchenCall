#!/usr/bin/env python3
"""Verify ffmpeg + local TTS (say / espeak / pyttsx3) can build 8 kHz mu-law for Twilio."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--text", default="Hello. I'm ready to take your order.")
    args = p.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    api_root = repo_root / "apps" / "api"
    sys.path.insert(0, str(api_root))

    from app.services.twilio_tts_synth import synthesize_speech_to_mulaw

    out = synthesize_speech_to_mulaw(args.text)
    if not out:
        print("FAIL: no mu-law produced (install ffmpeg; on macOS use `say`, or espeak-ng, or pip install pyttsx3)")
        return 1
    print("OK: mu-law bytes", len(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
