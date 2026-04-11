# KitchenCall runbook — agent unavailable

Use this when dashboard shows `Agent status: unavailable (...)` or calls are not reaching the voice worker.

## 1) Identify failure mode

1. Check API status endpoint:
   - `GET /agent/status`
2. Note `reason`:
   - `heartbeat_missing`
   - `heartbeat_stale`
   - `heartbeat_invalid`
   - `heartbeat_missing_timestamp`

## 2) Fast triage

1. Validate worker config:
   - `cd apps/agent && python -m kitchencall_agent.worker --check`
2. Confirm worker process is running.
3. Confirm API and worker use the same heartbeat path:
   - `KITCHENCALL_AGENT_HEARTBEAT_PATH`
4. If Twilio is involved, confirm Twilio webhook deliveries are successful and call mappings exist:
   - `GET /telephony/twilio/calls/{call_sid}`

## 3) Recover service

1. Restart worker after fixing env/config.
2. Verify heartbeat recovers (`/agent/status` -> `available: true`).
3. Place one smoke test session:
   - dashboard LiveKit connect + one utterance
   - or Twilio inbound mapping + media flow check

## 4) Customer impact fallback

If recovery is not immediate:

1. Use transfer fallback path for active calls/sessions.
2. Notify staff to handle inbound calls manually.
3. Keep collecting transcript/order state where possible; avoid silent drops.

## 5) Rollback guidance

If outage started after deployment:

1. Roll back worker to last known good build.
2. Roll back API if `/agent/status` or telephony route regressions are suspected.
3. Re-run smoke checks before reopening traffic.

## 6) Post-incident notes

Capture:

- incident start/end time
- root cause
- affected sessions/calls
- corrective actions

