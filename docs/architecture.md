# KitchenCall — Architecture

**One-line model:** KitchenCall uses a **dual-loop voice architecture** where realtime conversation stays natural, but **every order change passes through a deterministic action-and-state engine** before it becomes part of the cart.

Local-first restaurant ordering system. **Structured cart state is the source of truth**; the conversational layer never mutates the cart directly.

## System overview

```
                    CALLER (PSTN)
                        │
                     TWILIO
                        │ mu-law 8kHz audio
                        │
                CLOUDFLARE TUNNEL
                        │
         ┌──────────────┴──────────────┐
         │        AUDIO BRIDGE         │
         │    mu-law ↔ PCM 16kHz       │
         └──────┬─────────────┬────────┘
                │             │
       ┌────────▼───┐   ┌────▼──────────────┐
       │PERSONAPLEX │   │ WHISPER (shadow)   │
       │  7B MLX    │   │ text extraction    │
       │            │   └────┬──────────────-┘
       │ full-duplex│        │ caller text
       │ natural    │        ▼
       │ voice      │   ┌────────────────┐
       │            │   │ Logic Loop     │
       └────────────┘   │ (Rules/Ollama) │
                        └────┬───────────┘
                             │ actions
                             ▼
                        ┌────────────┐
                        │State Engine│
                        │  Cart/DB   │
                        └────┬───────┘
                             │
                             ▼
                        ┌────────────┐
                        │ Dashboard  │
                        │ (React)    │
                        └────────────┘
```

## Dual-loop model

### Audio / conversation loop

- **PersonaPlex-MLX** handles full-duplex, natural voice conversation on Apple Silicon.
- Prompted with the restaurant menu, ordering flow, and personality.
- Supports barge-in and natural turn-taking.
- Does **not** apply cart mutations directly.

### Logic loop (extractor, not planner)

- **Shadow pipeline**: Whisper extracts text from caller audio in parallel.
- Extract **intent** and **slots** (item, modifiers, order type, etc.) from text.
- Emit **structured actions** — `add_item`, `modify_item`, `remove_item`, `set_order_type`, `set_customer_info`, `confirm_order`, `transfer_to_staff`, etc.
- **Deterministic code** (state engine, session rules, menu validation) decides what is legal.

### State engine

- Applies actions to the cart **deterministically**; validates against the menu catalog.
- Rejects illegal modifiers or unknown items before they hit the cart.

### Why two loops

- Natural speech can be approximate; **cart math and corrections must be exact**.
- Splitting responsibilities avoids "sounds great, orders wrong."

## Session state machine

| Phase | Meaning |
|-------|---------|
| `greeting` | Opening; caller not yet in ordering flow. |
| `ordering` | Taking items, modifiers, order type. |
| `collecting_missing_info` | Filling name, phone, address, etc. |
| `confirming` | Readback; awaiting customer affirmation. |
| `submitted` | Order persisted and completed. |
| `transfer_requested` | Caller asked for staff; flag/log. |

## Local deployment stack

| Layer | Component | Port |
|-------|-----------|------|
| Voice agent | PersonaPlex-MLX (7B, 4-bit) | 8998 |
| Audio bridge | Twilio ↔ PersonaPlex connector | 8000 |
| STT (shadow) | faster-whisper (tiny, int8) | in-process |
| NLU | Ollama (llama3.2:3b) | 11434 |
| API + DB | FastAPI + SQLite | 8000 |
| Dashboard | React (Vite) | 5173 |
| Tunnel | Cloudflare Tunnel (free) | — |

All runs on a single Mac (M4 Pro, 24GB). No cloud APIs required.

## Data flow

1. Caller speaks → Twilio streams audio → audio bridge converts mu-law to PCM.
2. **PersonaPlex** handles the conversation in real-time (natural, full-duplex).
3. **In parallel**: Whisper extracts caller text → logic loop → structured actions.
4. **State engine** validates and applies actions → updates cart; session phase may update.
5. Dashboard shows live cart, transcript, and order status.

## Code map

| Area | Location |
|------|----------|
| FastAPI entry | `apps/api/app/main.py` |
| Session / order routes | `apps/api/app/api/routes_sessions.py` |
| Telephony (Twilio) | `apps/api/app/api/routes_telephony.py` |
| Cart / action models | `apps/api/app/schemas/` |
| DB models + repo | `apps/api/app/db/` |
| State engine + phase | `apps/api/app/services/state_engine.py` |
| Logic (rules extractor) | `apps/api/app/services/logic_loop.py` |
| LLM extractor (Ollama) | `apps/api/app/services/logic_loop_llm.py` |
| Orchestrator | `apps/api/app/services/orchestrator.py` |
| Menu catalog | `apps/api/app/services/menu_catalog.py` |
| STT (Whisper/Deepgram) | `apps/api/app/services/telephony_stt.py` |
| TTS (say/espeak) | `apps/api/app/services/twilio_tts_synth.py` |
| Dashboard | `apps/web/` |
| Docker | `Dockerfile` (cloud), `apps/api/Dockerfile` (local) |
| POC scripts | `poc/scripts/` |

## Related docs

- [product-flow.md](./product-flow.md) — MVP PRD.
- [implementation-plan.md](./implementation-plan.md) — milestones and API sketch.
- [poc-checklist.md](./poc-checklist.md) — build order and demo criteria.
- [prompt-design.md](./prompt-design.md) — tone and phrasing rules.
- [oss-stack.md](./oss-stack.md) — OSS / local-first stack notes.
- [twilio-phone-test.md](./twilio-phone-test.md) — Twilio call testing guide.
