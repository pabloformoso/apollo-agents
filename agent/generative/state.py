"""Musical-state serializer (A-5, minimal for the spike).

Just enough for the mind to reason: what is playing now, how long it has
been playing, the standing human intent, and the last few reasons (so it
can avoid repeating itself). Compact by design — R3 says garbage state
produces generic music, but so does a bloated prompt.
"""

from __future__ import annotations

import json

from .spec import PatternSpec

MAX_RECENT_REASONS = 5


def build_state(
    current_spec: PatternSpec,
    bars_elapsed: int,
    intent: str,
    recent_reasons: list[str],
    jitter_ms: float | None = None,
) -> dict:
    state = {
        "now_playing": current_spec.summary(),
        "bars_elapsed": bars_elapsed,
        "standing_intent": intent.strip() or "none — keep the groove evolving naturally",
        "recent_reasons": recent_reasons[-MAX_RECENT_REASONS:],
    }
    if jitter_ms is not None:
        state["clock_p99_jitter_ms"] = jitter_ms
    return state


def to_prompt(state: dict) -> str:
    return json.dumps(state, ensure_ascii=False, indent=2)
