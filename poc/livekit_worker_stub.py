"""
Deprecated entrypoint name — use the real worker instead:

  cd apps/agent && python -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  export LIVEKIT_URL=... LIVEKIT_API_KEY=... LIVEKIT_API_SECRET=...
  export KITCHENCALL_API_BASE=http://127.0.0.1:8000
  export OPENAI_API_KEY=...
  python -m kitchencall_agent.worker dev

See README.md (LiveKit section) and docs/architecture.md.
"""

from __future__ import annotations

import sys


def main() -> None:
    print(
        "This stub is retired. Run: python -m kitchencall_agent.worker (from apps/agent).",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
