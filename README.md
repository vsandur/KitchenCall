# KitchenCall

Human-like restaurant phone ordering POC: **natural conversation** with a **deterministic cart** as source of truth (dual-loop architecture in `docs/architecture.md`).

## What’s implemented (Phase 1 POC)

| Area | Details |
|------|---------|
| **State engine** | `apps/api/app/services/state_engine.py` — actions → cart; `phase_from_state`; sequence apply |
| **SQLite** | Sessions, transcript lines, saved orders — `apps/api/data/kitchencall.db` (auto-created) |
| **API** | `POST /sessions`, `GET /sessions`, `GET /sessions/{id}`, `POST .../transcript`, `POST .../process-turn` (rules by default; optional **local LLM** via OpenAI-compatible API, e.g. Ollama), `POST .../actions`, `POST .../finalize` (affirmation gate), `GET /orders`, `GET /menu`, `GET /health` |
| **Dashboard** | Vite + React — `apps/web` — polls API via dev proxy `/api` → `http://127.0.0.1:8000` |
| **POC script** | `poc/scripts/run_local_demo.py` — end-to-end ordering + finalize (stdlib `urllib`) |
| **LiveKit** | `POST /livekit/token` (API) + `apps/agent` worker — room `kc-{session_id}` → STT → `process-turn` → TTS |

## Documentation

| Doc | Purpose |
|-----|---------|
| [docs/architecture.md](docs/architecture.md) | Dual-loop design, transcript partial/final, session FSM, stack |
| [docs/oss-stack.md](docs/oss-stack.md) | **OSS / zero paid-API** defaults (rules, local LLM, self-hosted voice) |
| [docs/product-flow.md](docs/product-flow.md) | MVP PRD |
| [docs/poc-checklist.md](docs/poc-checklist.md) | Build order, demo script, PRD cross-refs |
| [docs/implementation-plan.md](docs/implementation-plan.md) | Milestones M0–M6 |
| [docs/prompt-design.md](docs/prompt-design.md) | Staff tone |
| [docs/twilio-phone-test.md](docs/twilio-phone-test.md) | **Call your Twilio number** — PSTN test runbook (ngrok, env, ffmpeg) |
| [docs/api-hosting.md](docs/api-hosting.md) | **Host the API** — laptop+tunnel vs VPS+Docker vs PaaS (Twilio / WSS / SQLite) |

## Run locally

### 1. API

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000 --reload-dir app --reload-dir data
```

Open http://127.0.0.1:8000/docs

**Reload loop:** use `--reload-dir app --reload-dir data` so `.venv` is not watched (see earlier note in git history if needed).

### 2. Dashboard (second terminal)

```bash
cd apps/web
npm install
npm run dev
```

Open http://127.0.0.1:5173 — create a session, then use **Start mic** (browser speech recognition) or **Process turn** text input. Assistant replies are also spoken with browser TTS (toggleable). With LiveKit configured on the API, use **Connect LiveKit mic** while the agent worker is running (see below). Finalize after the cart reaches `confirming` (for example after saying `that's all`).

### 3. LiveKit voice room (optional)

Requires a LiveKit project, API env vars for token minting, and speech backend env vars on the worker.

**API** — set `KITCHENCALL_LIVEKIT_URL`, `KITCHENCALL_LIVEKIT_API_KEY`, `KITCHENCALL_LIVEKIT_API_SECRET` (see `apps/api/.env.example`). Restart uvicorn. The dashboard calls `POST /livekit/token` with the current session id; clients join room `kc-{session_id}`.

**Agent worker** (separate terminal):

```bash
cd apps/agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export LIVEKIT_URL=wss://your-project.livekit.cloud
export LIVEKIT_API_KEY=...
export LIVEKIT_API_SECRET=...
export KITCHENCALL_API_BASE=http://127.0.0.1:8000
# STT backend: "kyutai" (default, Moshi-compatible) or "inference"
export KITCHENCALL_STT_BACKEND=kyutai
# Kyutai/Moshi STT server
export KYUTAI_API_KEY=...
export KYUTAI_BASE_URL=ws://127.0.0.1:8080/api/asr-streaming
# TTS backend: LiveKit Inference (default)
export KITCHENCALL_TTS_BACKEND=inference
# Optional inference model overrides
export KITCHENCALL_STT_MODEL=deepgram/flux-general
export KITCHENCALL_TTS_MODEL=cartesia/sonic-2
export KITCHENCALL_TTS_VOICE=9626c31c-bec5-4cca-baa8-f8ba9e84c8bc
# Optional shared heartbeat file (worker writes, API reads)
export KITCHENCALL_AGENT_HEARTBEAT_PATH=/tmp/kitchencall-agent-heartbeat.json
# Optional preflight validation (exits 0/1 and prints missing vars)
python -m kitchencall_agent.worker --check
python -m kitchencall_agent.worker dev
```

The worker registers as agent name `kitchencall`. Configure your LiveKit project so room jobs are dispatched to this worker (see [LiveKit Agents](https://docs.livekit.io/agents/) for dispatch / dev workflow).
Current state: STT can run on Kyutai/Moshi, with LiveKit Inference used for TTS (and as STT fallback).

**Dashboard** — select the same session, click **Connect LiveKit mic**. Prefer **Stop mic** on the browser SpeechRecognition path when testing LiveKit so only one mic pipeline runs.

### 3.1 Quick runbook (exact order)

1. Start API (`uvicorn` in `apps/api`) with `KITCHENCALL_LIVEKIT_*` configured.
2. Start Kyutai/Moshi STT server (`KYUTAI_BASE_URL`) and confirm API key works.
3. Start agent worker in `apps/agent` with:
   - `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
   - `KITCHENCALL_API_BASE`
   - `KITCHENCALL_STT_BACKEND=kyutai`
   - `KITCHENCALL_TTS_BACKEND=inference`
4. Open dashboard, create/select a session, click **Connect LiveKit mic**.
5. Speak one turn; verify cart/transcript updates and assistant audio reply.

### 3.2 Troubleshooting

- **`/livekit/token` returns `livekit_not_configured`**
  - Set API env vars: `KITCHENCALL_LIVEKIT_URL`, `KITCHENCALL_LIVEKIT_API_KEY`, `KITCHENCALL_LIVEKIT_API_SECRET`, then restart API.
- **Dashboard connects, but no agent joins room**
  - Ensure LiveKit dispatch routes jobs to `agent_name="kitchencall"` and worker is running with valid `LIVEKIT_*`.
- **Dashboard shows `Agent status: unavailable`**
  - Check heartbeat path alignment between worker/API via `KITCHENCALL_AGENT_HEARTBEAT_PATH` and confirm worker process can write the file.
- **Worker exits at startup with config error**
  - Worker validates env at boot; fix missing vars listed in the exception and restart.
- **No transcripts from mic**
  - Verify `KYUTAI_API_KEY` and `KYUTAI_BASE_URL` if using `KITCHENCALL_STT_BACKEND=kyutai`; otherwise set `KITCHENCALL_STT_BACKEND=inference`.
- **No assistant speech**
  - Confirm `KITCHENCALL_TTS_BACKEND=inference` and `LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` are set for LiveKit Inference access.

### 4. CLI demo (API must be running on port 8000)

```bash
python3 poc/scripts/run_local_demo.py
# or: python3 poc/scripts/run_local_demo.py --base http://127.0.0.1:8765
```

### 5. Twilio mapping (API webhook)

Twilio call mapping is now wired in the API:

- `POST /telephony/twilio/inbound` — accepts Twilio form fields (`CallSid`, `From`, `To`), creates a KitchenCall session, stores call mapping, returns TwiML response.
- `POST /telephony/twilio/status` — accepts Twilio status callback (`CallSid`, `CallStatus`) and updates mapped call status.
- `GET /telephony/twilio/calls/{call_sid}` — inspect mapped call/session for debugging.
- `WS /telephony/twilio/media` — Twilio Media Streams: maps lifecycle to the session; optional **STT → same `process-turn` path** as the dashboard (see [docs/twilio-media-bridge.md](docs/twilio-media-bridge.md)).

Bridge mode is configurable via API env:

- `KITCHENCALL_TWILIO_BRIDGE_MODE=say_only|stream|sip`
- `KITCHENCALL_TWILIO_MEDIA_STREAM_URL=wss://<your-public-host>/telephony/twilio/media` (when mode=`stream`; must be **wss** for Twilio)
- `KITCHENCALL_TWILIO_SIP_URI=sip:...` (used when mode=`sip`)

`stream` appends `session_id` and `call_sid` query params. Set `KITCHENCALL_TWILIO_STREAM_STT_BACKEND=faster_whisper` (install `requirements-telephony.txt`) or `http` to transcribe caller audio into cart updates. For the caller to **hear** assistant replies on the phone, use **`both_tracks`** (default) and install **`ffmpeg`**; see [docs/twilio-phone-test.md](docs/twilio-phone-test.md).

**Which number to call for testing:** the **Twilio phone number on your account** (Console → Phone Numbers → Active numbers). There is no project-wide shared test number; you dial **your** purchased or trial number after its voice webhook points at your public API.

Local verifiers (without placing a real call):

```bash
python3 poc/scripts/verify_twilio_mapping.py --base http://127.0.0.1:8000
python3 poc/scripts/verify_twilio_tts_local.py
```

### Tests

```bash
cd apps/api
pip install -r requirements-dev.txt
pytest
```

```bash
cd apps/agent
pip install -r requirements-dev.txt
pytest
```

### Docker (API only)

From repo root:

```bash
docker compose -f infra/docker-compose.yml up --build
```

## Env (optional)

See `apps/api/.env.example` — `KITCHENCALL_MENU_PATH`, `KITCHENCALL_DATABASE_PATH`, `KITCHENCALL_CORS_ORIGINS`, optional `KITCHENCALL_LIVEKIT_*` for `/livekit/token`, optional **`KITCHENCALL_LOGIC_EXTRACTOR=llm`** + `KITCHENCALL_LLM_*` for local Ollama (defaults to `http://127.0.0.1:11434/v1`, no key on localhost). Details: [docs/oss-stack.md](docs/oss-stack.md).

## Not done yet (by design)

- **Full barge-in policy** is basic today (browser TTS cancels when mic starts; API still processes only final transcripts)  
- **Phase 2+** repeat customers, richer telephony (transfer, etc.), POS  

## Working name

**KitchenCall** — local-first; MLX / Moshi / LiveKit as optional audio layers (`docs/architecture.md`).
