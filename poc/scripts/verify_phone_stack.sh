#!/usr/bin/env bash
# Smoke-test KitchenCall + PersonaPlex from the host where the API runs.
# Usage: ./poc/scripts/verify_phone_stack.sh [BASE_URL]
# Example: ./poc/scripts/verify_phone_stack.sh http://127.0.0.1:8000

set -euo pipefail
BASE="${1:-http://127.0.0.1:8000}"

echo "== GET $BASE/health =="
curl -sS -f "$BASE/health" | python3 -m json.tool

echo "== GET $BASE/telephony/twilio/debug-status =="
curl -sS -f "$BASE/telephony/twilio/debug-status" | python3 -m json.tool

echo "== GET $BASE/telephony/twilio/personaplex-probe =="
curl -sS -m 30 "$BASE/telephony/twilio/personaplex-probe" | python3 -m json.tool

echo "Done. personaplex-probe should show ok:true and handshake_first_byte:0 when PersonaPlex is healthy."
