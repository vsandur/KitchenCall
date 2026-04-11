#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request


def post_form(url: str, data: dict[str, str]) -> tuple[int, str]:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
        return resp.status, resp.read().decode("utf-8")


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as resp:  # nosec B310
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    p = argparse.ArgumentParser(description="Verify Twilio mapping routes without placing a real call.")
    p.add_argument("--base", default="http://127.0.0.1:8000", help="API base URL")
    p.add_argument("--call-sid", default="CA_VERIFY_001", help="Synthetic Twilio CallSid")
    args = p.parse_args()

    base = args.base.rstrip("/")
    call_sid = args.call_sid

    inbound_url = f"{base}/telephony/twilio/inbound"
    status_url = f"{base}/telephony/twilio/status"
    call_url = f"{base}/telephony/twilio/calls/{call_sid}"

    code, xml = post_form(
        inbound_url,
        {"CallSid": call_sid, "From": "+14155550123", "To": "+14155550999"},
    )
    print(f"inbound: HTTP {code}")
    print(xml[:180] + ("..." if len(xml) > 180 else ""))

    mapped = get_json(call_url)
    print("mapped:", mapped)
    if not mapped.get("found"):
        raise SystemExit("expected call mapping to exist")

    code2, status_body = post_form(status_url, {"CallSid": call_sid, "CallStatus": "completed"})
    print(f"status: HTTP {code2} {status_body}")

    mapped_after = get_json(call_url)
    print("mapped_after:", mapped_after)
    if mapped_after.get("status") != "completed":
        raise SystemExit("expected status=completed")

    print("Twilio mapping verification: OK")


if __name__ == "__main__":
    main()
