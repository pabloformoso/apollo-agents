"""Apollo v2.6.0 — one-shot brief parser.

Extracts the six "understood as" fields from a user's single-sentence
brief using a forced tool call against Haiku 4.5. Cheap (<300 ms,
~$0.0001 per call) and strict about null fields — the prompt forbids
guessing so the downstream planner only sees user-stated context.

Returns ``ParsedBrief`` with ``None`` for any unstated field. The
planner's ``phase_genre_guard`` handles the conversational fill-in for
missing fields, so leaving them ``None`` here is the correct fallback
rather than hallucinating values.
"""
from __future__ import annotations

import logging
import os
from typing import TypedDict


log = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"

_VALID_ENERGY = {"plateau", "with peak", "building", "descending"}
_VALID_VENUES = {
    "garden", "cafe", "bar", "club", "warehouse",
    "office", "home", "car", "gym",
}


class ParsedBrief(TypedDict):
    genre: str | None
    duration_min: int | None
    mood: str | None
    venue: str | None
    energy: str | None
    tempo: str | None


_SYSTEM = """Extract these six fields from a music-set brief. Return null for any field the user did not state.
Do not guess. Do not invent.

- genre: lowercase string ("lofi", "techno", "deep house", "neo-soul", "ambient", "synthwave"…).
- duration_min: integer minutes. "an hour" → 60, "ninety minutes" → 90, "an hour and a half" → 90.
- mood: a single word or short phrase ("chill", "warm", "intense", "melancholic").
- venue: one of {garden, cafe, bar, club, warehouse, office, home, car, gym}. Null if no venue mentioned.
- energy: one of {plateau, with peak, building, descending}. Null if unstated.
- tempo: BPM range string like "120–128 BPM", or "auto" when no tempo was given.
"""

_TOOL = {
    "name": "report_brief",
    "description": "Report the six fields extracted from the brief.",
    "input_schema": {
        "type": "object",
        "properties": {
            "genre": {"type": ["string", "null"]},
            "duration_min": {"type": ["integer", "null"]},
            "mood": {"type": ["string", "null"]},
            "venue": {"type": ["string", "null"]},
            "energy": {"type": ["string", "null"]},
            "tempo": {"type": ["string", "null"]},
        },
        "required": ["genre", "duration_min", "mood", "venue", "energy", "tempo"],
    },
}


def _empty() -> ParsedBrief:
    return {
        "genre": None,
        "duration_min": None,
        "mood": None,
        "venue": None,
        "energy": None,
        "tempo": None,
    }


def _normalize(raw: dict) -> ParsedBrief:
    """Coerce types and clamp values the LLM returned.

    Defensive: even with ``tool_choice`` forcing a tool call, the LLM may
    return out-of-range integers or unexpected enum values. We strip
    invalid values back to ``None`` so the planner never sees junk.
    """
    out = _empty()

    g = raw.get("genre")
    if isinstance(g, str) and g.strip():
        out["genre"] = g.strip().lower()

    d = raw.get("duration_min")
    if isinstance(d, (int, float)) and 1 <= int(d) <= 600:
        out["duration_min"] = int(d)

    for key in ("mood", "tempo"):
        v = raw.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()

    venue = raw.get("venue")
    if isinstance(venue, str) and venue.strip().lower() in _VALID_VENUES:
        out["venue"] = venue.strip().lower()

    energy = raw.get("energy")
    if isinstance(energy, str) and energy.strip().lower() in _VALID_ENERGY:
        out["energy"] = energy.strip().lower()

    return out


def parse(brief: str) -> ParsedBrief:
    """Run the parser. Synchronous — call via ``asyncio.to_thread``.

    Returns all-null on any failure (no API key, network error, malformed
    response). The downstream planner treats missing fields as "ask the
    user", so a parser failure degrades gracefully into the legacy
    conversational genre-guard flow.
    """
    if not (brief or "").strip():
        return _empty()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY not set; brief_parser returning all-null")
        return _empty()
    try:
        from anthropic import Anthropic  # noqa: PLC0415 — local import keeps
        # the module importable in environments without the SDK (e.g. unit
        # tests that monkeypatch this function).
        client = Anthropic()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=_SYSTEM,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "report_brief"},
            messages=[{"role": "user", "content": brief}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and \
                    getattr(block, "name", None) == "report_brief":
                return _normalize(dict(block.input))
    except Exception as exc:  # noqa: BLE001 — never crash a session POST
        log.exception("brief_parser failure: %s", exc)
    return _empty()
