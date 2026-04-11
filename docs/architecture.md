# KitchenCall — Architecture (POC)

**One-line model:** KitchenCall uses a **dual-loop voice architecture** where realtime conversation stays natural, but **every order change passes through a deterministic action-and-state engine** before it becomes part of the cart.

Local-first restaurant ordering POC. **Structured cart state is the source of truth**; the conversational layer never mutates the cart directly.

## Dual-loop model

### Audio / conversation loop

- Handles listening, speaking, timing, barge-in, and restaurant-like tone.
- May use duplex speech (e.g. Moshi) or a **real** fallback **STT → LLM/TTS** path (LiveKit supports both pipeline styles) if Moshi install or runtime is unstable on Apple Silicon.
- Receives **context** from the session (cart snapshot, `missing_info`, session phase) to shape replies.
- Does **not** apply cart mutations; it reacts to user speech and to outcomes of **structured actions** (e.g. clarification prompts, confirmations).

### Logic loop (extractor, not planner — MVP)

For Phase 1, keep the logic loop **narrow**:

- Extract **intent** and **slots** (item, modifiers, order type, etc.) from **final** text only.
- Emit **structured actions**; do not let the model “plan” the whole conversation or rewrite the cart in prose.
- **Deterministic code** (state engine, session rules, menu validation) decides what is legal and what happens next.

Outputs match the action schema: `add_item`, `modify_item`, `remove_item`, `set_order_type`, `set_customer_info`, `ask_clarification`, `confirm_order`, `transfer_to_staff`, etc.

### State engine

- Applies actions to the cart **deterministically**; validates against the menu catalog.
- Rejects illegal modifiers or unknown items before they hit the cart; surfaces reasons for short follow-ups.

### Why two loops

- Natural speech can be approximate; **cart math and corrections must be exact**.
- Splitting responsibilities avoids “sounds great, orders wrong.”

## Transcript event contract

Split events so the logic loop does not fire on half-finished speech:

| Class | Use |
|-------|-----|
| **`partial_transcript`** | UI, interruption / barge-in, “assistant should hush” hints; **not** sent to action extraction. |
| **`final_transcript`** | End-of-utterance text; **only** this (or equivalent committed segment) feeds the logic loop → actions → state engine. |

Orchestrator policy: optionally use partials for UX only; cart mutations only after finals (unless you add an explicit “commit early” rule later).

## Session state machine (orchestration)

Cart JSON tracks **what** is ordered; the session additionally tracks **where** the conversation is (orchestrator / session row / FSM):

| Phase | Meaning |
|-------|---------|
| `greeting` | Opening; caller not yet in ordering flow. |
| `ordering` | Taking items, modifiers, order type. |
| `collecting_missing_info` | Filling `metadata.missing_info` (name, phone, address, …). |
| `confirming` | Readback; awaiting explicit customer affirmation (PRD §5.7). |
| `submitted` | Order persisted and completed for this session. |
| `transfer_requested` | Caller asked for staff; POC stub — flag/log, message (PRD §5.10). |

Valid transitions are enforced in the orchestrator/API (not by the voice model). Interruption recovery is easier when each turn checks **phase + cart + last final transcript**.

## High-level data flow

1. User speaks → audio pipeline emits **`partial_transcript`** (optional) and **`final_transcript`** per utterance.
2. **Final** text → **logic loop** → one or more **actions** (JSON).
3. **State engine** validates and applies actions → updates cart JSON; session phase may update.
4. Session publishes **cart + phase** to the dashboard (poll or WebSocket).
5. Conversation loop generates the next utterance using **policy + cart context** (staff-like phrasing; see [prompt-design.md](./prompt-design.md)).

## Backend responsibilities (FastAPI)

- REST (and/or WebSocket): sessions, transcript append, cart read, action apply (internal or authenticated), finalize, menu, transfer stub.
- Persistence: **SQLite** for POC — transcripts, orders, session state; sufficient for one-machine demos.
- **Orchestrator** (module): wires transcript events ↔ logic ↔ state ↔ phase machine ↔ dashboard.

## Failure and safety rules

- Unsafe or ambiguous extraction → `ask_clarification` or no-op; **do not guess** high-impact cart changes.
- Invalid actions → state engine rejects with a machine-readable error.
- **Final order** persisted only after **confirming** phase + explicit customer affirmation (orchestrator/API; PRD §5.7).

## Stack alignment (POC)

| Layer | Target | Fallback / note |
|-------|--------|------------------|
| Realtime | LiveKit Agents | Same session/cart API regardless of ingress (browser, mic, phone later). |
| Voice | Duplex (e.g. Moshi) | **Keep fallback real:** classic STT→LLM→TTS via LiveKit; Moshi has moving install/runtime surface on Apple Silicon. |
| Logic | Rules + / or MLX-LM | Extractor-only MVP; structured JSON actions out. |
| API + DB | FastAPI, SQLite | See production note below. |
| Dashboard | Next.js or minimal web | Transcript + cart JSON + completed orders. |

## Phone (later)

Twilio or SIP is another **audio ingress** into the same orchestrator, state engine, and session FSM; cart and action contracts stay unchanged.

## POC vs production (not required for MVP)

For production you would typically add: **Redis** (or similar) for hot session state, stronger **observability**, **idempotent** event handling, telephony **timeouts/retries**, and a formal **order submission** contract with the kitchen/POS. The POC intentionally stops at SQLite + local demo reliability.

## Document map

- [product-flow.md](./product-flow.md) — MVP PRD.
- [implementation-plan.md](./implementation-plan.md) — milestones and API sketch.
- [poc-checklist.md](./poc-checklist.md) — build order and demo criteria.
- [prompt-design.md](./prompt-design.md) — tone and phrasing rules.
- [oss-stack.md](./oss-stack.md) — OSS / no paid API defaults (rules, local LLM, self-hosted voice).

## Code map (POC)

| Area | Location |
|------|-----------|
| FastAPI entry | `apps/api/app/main.py` |
| Session / order routes | `apps/api/app/api/routes_sessions.py` |
| Cart / action models | `apps/api/app/schemas/` (`SessionPhase` in `session.py`) |
| DB models + repo | `apps/api/app/db/models.py`, `repo.py`, `database.py` |
| State engine + phase | `apps/api/app/services/state_engine.py` |
| Logic (rules extractor) | `apps/api/app/services/logic_loop.py` |
| Extractor dispatch + optional local LLM | `apps/api/app/services/logic_extract.py`, `logic_loop_llm.py` |
| Orchestrator | `apps/api/app/services/orchestrator.py` |
| Menu load + line validation | `apps/api/app/services/menu_catalog.py` |
| Dashboard | `apps/web/` |
| Local demo script | `poc/scripts/run_local_demo.py` |
| LiveKit stub | `poc/livekit_worker_stub.py` |
| Shared JSON Schema mirrors | `packages/shared/schemas/` |
| Staff prompt stub | `packages/shared/prompts/staff_prompt.txt` |
| Mock menu | `apps/api/data/menu.json` |
| Docker | `apps/api/Dockerfile`, `infra/docker-compose.yml` |
