# Twilio Media Streams → KitchenCall cart (Ticket 1)

Inbound calls can stream **8 kHz mu-law** audio to `WS /telephony/twilio/media`. When STT is enabled, utterances are transcribed and fed through **`execute_process_turn`** — the same orchestration as the dashboard (`POST /sessions/{id}/process-turn`).

## 1. Twilio Console

1. **Voice webhook** (incoming call): `POST https://<api>/telephony/twilio/inbound` (HTTP, not WS).
2. **Stream URL** (when using `stream` mode): `wss://<api>/telephony/twilio/media` — Twilio requires **TLS** on the public internet (ngrok / Cloudflare / your host).
3. Set API env:
   - `KITCHENCALL_TWILIO_BRIDGE_MODE=stream`
   - `KITCHENCALL_TWILIO_MEDIA_STREAM_URL=wss://<same-host>/telephony/twilio/media`

## 2. Speech-to-text (pick one)

| Backend | Env | Notes |
|--------|-----|--------|
| **Off** | `KITCHENCALL_TWILIO_STREAM_STT_BACKEND=off` (default) | Only logs stream lifecycle; no cart updates from audio. |
| **faster-whisper** | `=faster_whisper` | Local OSS. Install: `pip install -r apps/api/requirements-telephony.txt`. Tune `KITCHENCALL_TWILIO_WHISPER_MODEL` (`tiny`, `base`, …). CPU-only; first load downloads weights. |
| **HTTP** | `=http` + `KITCHENCALL_TWILIO_STT_HTTP_URL` | `POST` multipart field `file` with a WAV (`audio/wav`). Response JSON: `{"text":"..."}`. Use your own Whisper server, etc. |

## 3. Utterance segmentation

Audio is buffered until **RMS silence** (~`KITCHENCALL_TWILIO_UTTERANCE_SILENCE_MS`) or **max duration** (`KITCHENCALL_TWILIO_UTTERANCE_MAX_MS`). Adjust `KITCHENCALL_TWILIO_UTTERANCE_RMS_THRESHOLD` if you see clipping or background noise.

## 4. Outbound voice (caller hears the assistant)

Use **`KITCHENCALL_TWILIO_STREAM_TRACK=both_tracks`** (default) so Twilio sends **inbound** audio for STT and accepts **outbound** mu-law on the same stream.

The API encodes assistant replies as **8 kHz mu-law** frames (via **`ffmpeg`**) after optional local TTS (`say` on macOS, `espeak-ng` / `espeak`, or `pyttsx3`). Control with:

- `KITCHENCALL_TWILIO_STREAM_TTS_BACKEND` — `auto` (on when STT is on), `on`, or `off`
- `KITCHENCALL_TWILIO_VOICE_GREETING` — optional text for the TwiML `<Say>` **before** `<Connect><Stream>` (empty = built-in ordering intro)

**Requirement:** `ffmpeg` must be installed and on `PATH`. Verify locally: `python3 poc/scripts/verify_twilio_tts_local.py`.

A short **ordering greeting** also plays from TwiML before the media stream connects; assistant **turn** replies use the stream outbound path when TTS is enabled.

## 5. Verify without a phone

```bash
python3 poc/scripts/verify_twilio_mapping.py --base http://127.0.0.1:8000
```

WebSocket behaviour is covered in API tests with STT mocked.
