# KitchenCall — Implementation plan (Phase 1 POC)

This plan turns **[product-flow.md](./product-flow.md)** (MVP PRD) and **[architecture.md](./architecture.md)** into sequenced work. Track granular tasks with **[poc-checklist.md](./poc-checklist.md)**.

## Goals (Phase 1 exit)

1. **Structured truth**: cart + actions + state engine are the source of truth; logic never “ghost-writes” the cart in prose.  
2. **PRD behavior**: confirmation gate (§5.7), transfer stub (§5.10), menu validation (§5.3), ambiguity handling (§5.5).  
3. **Demo**: scripted flows A–C on **[poc-checklist.md](./poc-checklist.md)** with dashboard showing transcript + live cart + completed order.

## Non-goals for Phase 1

- Real phone ingress, payments, POS, delivery dispatch (see PRD §8).  
- Production Moshi integration is **stretch**; architecture allows STT/TTS fallback (see **[architecture.md](./architecture.md)** stack table).

---

## Milestones

### M0 — Repo scaffold (~0.5 day)

- Create monorepo-style layout (below).  
- Root `README` already points at docs; add `pyproject.toml` or `requirements.txt` when `apps/api` exists.  
- Optional: `docker-compose.yml` for API + DB volume later; not blocking for local SQLite.

**Suggested layout** (adapt names if you prefer flat structure):

```text
KitchenCall/
  apps/
    api/                 # FastAPI, state engine, SQLite
    web/                 # minimal dashboard (Next or Vite+React)
  packages/
    shared/
      schemas/           # JSON Schema or Pydantic-shared exports
      prompts/           # staff_prompt.txt
  poc/
    scripts/             # run_local_demo.py, replay fixtures
    test_cases/          # transcript → expected actions/cart
  docs/                  # existing
```

### M1 — Contracts (~1–2 days)

- **Cart schema** and **action schema** as single source of truth: prefer Pydantic models in `apps/api` with optional JSON Schema export under `packages/shared/schemas/`.  
- **Mock menu JSON**: categories, items, sizes, modifier groups, required choices, `unavailable` flags.  
- **Menu validation** helper: resolve `menu_item_id`, validate modifiers/size, return errors for state engine and logic loop.

**Blocks:** M2 (engine needs shapes), M4 (API serves menu/cart).

### M2 — State engine + tests (~2–4 days)

- Implement `apply_action(cart, action) -> cart | errors` deterministically.  
- Intents: at minimum `add_item`, `modify_item`, `remove_item`, `set_order_type`, `set_customer_info`, `ask_clarification` (no-op on cart if handled upstream), `confirm_order` (transition metadata / status only — final persist still gated in API per §5.7).  
- Tests: corrections, quantity, modifier add/remove, illegal menu refs, ambiguous target (expect error or explicit clarification action — no silent wrong line).

**Blocks:** M3 orchestration stub, M4 finalize rules.

### M3 — Logic loop stub (~1–3 days)

- **v0**: rule-based or fixture-driven mapping from transcript lines → actions for demos.  
- **v1**: MLX / small model outputs **only** JSON actions; invalid JSON → retry or `ask_clarification`.  
- Wire **staff prompt** ([prompt-design.md](./prompt-design.md)) + **cart snapshot** as context for generation.

**Blocks:** M5 full conversation path; can parallel M4 after M1.

### M4 — FastAPI + SQLite (~2–3 days)

- Sessions: create, append transcript segment, get cart, post action(s) (internal or from logic service), **finalize** only if business rules satisfied + explicit confirm recorded.  
- Persist: `sessions`, `transcript_events`, `orders` (completed rows).  
- **Transfer**: endpoint or intent sets `session.transfer_requested` (or equivalent) and returns stub copy; log event (§5.10).  
- **SSE or WebSocket** (optional) or **poll** for dashboard: session id, latest cart, transcript tail.

**Depends on:** M1, M2.

### M5 — Minimal dashboard (~2–3 days)

- Pages/sections: current session selector, transcript panel, cart JSON (pretty), completed orders list.  
- Use API poll first; upgrade to push if needed.

**Depends on:** M4.

### M6 — Audio / LiveKit integration (~variable)

- Prove **LiveKit Agents** session lifecycle + injection of text events into logic loop + cart updates back to agent context.  
- **Duplex**: target Moshi path per architecture; if blocked, document **fallback** STT/TTS and still run demos A–B on cart accuracy.

**Depends on:** M3 + M4 (can stub audio with typed text for all cart demos first).

---

## Dependency sketch

```text
M1 schemas/menu ──► M2 state engine ──► M4 API finalize rules
        │                    │
        └────────────────────┼──► M3 logic loop
                             │
                             ▼
                        M5 dashboard ◄── M4
                             │
M6 LiveKit/audio ────────────┘ (cart demos can skip M6 initially)
```

## Order of execution (recommended)

1. M0 scaffold  
2. M1 → M2 → M4 (core product vertical)  
3. M5 dashboard  
4. M3 logic (start with rules/fixtures, then model)  
5. M6 audio when the vertical is stable  

This matches **[poc-checklist.md](./poc-checklist.md)** “First implementation order,” with explicit milestones.

---

## API shape (draft)

Define properly in code; this is planning-level only.

| Concern | Sketch |
|--------|--------|
| Session | `POST /sessions`, `GET /sessions/{id}` |
| Transcript | `POST /sessions/{id}/transcript` (append text segment) |
| Cart | `GET /sessions/{id}/cart` |
| Actions | `POST /sessions/{id}/actions` (validate + apply via engine) or internal-only after logic loop |
| Finalize | `POST /sessions/{id}/finalize` — **403/409** unless confirm gate satisfied |
| Menu | `GET /menu` |
| Dashboard feed | `GET /sessions/{id}/stream` or poll composite endpoint |

---

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Moshi build / integration slips schedule | Ship M1–M5 with **text-in** demo; audio is layer swap per architecture |
| Model hallucinates cart | **Only** state engine mutates cart; model emits **actions** only |
| Demo script fragile | Lock **one** mock menu + **poc/test_cases** golden files |

---

## Definition of Done (Phase 1)

- [ ] All Phase 1 items checked in **[poc-checklist.md](./poc-checklist.md)** that apply without LiveKit, **or** explicitly deferred with a listed reason.  
- [ ] Demos A–B pass with cart JSON matching spoken summary; demo C as far as audio stack allows.  
- [ ] PRD §5.7 and §5.10 reflected in API behavior (tests or manual script documented in `poc/scripts`).

---

## Next action

Execute **M0 + M1**: create `apps/api` with Pydantic models, JSON files for mock menu, and empty FastAPI app with `/health` and `/menu` reading the fixture.

---

## Production flow backlog (next 10 tickets)

These are the highest-priority tickets to move from POC to the PRD's production flow.

### Sprint A — Channel + reliability baseline

1. **Telephony ingress MVP**
   - Add inbound phone entry (SIP/Twilio) mapped to KitchenCall sessions.
   - **Acceptance:** real phone call creates a session and enters the same cart/orchestrator path as dashboard/LiveKit.

2. **Live transfer handoff (replace stub)**
   - Implement real human transfer path (bridge, failover message, transfer outcome logging).
   - **Acceptance:** transfer intent routes to staff line and marks session outcome (`transferred`, `transfer_failed`, etc.).

3. **Dispatch and worker readiness guardrails**
   - Add health/readiness endpoint + startup checks for LiveKit worker and telephony bridge.
   - **Acceptance:** misconfigured deployment fails fast; dashboard/API can display "agent unavailable" state.

### Sprint B — Operational hardening

4. **Session state machine hardening**
   - Formalize allowed phase transitions (`greeting -> ordering -> confirming -> completed` and transfer branches).
   - **Acceptance:** invalid transitions blocked with tests and clear API errors.

5. **Idempotent finalize + replay safety**
   - Implemented: repeat `POST /sessions/{id}/finalize` after success returns **200** with the same `saved_order_id` and `idempotent_replay: true` (no extra `saved_orders` row).
   - **Acceptance:** multiple finalize attempts yield one saved order and deterministic response codes.

6. **Observability v1**
   - Emit structured logs/metrics for STT latency, `process-turn` latency, TTS latency, turn errors, transfer outcomes.
   - **Acceptance:** one dashboard/query shows session success/failure and top error causes for last 24h.

### Sprint C — Product completeness

7. **Ambiguity resolution quality pass**
   - Tighten unresolved-reference flow ("that one", "first one"), including max clarification retries and fallback transfer.
   - **Acceptance:** scripted ambiguity suite passes without wrong high-impact cart edits.

8. **Customer profile + order history (Phase 2 core)**
   - Persist customer identity keys (phone-based) and past completed carts.
   - **Acceptance:** API can return recent order history for known caller.

9. **Reorder flow**
   - Add "same as last time" path with explicit confirmation and editable replay into cart actions.
   - **Acceptance:** caller can reorder prior order and still modify before final confirmation.

### Sprint D — Scale + release safety

10. **Load and failure testing**
   - Add soak/load test profile (concurrent active sessions), plus chaos tests for STT/TTS/API dependency timeouts.
   - **Acceptance:** documented operating limits and fallback behavior (degrade/transfer) under stress.

---

## Recommended execution order (2-4 weeks)

- **Week 1:** tickets 1-3 (channel + availability baseline)
- **Week 2:** tickets 4-6 (correctness + observability)
- **Week 3:** tickets 7-9 (PRD quality + repeat customer value)
- **Week 4:** ticket 10 + stabilization bugfix buffer
