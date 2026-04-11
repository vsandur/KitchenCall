from typing import Literal

# Orchestrator phases — see docs/architecture.md (session state machine).
SessionPhase = Literal[
    "greeting",
    "ordering",
    "collecting_missing_info",
    "confirming",
    "submitted",
    "transfer_requested",
    "cancelled",
]
