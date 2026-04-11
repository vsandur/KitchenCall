#!/usr/bin/env python3
"""Walk through a minimal ordering flow against a running API (default http://127.0.0.1:8000)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _post(base: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body or {}).encode("utf-8") if body is not None else b"{}"
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return e.code, {"detail": raw}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8000", help="API base URL")
    args = p.parse_args()
    base = args.base.rstrip("/")

    code, sess = _post(base, "/sessions", {})
    if code != 201:
        print("create session failed", code, sess)
        return 1
    sid = sess["id"]
    print("session", sid)

    turns = [
        "large pepperoni for pickup",
        "garlic knots",
        "Coke",
        "name is Alex",
        "phone is 555-123-4567",
        "that's all",
        "yes",
    ]
    for t in turns:
        code, body = _post(base, f"/sessions/{sid}/process-turn", {"text": t})
        if code != 200:
            print("process-turn failed", t, code, body)
            return 1
        print(">", t)
        print("  intents:", body.get("applied_intents"), "errors:", body.get("errors"))
        if body.get("affirmation_hint"):
            print("  hint:", body["affirmation_hint"])

    code, fin = _post(base, f"/sessions/{sid}/finalize", {"affirmed": True})
    if code != 200:
        print("finalize failed:", code, fin)
        return 1
    print("finalize", fin)

    return 0


if __name__ == "__main__":
    sys.exit(main())
