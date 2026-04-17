# KitchenCall — Architecture

**One-line model:** KitchenCall uses a **dual-loop voice architecture** — a natural full-duplex voice agent (PersonaPlex) handles the conversation while a **deterministic action-and-state engine** maintains the structured cart. The voice layer never mutates the cart directly.

Local-first, zero-cloud-API restaurant phone ordering system running entirely on Apple Silicon.

---

## System diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           CUSTOMER PHONE (PSTN)                         │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          TWILIO (cloud)                                  │
│                                                                          │
│  Inbound call → POST /telephony/twilio/inbound                          │
│  Returns TwiML: <Say> greeting → <Play> beep → <Connect><Stream>       │
│  Opens bidirectional WebSocket for real-time audio                       │
│  Audio format: G.711 mu-law, 8 kHz, mono, 20ms frames                  │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ wss:// (mu-law 8kHz, bidirectional)
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     CLOUDFLARE TUNNEL (free)                             │
│              https://<random>.trycloudflare.com                          │
│              Routes public internet → localhost:8000                     │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│                    MAC (M4 Pro, 24GB unified memory)                     │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │                   AUDIO BRIDGE (port 8000)                         │  │
│  │                                                                    │  │
│  │  Twilio WebSocket ←→ Audio format conversion ←→ PersonaPlex       │  │
│  │                                                                    │  │
│  │  Inbound:  mu-law 8kHz → PCM 16-bit → resample to 16kHz          │  │
│  │  Outbound: PersonaPlex PCM 24kHz → resample to 8kHz → mu-law     │  │
│  │                                                                    │  │
│  │  Responsibilities:                                                 │  │
│  │  • Accept Twilio Media Stream WebSocket events                    │  │
│  │  • Convert between Twilio's G.711 mu-law and PersonaPlex's PCM    │  │
│  │  • Route inbound audio to BOTH PersonaPlex and shadow STT         │  │
│  │  • Route PersonaPlex output audio back to Twilio                  │  │
│  │  • Manage session lifecycle (create, track, close)                │  │
│  └───────────┬──────────────────────────────┬────────────────────────┘  │
│              │                              │                           │
│     ┌────────▼────────┐            ┌────────▼─────────┐                 │
│     │  PERSONAPLEX    │            │  SHADOW PIPELINE  │                 │
│     │  (port 8998)    │            │  (in-process)     │                 │
│     │                 │            │                   │                 │
│     │  Model:         │            │  ┌─────────────┐  │                 │
│     │  personaplex-   │            │  │ Whisper STT │  │                 │
│     │  7b-v1 (MLX)    │            │  │ (tiny/int8) │  │                 │
│     │                 │            │  │ ~1-2s on M4 │  │                 │
│     │  Quantization:  │            │  └──────┬──────┘  │                 │
│     │  4-bit (Q4)     │            │         │ text    │                 │
│     │                 │            │         ▼         │                 │
│     │  Memory: ~5GB   │            │  ┌─────────────┐  │                 │
│     │                 │            │  │ Logic Loop  │  │                 │
│     │  Features:      │            │  │             │  │                 │
│     │  • Full-duplex  │            │  │ Rules-based │  │                 │
│     │  • Barge-in     │            │  │ extractor   │  │                 │
│     │  • Natural      │            │  │ OR          │  │                 │
│     │    voice        │            │  │ Ollama LLM  │──┼───► Ollama     │
│     │  • Streaming    │            │  │ (llama3.2)  │  │    (port 11434)│
│     │                 │            │  └──────┬──────┘  │                 │
│     │  Prompt:        │            │         │actions  │                 │
│     │  Restaurant     │            │         ▼         │                 │
│     │  personality +  │            │  ┌─────────────┐  │                 │
│     │  menu + flow    │            │  │State Engine │  │                 │
│     │                 │            │  │             │  │                 │
│     └─────────────────┘            │  │ Validates   │  │                 │
│                                    │  │ against     │  │                 │
│                                    │  │ menu.json   │  │                 │
│                                    │  │             │  │                 │
│                                    │  │ Updates     │  │                 │
│                                    │  │ cart + DB   │  │                 │
│                                    │  └──────┬──────┘  │                 │
│                                    │         │         │                 │
│                                    └─────────┼─────────┘                 │
│                                              │                           │
│                                              ▼                           │
│                                    ┌─────────────────┐                   │
│                                    │    SQLite DB     │                   │
│                                    │                  │                   │
│                                    │  Sessions        │                   │
│                                    │  Transcripts     │                   │
│                                    │  Orders          │                   │
│                                    │  Telephony calls │                   │
│                                    └────────┬─────────┘                   │
│                                             │                            │
│                                             ▼                            │
│                                    ┌─────────────────┐                   │
│                                    │   Dashboard     │                   │
│                                    │   (React/Vite)  │                   │
│                                    │   port 5173     │                   │
│                                    │                 │                   │
│                                    │  • Live cart    │                   │
│                                    │  • Transcript   │                   │
│                                    │  • Order queue  │                   │
│                                    └─────────────────┘                   │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Why two loops?

Natural speech can be approximate ("yeah gimme a large pep with extra cheese"); **cart math and corrections must be exact**. Splitting responsibilities avoids "sounds great, orders wrong."

| Loop | Responsibility | Speed | Accuracy |
|------|---------------|-------|----------|
| **Voice (PersonaPlex)** | Natural conversation, tone, pacing, barge-in | Real-time (~100ms) | Approximate (7B model) |
| **Logic (Shadow)** | Cart mutations, pricing, validation | Near-real-time (~3-5s) | Deterministic, exact |

The voice loop shapes the **experience**. The logic loop shapes the **order**.

---

## Component details

### 1. Twilio (external)

- Receives PSTN call on purchased phone number
- Calls our webhook (`POST /telephony/twilio/inbound`) → receives TwiML
- TwiML plays a short greeting and beep, then opens a WebSocket stream
- Streams caller audio as base64-encoded mu-law in JSON frames every 20ms
- Accepts outbound audio on the same WebSocket for the agent's voice

### 2. Cloudflare Tunnel

- Free, no-signup tunnel via `cloudflared tunnel --url http://localhost:8000`
- Provides public HTTPS + WSS URL pointing to localhost
- URL changes on restart (stable URLs available with a Cloudflare account)

### 3. Audio Bridge (`routes_telephony.py`)

The bridge sits inside the FastAPI app and handles:

| Function | Detail |
|----------|--------|
| **WebSocket lifecycle** | Accept connection, parse `connected`/`start`/`media`/`stop` events |
| **Session mapping** | Map Twilio `CallSid` → KitchenCall session via DB lookup |
| **Format conversion** | G.711 mu-law ↔ PCM16 (in-process codec, no ffmpeg needed for decode) |
| **Audio routing** | Fork inbound PCM to both PersonaPlex and shadow Whisper pipeline |
| **Outbound audio** | Receive PersonaPlex speech, encode to mu-law, send to Twilio |

### 4. PersonaPlex-MLX (voice agent)

| Property | Value |
|----------|-------|
| Model | `nvidia/personaplex-7b-v1` |
| Runtime | MLX (Apple Silicon optimized) |
| Quantization | 4-bit (Q4) |
| Memory | ~5 GB unified memory |
| Mode | Full-duplex streaming |
| Audio I/O | PCM 16-bit, 24 kHz |
| Latency | ~100-200ms first-token |

**Personality prompt** configures the model as a restaurant ordering agent:

```
You are a friendly phone order agent for Mario's Pizza. You are warm,
efficient, and natural — like a real restaurant employee. Our menu:

- Pepperoni Pizza (small/medium/large)
- Cheese Pizza (small/medium/large)
- Garlic Knots (6 piece/12 piece)
- Coke (can/20oz)
- Classic Burger (single/double)
- Chicken Sandwich

Take the customer's order, confirm items, ask for their name and phone
number, read back the complete order, and confirm. Be conversational
and friendly, not robotic.
```

PersonaPlex handles:
- **Greeting** the caller naturally
- **Listening** and responding in real-time (full-duplex)
- **Barge-in** — caller can interrupt mid-sentence
- **Clarification** — "Did you say large or medium?"
- **Confirmation** — reading back the order naturally

PersonaPlex does **not** handle:
- Cart state management (shadow pipeline does this)
- Menu validation (state engine does this)
- Order persistence (API does this)

### 5. Shadow STT pipeline (Whisper)

Runs in parallel with PersonaPlex on the same inbound audio:

```
Inbound PCM → UtteranceBuffer (5s chunks or silence-triggered)
           → faster-whisper (tiny model, int8, ~1-2s on M4 Pro)
           → transcribed text
           → logic loop (intent + slot extraction)
           → state engine (cart mutation)
           → DB write
```

| Property | Value |
|----------|-------|
| Model | `faster-whisper` tiny |
| Compute | CPU int8 (M4 Pro) |
| Latency | ~1-2s for 5s audio |
| Purpose | Extract text for structured cart updates |

The shadow pipeline does **not** generate voice responses — PersonaPlex does that.

### 6. Logic loop

Two modes (configurable via `KITCHENCALL_LOGIC_EXTRACTOR`):

**Rules-based** (`rules`, default):
- Pattern matching on transcribed text
- Zero cost, zero latency, deterministic
- Handles: "large pepperoni", "add extra cheese", "name is Alex", etc.

**LLM-assisted** (`llm`):
- Sends text to Ollama (llama3.2:3b on port 11434)
- Returns structured JSON actions
- Better at ambiguous utterances, costs more CPU

Both output the same **action schema**: `add_item`, `modify_item`, `remove_item`, `set_order_type`, `set_customer_info`, `confirm_order`, `transfer_to_staff`.

### 7. State engine

Deterministic, zero-tolerance cart manager:

- Validates every action against `menu.json` before applying
- Rejects unknown items, invalid modifiers, impossible quantities
- Manages session phase transitions (greeting → ordering → confirming → submitted)
- Computes `missing_info` (name, phone, order type not yet provided)
- Never guesses — rejects ambiguous actions with machine-readable errors

### 8. SQLite database

| Table | Purpose |
|-------|---------|
| `sessions` | Session state, cart JSON, phase |
| `transcripts` | Timestamped conversation log (user, assistant, system) |
| `orders` | Finalized orders (snapshot of cart at submission) |
| `telephony_calls` | Twilio call tracking (SID, status, session mapping) |

### 9. Dashboard (React)

- Live view of active sessions, cart contents, and transcript
- Order queue showing completed/submitted orders
- Polls the API or uses WebSocket for real-time updates

---

## Session state machine

```
  ┌──────────┐     first utterance     ┌──────────┐
  │ greeting ├─────────────────────────►│ ordering │
  └──────────┘                          └────┬─────┘
                                             │
                                   all items + info collected
                                             │
                                             ▼
                                       ┌───────────┐
                                       │confirming │
                                       └─────┬─────┘
                                             │
                                     customer says "yes"
                                             │
                                             ▼
                                       ┌───────────┐
                                       │ submitted │
                                       └───────────┘
```

| Phase | Meaning | Triggers next |
|-------|---------|---------------|
| `greeting` | Opening, caller not yet ordering | Any food/drink mention |
| `ordering` | Taking items, modifiers, order type | All `missing_info` resolved |
| `collecting_missing_info` | Filling name, phone, address | All required fields present |
| `confirming` | Readback, awaiting "yes" | Affirmation detected |
| `submitted` | Order persisted, call can end | — |
| `transfer_requested` | Caller asked for human staff | — |

---

## Call flow (end to end)

```
Time  Caller                  System
─────────────────────────────────────────────────────────────────
0s    Dials restaurant        Twilio receives call
                              POST /inbound → TwiML returned
1s                            <Say> "Thanks for calling Mario's
                              Pizza! Tell me what you'd like..."
5s                            <Play> beep.wav
6s                            <Connect><Stream> WebSocket opens
                              PersonaPlex session starts

8s    "Hi, can I get a        PersonaPlex: listens, responds
       large pepperoni         naturally in real-time
       pizza?"
                              Shadow: Whisper transcribes →
                              logic extracts add_item →
                              state engine adds to cart

10s                           PersonaPlex: "Sure! A large
                              pepperoni pizza. Anything else?"

12s   "Yeah, garlic knots     PersonaPlex: responds
       and a Coke"
                              Shadow: extracts 2 items →
                              cart updated

15s                           PersonaPlex: "Got it! Garlic
                              knots and a Coke. What's the
                              name for the order?"

17s   "Alex, 555-1234"        Shadow: extracts customer info
                              missing_info resolved

20s                           PersonaPlex: "Okay Alex, so
                              that's a large pepperoni, garlic
                              knots, and a Coke for pickup.
                              Sound right?"

22s   "Yes"                   Shadow: affirmation detected →
                              finalize_session → order saved

23s                           PersonaPlex: "You're all set!
                              It'll be ready in about 15
                              minutes. Thanks for calling!"

25s   Hangs up                Twilio sends stop event
                              Session closed, order in DB
                              Dashboard shows new order
```

---

## Port allocation

| Port | Service | Protocol |
|------|---------|----------|
| 8000 | KitchenCall API + Audio Bridge | HTTP, WSS |
| 8998 | PersonaPlex-MLX (web mode) | HTTP, WSS |
| 11434 | Ollama (LLM) | HTTP |
| 5173 | Dashboard (Vite dev server) | HTTP |
| 6379 | Redis (Mirofish, separate project) | TCP |

---

## Memory budget (24GB unified)

| Component | Estimated |
|-----------|-----------|
| PersonaPlex 7B Q4 | ~5 GB |
| Ollama llama3.2:3b | ~2 GB |
| faster-whisper tiny | ~0.2 GB |
| FastAPI + SQLite | ~0.1 GB |
| OS + other apps | ~8 GB |
| **Headroom** | **~8.7 GB** |

---

## File structure

```
KitchenCall/
├── Dockerfile                    # Cloud deploy (Deepgram STT)
├── render.yaml                   # Render blueprint
├── .gitignore
├── README.md
│
├── apps/
│   ├── api/
│   │   ├── Dockerfile            # Local Docker (Whisper STT)
│   │   ├── requirements.txt
│   │   ├── requirements-dev.txt
│   │   ├── requirements-telephony.txt
│   │   ├── .env.example
│   │   ├── data/
│   │   │   ├── menu.json         # Restaurant menu definition
│   │   │   └── phone_beep.wav    # Tone played before stream
│   │   ├── app/
│   │   │   ├── main.py           # FastAPI entry + lifespan
│   │   │   ├── config.py         # Pydantic settings (KITCHENCALL_*)
│   │   │   ├── api/
│   │   │   │   ├── routes.py             # Health, menu
│   │   │   │   ├── routes_sessions.py    # Sessions, orders, process-turn
│   │   │   │   ├── routes_telephony.py   # Twilio webhooks + WebSocket
│   │   │   │   └── routes_livekit.py     # LiveKit token generation
│   │   │   ├── db/
│   │   │   │   ├── database.py   # SQLite engine + session factory
│   │   │   │   ├── models.py     # SQLAlchemy table definitions
│   │   │   │   └── repo.py       # Data access layer
│   │   │   ├── schemas/
│   │   │   │   ├── cart.py       # Cart, CartItem, CartMetadata
│   │   │   │   ├── action.py     # Action types (add_item, etc.)
│   │   │   │   └── session.py    # Session schemas
│   │   │   └── services/
│   │   │       ├── state_engine.py       # Deterministic cart mutations
│   │   │       ├── logic_loop.py         # Rules-based intent extraction
│   │   │       ├── logic_loop_llm.py     # LLM-based extraction (Ollama)
│   │   │       ├── logic_extract.py      # Extractor dispatch
│   │   │       ├── orchestrator.py       # Session turn orchestration
│   │   │       ├── session_turn.py       # Process-turn entry point
│   │   │       ├── session_finalize.py   # Order finalization
│   │   │       ├── response_builder.py   # Assistant response generation
│   │   │       ├── menu_catalog.py       # Menu loading + validation
│   │   │       ├── telephony_stt.py      # STT backends (Whisper/Deepgram/OpenAI)
│   │   │       ├── twilio_mulaw.py       # G.711 mu-law codec
│   │   │       ├── twilio_utterance.py   # Utterance buffer (silence detection)
│   │   │       ├── twilio_media_turn.py  # STT → process-turn orchestration
│   │   │       ├── twilio_media_outbound.py  # Send audio to Twilio
│   │   │       └── twilio_tts_synth.py   # TTS synthesis (say/espeak/ffmpeg)
│   │   └── tests/                # 41 tests (pytest)
│   │
│   ├── web/                      # React dashboard (Vite + TypeScript)
│   └── agent/                    # LiveKit worker (optional)
│
├── poc/scripts/                  # Demo + verification scripts
├── infra/docker-compose.yml      # Docker Compose for VPS deploy
└── docs/                         # Architecture, hosting, testing guides
```

---

## Related docs

- [product-flow.md](./product-flow.md) — MVP product requirements
- [implementation-plan.md](./implementation-plan.md) — Milestones and API sketch
- [poc-checklist.md](./poc-checklist.md) — Build order and demo criteria
- [prompt-design.md](./prompt-design.md) — Tone and phrasing rules
- [oss-stack.md](./oss-stack.md) — OSS / local-first stack notes
- [api-hosting.md](./api-hosting.md) — Deployment options
- [twilio-phone-test.md](./twilio-phone-test.md) — Twilio call testing guide
