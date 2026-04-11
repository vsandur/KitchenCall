# KitchenCall — open-source, zero-API-spend plan

Goal: run the POC **without paid cloud AI or speech APIs**, using **local or self-hosted OSS** where a model or service is needed. Paid providers remain optional for teams that choose them later.

## 1. Order understanding (API / `process-turn`)

| Mode | Cost | What it is |
|------|------|------------|
| **`rules` (default)** | Free | Deterministic patterns in `apps/api/app/services/logic_loop.py`. Good for demos and tests. |
| **`llm` + local Ollama** | Free (your hardware) | Set `KITCHENCALL_LOGIC_EXTRACTOR=llm` and run [Ollama](https://ollama.com) with a small instruct model. Set `KITCHENCALL_LLM_MODEL` to an exact name from `ollama list` (e.g. `llama3.2:3b` or `qwen2.5:3b` — a bare `llama3.2` string will 404 if that tag was never pulled). The API calls `POST …/v1/chat/completions` on `KITCHENCALL_LLM_BASE_URL` (default `http://127.0.0.1:11434/v1`). No API key is required when the base URL is **localhost / 127.0.0.1**. |

Other **OpenAI-compatible** OSS servers (vLLM, LocalAI, etc.) work the same way; point `KITCHENCALL_LLM_BASE_URL` at your server and set `KITCHENCALL_LLM_API_KEY` if the server requires auth.

The state engine still **validates every action**; the LLM only proposes JSON actions.

## 2. Dashboard voice (browser)

| Path | Cost |
|------|------|
| **Browser mic + Web Speech API** | Free |
| **Browser TTS** | Free |

No server-side speech required.

## 3. LiveKit room + worker (`apps/agent`)

| Piece | OSS / free option | Paid option (optional) |
|-------|-------------------|-------------------------|
| **Realtime room** | [LiveKit open source](https://github.com/livekit/livekit) self-hosted | LiveKit Cloud |
| **STT** | **Kyutai / Moshi**-style server (`KITCHENCALL_STT_BACKEND=kyutai`) per your deployment | LiveKit Inference, cloud STT |
| **TTS** | Self-hosted TTS or a local pipeline you wire in | LiveKit Inference TTS |

The worker is designed to hit **your** API (`KITCHENCALL_API_BASE`); it does not require a paid LLM for the **cart** if you keep logic on the API (`rules` or local `llm`).

## 4. Phone (PSTN vs OSS)

There is **no open-source clone of Twilio** that also gives you **free** calls to/from the real public telephone network. The **telephone network** is operated by carriers; someone pays for **DIDs** (phone numbers) and **minutes**, whether that is Twilio, another CPaaS, or a **SIP trunk** behind your own server.

### $0 speech demos (no classical “phone line”)

Use paths that never touch PSTN:

| Path | Notes |
|------|--------|
| **Dashboard — browser mic** | §2 above; same `process-turn` / cart as production logic. |
| **LiveKit + web client** | §3; customer uses a **browser or app**, not a landline/cell call. |

### OSS *software* for telephony (PSTN still has a small carrier bill)

If you want to **avoid Twilio** specifically, common stacks are:

| Component | Role |
|-----------|------|
| **[Asterisk](https://www.asterisk.org/)** or **[FreeSWITCH](https://freeswitch.com/)** | Open-source **PBX / media**: SIP, IVR, bridging, sometimes WebRTC. **Software is free**; you still buy a **SIP trunk** and number from an ITSP (often **cheaper per minute** than retail CPaaS, but not zero). |
| **[Kamailio](https://www.kamailio.org/)** / **[OpenSIPS](https://www.opensips.org/)** | SIP routing/proxy; same story for PSTN (**trunk required**). |

Typical pattern: **Asterisk/FreeSWITCH** terminates the customer’s call, converts audio to something your app can consume (e.g. **HTTP STT** you already support, **WebSocket/RTP bridge**, or a custom sidecar), then your service runs the same ordering logic. That **integration is not built into KitchenCall yet** — today’s wired path is **Twilio** (TwiML + Twilio Media Streams); an Asterisk **ARI / AudioSocket / RTP** path would be **new development**.

### Twilio with $0 *speech* APIs (still not $0 for the number)

If you use Twilio only as the **phone bridge**, you can keep **STT/TTS OSS** on your side (`faster-whisper`, local TTS + `ffmpeg`) — see [twilio-media-bridge.md](./twilio-media-bridge.md) and [twilio-phone-test.md](./twilio-phone-test.md). You still pay Twilio (or a trunk) for **the line**, not for OpenAI-style speech APIs.

**Summary:** For **no spend**, use **browser or LiveKit**. For **real phone calls**, use **paid carrier access** (Twilio or **OSS PBX + SIP trunk**); the repo today implements the **Twilio** shape first.

## 5. Suggested “all OSS” dev stack

1. **API**: `uvicorn` + `KITCHENCALL_LOGIC_EXTRACTOR=rules` *or* Ollama + `llm`.
2. **Web**: `npm run dev`.
3. **Optional voice**: Ollama (if using `llm`) + self-hosted LiveKit + Kyutai STT + agent worker with OSS TTS path when you add or swap plugins.

## 6. Security note

If you expose `KITCHENCALL_LLM_BASE_URL` to the **public internet** without auth, protect it (reverse proxy + key, or VPN). The default localhost setup is for **local development only**.
