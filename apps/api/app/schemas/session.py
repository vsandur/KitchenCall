from __future__ import annotations

from typing import Literal

# Session lifecycle phase (persisted on KitchenSession.phase; aligned with state_engine.phase_from_state).
SessionPhase = Literal[
    "greeting",
    "ordering",
    "collecting_missing_info",
    "confirming",
    "submitted",
    "cancelled",
    "transfer_requested",
]
