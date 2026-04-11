# KitchenCall — POC checklist

Use this to sequence work and judge demo readiness. For product rules this checklist implements, see **[product-flow.md](./product-flow.md)** (MVP PRD).

### PRD alignment (must match implementation)

| Topic | PRD section |
|-------|----------------|
| **Confirmation gate** — no `completed` order without explicit customer yes | [§5.7 Final confirmation](./product-flow.md#57-final-confirmation) |
| **Transfer to staff** — POC stub (message / flag / log); live PBX later | [§5.10 Transfer to staff](./product-flow.md#510-transfer-to-staff-mvp--poc) |
| Ambiguity — clarify or target by `item_id`, no guessing | [§5.5 Corrections](./product-flow.md#55-corrections-and-changes) |
| Menu constraint — only validated menu items | [§5.3 Conversational order taking](./product-flow.md#53-conversational-order-taking) |

## Phase 1 — Local conversational POC

### Contracts and data

- [x] Cart JSON schema fixed (`order_id`, `customer`, `order_type`, `items[]`, `metadata`) — `apps/api/app/schemas/cart.py` + `packages/shared/schemas/cart.schema.json`  
- [x] Action JSON schema fixed (intents listed in PRD) — `apps/api/app/schemas/action.py` + `packages/shared/schemas/action.schema.json`  
- [x] Mock menu JSON + validation (sizes, modifiers, required choices, unavailable flags) — `apps/api/data/menu.json`, `app/services/menu_catalog.py`

### Core engine

- [x] Deterministic **state engine** — `apps/api/app/services/state_engine.py`  
- [x] Invalid actions → machine-readable error codes (`unknown_item_id`, `cart_empty`, menu codes, terminal state)  
- [x] Unknown `target_item_id` → error (no silent wrong line)  
- [x] Unit tests — `tests/test_state_engine.py`, `tests/test_menu_catalog.py`, `tests/test_logic_loop.py`

### Backend

- [x] FastAPI: sessions, transcript, `process-turn`, `actions`, `finalize`, `orders`, health, menu  
- [x] **Finalize** requires `affirmed: true` and `metadata.status == confirming` (PRD §5.7)  
- [x] **Transfer** sets `transfer_requested` + phase + `last_action` (PRD §5.10 stub)  
- [x] SQLite — `kitchen_sessions`, `transcript_lines`, `saved_orders`  
- [x] Dashboard **poll** (WebSocket optional later)

### Dashboard (minimal)

- [x] Transcript + cart JSON + completed orders — `apps/web` (Vite/React)

### Conversation

- [x] Staff prompt stub — `packages/shared/prompts/staff_prompt.txt` + [prompt-design.md](./prompt-design.md)  
- [x] Logic loop (rule-based MVP) — `apps/api/app/services/logic_loop.py`  
- [x] Orchestrator — `apps/api/app/services/orchestrator.py` (HTTP + future LiveKit)  
- [x] Local mic path (browser SpeechRecognition + transcript partials + final turn processing + TTS reply)

### Integration targets

- [x] LiveKit **extension point** — `poc/livekit_worker_stub.py`, `requirements-livekit.txt`  
- [x] LiveKit Agents session + media wired end-to-end (dashboard token -> room join -> worker STT -> `process-turn` -> TTS)  
- [x] Duplex voice path present with Kyutai/Moshi STT + LiveKit Inference TTS fallback

## Production flow — next tickets (1-3)

These map to the first three items in `docs/implementation-plan.md` production backlog.

### Ticket 1 — Telephony ingress MVP

- [x] Inbound phone provider selected and documented (SIP/Twilio)  
- [x] Inbound call webhook/ingress creates KitchenCall session id (`POST /telephony/twilio/inbound`)  
- [x] Twilio media websocket bridge contract is wired (`WS /telephony/twilio/media`) with session/call mapping and lifecycle logging  
- [x] Manual verification script for mapping/status path (`poc/scripts/verify_twilio_mapping.py`)  
- [x] Media Streams WS decodes inbound audio, optional STT (`faster_whisper` / HTTP), utterance segmentation → same `process-turn` as dashboard ([twilio-media-bridge.md](./twilio-media-bridge.md)); PSTN **TTS reply** via `both_tracks` + mu-law/`ffmpeg` ([twilio-phone-test.md](./twilio-phone-test.md)); voice **yes** in `confirming` finalizes order (same as `POST /finalize`)

### Ticket 2 — Live transfer handoff (replace stub)

- [ ] Transfer intent routes to a real staff destination (number/queue/endpoint)  
- [ ] Session outcome distinguishes `transferred`, `transfer_failed`, `transfer_declined`  
- [ ] Fallback caller message defined when transfer destination is unavailable  
- [ ] Manual verification for transfer happy path + failure path

### Ticket 3 — Dispatch/readiness guardrails

- [x] Worker preflight config check (`python -m kitchencall_agent.worker --check`)  
- [x] Health/readiness endpoint or status hook for worker process (supervisor-friendly) — heartbeat + `GET /agent/status`  
- [x] Runbook for "agent unavailable" incident handling (who/what/rollback steps) — `docs/runbook-agent-unavailable.md`  
- [x] Dashboard/API surface for unavailable agent state (clear operator signal)

## Success criteria (investor POC)

1. Conversation feels natural for **scripted** flows (one demo menu).  
2. Interruption / barge-in behaves acceptably for demo (policy + audio stack).  
3. Corrections update cart **without** dropping unrelated lines.  
4. Final spoken summary **matches** cart JSON.  
5. Dashboard shows the same structured order after confirm.

## Demo script (run through before showing)

| Demo | What to prove |
|------|----------------|
| **A — Normal order** | Pizza + side + drink; clarifications; confirm. |
| **B — Correction** | *“Actually make that a medium and add onions.”* Cart updates immediately. |
| **C — Interruption** | User talks over assistant; assistant stops and adapts. |
| **D — Repeat customer** | Phase 2: recognize test profile; offer usual order (optional). |

## Phase 2 — Repeat-customer memory

- [ ] Store orders per customer key (phone or test id)  
- [ ] Load last order / preferences for greeting suggestion  
- [ ] Dashboard: customer history

## Phase 3 — Phone

- [x] Twilio ingress into same orchestrator (`POST /telephony/twilio/inbound`, `WS /telephony/twilio/media`)  
- [x] Same cart and action pipeline as dashboard (`process-turn` + voice finalize on affirmation)

## Phase 4 — Productionization (not POC gate)

- Staff transfer, menu admin UI, kitchen display, POS, analytics

## First implementation order (recommended)

1. Schemas (cart + action)  
2. State engine + tests  
3. Mock menu + validation  
4. Minimal API + SQLite  
5. Minimal dashboard  
6. Prompt + logic loop  
7. Audio / LiveKit integration  
8. Harden demos A–C (D when phase 2 is ready)
