# Hosting the KitchenCall API

The API is one **FastAPI** app: `uvicorn app.main:app` on port **8000**. It uses **SQLite** and must stay **one writable database** per deployment.

## Quick decision

| Your goal | Reasonable choice |
|-----------|-------------------|
| **Local dev** (recommended for POC) | `uvicorn` + **Cloudflare Tunnel** — see below |
| **Try Twilio from your laptop** | Same as above — tunnel gives you HTTPS + WSS |
| **Always-on demo** | **VPS** + Docker + reverse proxy (Caddy/nginx) |
| **Managed PaaS** | Fly.io, Railway, Render — needs WebSocket support |

**Avoid** serverless stacks that don't support long-lived WebSockets — Twilio keeps a WSS open for the call.

## Option A — Local + Cloudflare Tunnel (recommended)

Best for development and demos. Runs on your Mac, no cloud costs.

1. Start the API:

   ```bash
   cd apps/api && source .venv/bin/activate
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

2. Start a tunnel:

   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```

3. Copy the tunnel URL (e.g. `https://xyz.trycloudflare.com`) and set:

   - `.env`: `KITCHENCALL_TWILIO_MEDIA_STREAM_URL=wss://xyz.trycloudflare.com/telephony/twilio/media`
   - Twilio webhook: `https://xyz.trycloudflare.com/telephony/twilio/inbound`

4. For phone audio, install `ffmpeg` and `faster-whisper`:

   ```bash
   brew install ffmpeg
   pip install faster-whisper
   ```

**Note:** Free tunnel URLs change on restart. For stable URLs, use a Cloudflare account or ngrok with a reserved domain.

## Option B — Docker on a VPS

```bash
docker compose -f infra/docker-compose.yml up --build -d
```

- Binds port 8000; put Caddy or nginx in front for TLS.
- Compose file mounts `apps/api/data` so SQLite survives restarts.
- Both Dockerfiles include `ffmpeg`, `espeak-ng`, and telephony deps.

## Option C — Managed PaaS

General checklist:

1. **Dockerfile** — use the repo-root `Dockerfile` (cloud STT via Deepgram) or `apps/api/Dockerfile` (local Whisper).
2. **Start command** — `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. **Persistent volume** — mount at `/app/data` for SQLite.
4. **WebSockets** — must be enabled for Twilio Media Streams.
5. **Env vars** — copy from `apps/api/.env.example`.

**Cloud STT note:** The repo-root Dockerfile defaults to `deepgram` STT backend. Set `KITCHENCALL_STT_API_KEY` in your platform's env vars. Free tier CPUs are too weak for local Whisper.

## After it's up

- Open `/docs` (Swagger) on your public URL.
- Debug: `GET /telephony/twilio/debug-status`
- Call test: [twilio-phone-test.md](./twilio-phone-test.md)

## CORS (dashboard)

If the web app is on another origin, set:

```
KITCHENCALL_CORS_ORIGINS=https://your-dashboard.example
```
