# Hosting the KitchenCall API (choose a path)

The “API” is one **FastAPI** app: `uvicorn app.main:app` on port **8000** by default. It uses **SQLite** (`kitchencall.db`) and must stay **one writable database** per deployment unless you change storage later.

Use this page to pick **how** you expose it—especially if **Twilio** needs **HTTPS** + **WSS** on the same public host.

## Quick decision

| Your goal | Reasonable choice |
|-----------|-------------------|
| **Local dev only** (browser dashboard) | `uvicorn` on `127.0.0.1:8000` — [README](../README.md) |
| **Try Twilio from your laptop** | Same `uvicorn` + a **TLS tunnel** (e.g. [ngrok](https://ngrok.com/)) exposing **HTTP and HTTPS** so you can set webhook `https://…` and `wss://…` to the same API |
| **Small always-on demo / restaurant POC** | **One VPS** (DigitalOcean, Hetzner, AWS Lightsail, …) + **Docker** ([`infra/docker-compose.yml`](../infra/docker-compose.yml)) + **reverse proxy + TLS** (Caddy or nginx) |
| **Managed PaaS** (less server ops) | **Fly.io**, **Railway**, **Render**, etc.—pick a platform that allows **WebSockets** and **persistent disk** for SQLite (or you accept ephemeral DB on free tiers) |

**Avoid** for Twilio Media Streams: pure **serverless HTTP-only** stacks that **don’t support long-lived WebSockets** or that **freeze** with no traffic—Twilio keeps a **WSS** open for the call.

## Option A — Laptop + tunnel (fastest for Twilio testing)

1. Run API locally:

   ```bash
   cd apps/api && source .venv/bin/activate
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

2. Start a tunnel that gives you **HTTPS** (ngrok example):

   ```bash
   ngrok http 8000
   ```

3. In Twilio and in `.env`:

   - Webhook: `https://<ngrok-subdomain>.ngrok-free.app/telephony/twilio/inbound`
   - Stream: `wss://<same-subdomain>.ngrok-free.app/telephony/twilio/media`

4. For **phone audio** (STT/TTS), also install telephony deps and `ffmpeg` on that machine (see [twilio-phone-test.md](./twilio-phone-test.md)).

**Note:** Free tunnel URLs change unless you pay for a fixed domain—fine for testing.

## Option B — Docker on a VPS (good “real” POC)

From repo root:

```bash
docker compose -f infra/docker-compose.yml up --build -d
```

- Binds **8000** on the host; put **Caddy** or **nginx** in front for **TLS** on 443 and proxy to `127.0.0.1:8000`.
- The compose file mounts `apps/api/data` so **SQLite** survives container restarts.
- **Twilio path:** install **`ffmpeg`** in the image if you use PSTN TTS—the default [`apps/api/Dockerfile`](../apps/api/Dockerfile) only has `requirements.txt`; for Whisper + phone TTS extend the image with `requirements-telephony.txt` and `ffmpeg` (or run STT/TTS on another service and use `KITCHENCALL_TWILIO_STREAM_STT_BACKEND=http`).

## Option C — Managed PaaS (Fly / Railway / Render, …)

General checklist:

1. **Build command / Dockerfile** — use `apps/api` context like the repo Dockerfile.
2. **Start command** — `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (platforms often set `PORT`).
3. **Persistent volume** — mount a disk at `/app/data` (or wherever `KITCHENCALL_DATABASE_PATH` points) so orders aren’t lost on redeploy.
4. **WebSockets** — enable if the platform has a toggle; confirm **WSS** works on your URL.
5. **Env vars** — copy from `apps/api/.env.example` (`KITCHENCALL_*`).

Compare platforms on: **price**, **WS support**, **disk**, **region** (latency to you and to Twilio).

### Render (step-by-step)

Use a **Web Service** (not a Static Site). Render gives you **HTTPS** and supports **WebSockets**, which Twilio Media Streams need.

1. **New → Web Service** → connect **`https://github.com/<you>/KitchenCall`** (repo root, not a `/tree/.../apps/api` URL).
2. **Root Directory (required for this monorepo):** set to **`apps/api`** on the service **Settings** page. If this is empty, the build looks for a `Dockerfile` at the repo root and fails with *`open Dockerfile: no such file or directory`*. Alternatively, deploy from the repo’s **[`render.yaml`](../render.yaml)** (Blueprint) which sets `rootDir: apps/api`.
3. **Runtime:** **Docker** (uses [`apps/api/Dockerfile`](../apps/api/Dockerfile)) *or* **Python** with:
   - **Build:** `pip install -r requirements.txt` (and `requirements-telephony.txt` if you use phone STT).
   - **Start:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. **PORT:** The Dockerfile already uses **`${PORT:-8000}`**, so Docker deploys usually need **no** override. If you ever pin the image to port 8000 only, set the service **Docker Command** to `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
5. **Persistent disk (SQLite):** **Settings → Disks** → add a disk, mount path **`/app/data`** (same as `KITCHENCALL_DATABASE_PATH` in the Dockerfile). Without this, the DB resets when the instance restarts.
6. **Environment:** add `KITCHENCALL_*` from [`apps/api/.env.example`](../apps/api/.env.example). For Twilio:
   - `KITCHENCALL_TWILIO_BRIDGE_MODE=stream`
   - `KITCHENCALL_TWILIO_MEDIA_STREAM_URL=wss://<your-service>.onrender.com/telephony/twilio/media`  
     (or `wss://voice.yourdomain.com/...` after you attach a custom domain).
7. **Twilio webhook:** `https://<same-host>/telephony/twilio/inbound`
8. **Phone STT/TTS:** the slim Docker image has **no `ffmpeg`** and no `requirements-telephony.txt`. For real calls with local Whisper + PSTN TTS, extend the Dockerfile (install `ffmpeg`, `pip install -r requirements-telephony.txt`) or set **`KITCHENCALL_TWILIO_STREAM_STT_BACKEND=http`** and point at an external transcoder.
9. **Free tier:** the service **spins down** when idle; first request (or an incoming call) can hit a **cold start**. For reliable Twilio demos, use a **paid** instance or keep the service warm.

**Custom domain:** Render dashboard → **Settings → Custom Domains** → add e.g. `api.yourdomain.com`, then set the same host in Twilio and in `KITCHENCALL_TWILIO_MEDIA_STREAM_URL` with **`wss://`**.

## After it’s up

- Open **`/docs`** (Swagger) on your public base URL.
- Health: **`GET /health`**
- Twilio smoke: [twilio-phone-test.md](./twilio-phone-test.md)

## CORS (dashboard)

If the web app is on another origin (e.g. Vercel + API on Fly), set:

`KITCHENCALL_CORS_ORIGINS=https://your-dashboard.example,https://www.your-dashboard.example`

## Summary

- **Many options** boil down to: **who runs `uvicorn`**, **who terminates TLS**, and **where SQLite lives**.
- For **Twilio**, prioritize **HTTPS webhook + WSS media** on a **stable URL** and a host that **keeps WebSockets open** for the duration of a call.
