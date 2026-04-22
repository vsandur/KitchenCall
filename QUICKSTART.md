# KitchenCall Quick Start

This guide gets KitchenCall + PersonaPlex + Twilio phone calls working with a single command.

## Prerequisites

1. **Python 3.12** (PersonaPlex requirement)
2. **Cloudflared** (for public tunnel): `brew install cloudflare/cloudflare/cloudflared`
3. **ffmpeg** (for audio): `brew install ffmpeg`
4. **Hugging Face token** with access to `nvidia/personaplex-7b-v1`
5. **Twilio account** with a phone number

## First-time Setup

### 1. Install Dependencies

```bash
# API dependencies
cd apps/api
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-telephony.txt
deactivate

# PersonaPlex dependencies
cd ../personaplex
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install --no-cache-dir "torch>=2.4,<2.8"  # Compatible version
deactivate
cd ../..
```

### 2. Configure Environment

Edit `apps/api/.env`:

```bash
# Required: Hugging Face token for PersonaPlex
HF_TOKEN=hf_your_token_here

# PersonaPlex settings (defaults are fine)
KITCHENCALL_PERSONAPLEX_ENABLED=true
KITCHENCALL_PERSONAPLEX_WS_URL=ws://localhost:8998/api/chat
KITCHENCALL_PERSONAPLEX_VOICE=NATF2

# Twilio bridge mode
KITCHENCALL_TWILIO_BRIDGE_MODE=stream

# Media Stream URL (auto-configured by start-services.sh)
KITCHENCALL_TWILIO_MEDIA_STREAM_URL=wss://placeholder.trycloudflare.com/telephony/twilio/media

# STT backend
KITCHENCALL_TWILIO_STREAM_STT_BACKEND=faster_whisper
KITCHENCALL_TWILIO_WHISPER_MODEL=tiny
```

### 3. Accept PersonaPlex Model License

Visit https://huggingface.co/nvidia/personaplex-7b-v1 and accept the license.

## Running KitchenCall

### Start All Services (Single Command)

```bash
./start-services.sh
```

This script:
- Stops any existing services
- Starts a cloudflared tunnel with a fresh public URL
- Automatically updates `.env` with the new tunnel URL
- Starts PersonaPlex (port 8998)
- Starts KitchenCall API (port 8000)
- Runs health checks
- Shows you the webhook URL for Twilio

**Output example:**

```
==========================================
KitchenCall Services Status
==========================================
Tunnel:      ✓ Running
  URL:       https://example-abc-xyz.trycloudflare.com
PersonaPlex: ✓ Running (8998)
API:         ✓ Running (8000)
PP Probe:    ✓ Handshake OK
==========================================

Webhook URL for Twilio Console:
  https://example-abc-xyz.trycloudflare.com/telephony/twilio/inbound
```

### Configure Twilio

1. Go to [Twilio Console → Phone Numbers](https://console.twilio.com/us1/develop/phone-numbers/manage/incoming)
2. Click your phone number
3. Under **Voice & Fax → A call comes in**:
   - **Webhook**: paste the URL from the script output
   - **HTTP POST**
4. Save

### Stop All Services

```bash
./stop-services.sh
```

## Testing

### 1. Call Your Twilio Number

From your verified phone (trial) or any phone (paid account), call your Twilio number.

You should:
- Hear PersonaPlex's natural voice greeting
- Be able to place an order by speaking
- Have your order processed in real-time

### 2. Monitor Logs

```bash
# API logs
tail -f /tmp/kitchencall-api.log

# PersonaPlex logs
tail -f /tmp/personaplex.log

# Tunnel logs
tail -f /tmp/cloudflared-kc.log
```

### 3. Check Dashboard

Open the web dashboard to see live sessions:

```bash
cd apps/web
npm install
npm run dev
# Open http://localhost:5173
```

## Troubleshooting

### "Application error has occurred" on phone

**Cause:** Twilio webhook URL is stale or unreachable.

**Fix:**
1. Run `./start-services.sh` again (generates new tunnel URL)
2. Update Twilio Console webhook with the new URL shown in output
3. Test: `curl https://your-tunnel-url.trycloudflare.com/health`

### PersonaPlex probe fails

**Symptoms:** Script shows `PP Probe: ✗ Failed`

**Fix:**
```bash
# Check PersonaPlex log
tail -30 /tmp/personaplex.log

# Common causes:
# - torch import error → reinstall torch: apps/personaplex/.venv/bin/pip install --no-cache-dir "torch>=2.4,<2.8"
# - HF_TOKEN missing → add to apps/api/.env
# - Model not downloaded → check HF license acceptance
```

### Services won't start

```bash
# Check what's using ports
lsof -nP -iTCP:8000,8998 -sTCP:LISTEN

# Force stop and retry
./stop-services.sh
sleep 2
./start-services.sh
```

### Silent calls (no audio from PersonaPlex)

Check debug status:
```bash
curl https://your-tunnel-url.trycloudflare.com/telephony/twilio/debug-status
```

Verify:
- `personaplex_enabled: true`
- `media_stream_url` matches your tunnel
- API and PersonaPlex logs show audio flowing

## Architecture

```
Caller's Phone
    ↓
Twilio PSTN
    ↓ (webhook on incoming call)
KitchenCall API (port 8000)
    ├─→ PersonaPlex (port 8998) — natural voice conversation
    └─→ Shadow STT pipeline — cart updates, no TTS
         ↓
    Database (SQLite)
         ↓
    Dashboard (port 5173)
```

## Production Notes

**For production use**, replace cloudflared Quick Tunnels with a proper setup:

1. **Named cloudflared tunnel** (persistent hostname)
2. **ngrok with static domain** (free tier includes one)
3. **Proper domain + TLS** (e.g., api.yourrestaurant.com)

Quick Tunnels change hostname on every restart, requiring webhook updates. The `start-services.sh` script handles this for local dev but is not suitable for production.

## Next Steps

- Read [docs/twilio-phone-test.md](./docs/twilio-phone-test.md) for detailed Twilio setup
- See [docs/architecture.md](./docs/architecture.md) for system design
- Check [docs/poc-checklist.md](./docs/poc-checklist.md) for POC scope
