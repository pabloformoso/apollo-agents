"""Apollo v2.6.0 — one-shot brief parser.

Extracts the six "understood as" fields from a user's single-sentence
brief and is strict about null fields — the prompt forbids guessing so
the downstream planner only sees user-stated context.

Provider (v3.11): the parser follows the SAME provider the rest of the
app is configured with (``AGENT_PROVIDER``, detection mirrored from
``agent/run.py``). It used to call Anthropic unconditionally, which
meant that on an install without ``ANTHROPIC_API_KEY`` — the local
LM Studio setup since 2026-07-12 — every free-text brief silently
parsed to all-null and was thrown away. Anthropic remains supported;
it is simply no longer assumed.

Two shapes of call, because the providers differ in what they do well:

* **anthropic** — a forced ``report_brief`` tool call. Structured and
  exact; keeps using cheap Haiku rather than the session's big model.
* **azure / ollama (any OpenAI-compatible endpoint, incl. LM Studio)** —
  a plain completion that must answer with a JSON object. Deliberately
  NOT tool-calling: the small local models this path serves are far
  more reliable at emitting JSON than at the function-calling
  interface (the same weakness that makes them skip ``extend_set``
  live), and ``_normalize`` already treats the payload as untrusted.

Returns ``ParsedBrief`` with ``None`` for any unstated field. The
planner's ``phase_genre_guard`` handles the conversational fill-in for
missing fields, so leaving them ``None`` here is the correct fallback
rather than hallucinating values.
"""
from __future__ import annotations

import json
import logging
import os
from typing import TypedDict


log = logging.getLogger(__name__)

# Extraction is a small, cheap job — pin a small model per provider
# instead of borrowing AGENT_MODEL, which points at the session's
# planner-grade model.
MODEL = "claude-haiku-4-5-20251001"

# Local models are seconds, not milliseconds (Haiku was ~300 ms). The
# call blocks a session POST via ``asyncio.to_thread``, so it needs a
# bound: past this the user is better served by the conversational
# genre-guard than by a spinner.
#
# Raised 30 -> 45 on 2026-08-18. qwen3.6-27b behind the LiteLLM proxy
# measured 29.5 s on this prompt — half a second under the old bound, so
# the parse was a coin flip between a good answer and a timeout. This is
# a deliberate UX trade: a longer spinner in exchange for a brief that
# actually parses. If a model ever needs more than this, it is the wrong
# model for a request-blocking path, not a reason to raise the bound
# again.
TIMEOUT_SEC = 45.0

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


_FIELDS = ("genre", "duration_min", "mood", "venue", "energy", "tempo")

_SYSTEM = """Extract these six fields from a music-set brief. Return null for any field the user did not state.
Do not guess. Do not invent.

- genre: lowercase string ("lofi", "techno", "deep house", "neo-soul", "ambient", "synthwave"…).
- duration_min: integer minutes. "an hour" → 60, "ninety minutes" → 90, "an hour and a half" → 90.
- mood: a single word or short phrase ("chill", "warm", "intense", "melancholic").
- venue: one of {garden, cafe, bar, club, warehouse, office, home, car, gym}. Null if no venue mentioned.
- energy: one of {plateau, with peak, building, descending}. Null if unstated.
- tempo: BPM range string like "120–128 BPM", or "auto" when no tempo was given.
"""

# Appended for the OpenAI-compatible path, which has no forced tool call
# to guarantee the shape.
_JSON_SUFFIX = """
Answer with a single JSON object and nothing else — no prose, no
markdown fences, no explanation. Exactly these keys:

{"genre": ..., "duration_min": ..., "mood": ..., "venue": ..., "energy": ..., "tempo": ...}

Use null (not "null", not "") for every field the user did not state.
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
        "required": list(_FIELDS),
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


def detect_provider() -> str:
    """Return the configured provider name.

    Mirrors ``agent/run.py`` / ``web/backend/pipeline.py`` detection, but
    read at CALL time rather than import time so a process that loads its
    ``.env`` late (or a test that monkeypatches env) still gets it right.

    ``mock`` is passed through untouched: E2E runs set
    ``AGENT_PROVIDER=mock`` precisely so nothing reaches a network.
    """
    provider = os.environ.get("AGENT_PROVIDER", "").strip().lower()
    if provider:
        return provider
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("AZURE_OPENAI_API_KEY"):
        return "azure"
    if os.environ.get("LITELLM_BASE_URL"):
        return "litellm"
    if os.environ.get("OLLAMA_BASE_URL"):
        return "ollama"
    return "anthropic"


def extract_json_object(text: str) -> dict | None:
    """Pull the first balanced ``{...}`` object out of a model reply.

    Small models wrap JSON in prose or ```json fences however firmly the
    prompt forbids it, so scanning beats trusting. Brace counting is
    string-aware: a ``}`` inside ``"mood"`` must not close the object.

    Returns ``None`` when there is no parseable object — the caller then
    degrades to all-null exactly as a failed call would.
    """
    if not text:
        return None
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


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
    # bool is an int subclass — True would sneak through as 1 minute.
    if isinstance(d, (int, float)) and not isinstance(d, bool) and 1 <= int(d) <= 600:
        out["duration_min"] = int(d)
    elif isinstance(d, str):
        # The OpenAI-compatible path has no schema to enforce the type,
        # and small models routinely quote the number ("60", "60 min").
        digits = "".join(ch for ch in d if ch.isdigit())
        if digits and 1 <= int(digits) <= 600:
            out["duration_min"] = int(digits)

    for key in ("mood", "tempo"):
        v = raw.get(key)
        if isinstance(v, str) and v.strip() and v.strip().lower() != "null":
            out[key] = v.strip()

    venue = raw.get("venue")
    if isinstance(venue, str) and venue.strip().lower() in _VALID_VENUES:
        out["venue"] = venue.strip().lower()

    energy = raw.get("energy")
    if isinstance(energy, str) and energy.strip().lower() in _VALID_ENERGY:
        out["energy"] = energy.strip().lower()

    return out


def _parse_anthropic(brief: str) -> ParsedBrief:
    """Forced-tool-call extraction against Haiku."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY not set; brief_parser returning all-null")
        return _empty()
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
    return _empty()


def _build_openai_client(provider: str):
    """Client + model for the OpenAI-compatible providers.

    ``ollama`` is the generic OpenAI-compatible path (it is what serves
    LM Studio over the Tailscale node), not Ollama specifically.
    ``litellm`` is the same path pointed at the team's LiteLLM proxy,
    which does validate its API key.
    """
    if provider == "azure":
        from openai import AzureOpenAI  # noqa: PLC0415
        client = AzureOpenAI(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            timeout=TIMEOUT_SEC,
        )
        return client, os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
    from openai import OpenAI  # noqa: PLC0415
    if provider == "litellm":
        base_url = os.environ["LITELLM_BASE_URL"]
        api_key = os.getenv("LITELLM_API_KEY", "sk-litellm")
        default_model = "qwen3.6-27b"
    else:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        api_key = "ollama"  # key is unused by Ollama / LM Studio
        default_model = "gemma4:4b"
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=TIMEOUT_SEC)
    return client, os.getenv("AGENT_MODEL", default_model)


#: The JSON payload itself is ~80 tokens, but a reasoning model spends its
#: budget thinking before it emits a single character of content. gemma4:12b
#: (local Ollama since 2026-08-17) needs 502-523 tokens for this prompt, so
#: the old 512 ceiling truncated the object mid-key and `extract_json_object`
#: returned None — every free-text brief silently parsed to all-null. This is
#: a ceiling, not a target: non-reasoning models still stop at ~80 tokens and
#: pay nothing for the headroom.
#:
#: Raised 1536 -> 3072 on 2026-08-18: qwen3.6-27b (LiteLLM proxy) spends
#: ~2010 tokens on this prompt, four times what gemma4 needed, and at 1536
#: returned finish_reason="length" with an EMPTY body — not even a partial
#: object to salvage.
_OPENAI_MAX_TOKENS = 3072


def _parse_openai_compatible(brief: str, provider: str) -> ParsedBrief:
    """JSON-object extraction against Azure OpenAI or a local endpoint."""
    client, model = _build_openai_client(provider)
    if not model:
        log.warning("brief_parser: no model configured for provider %r", provider)
        return _empty()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM + _JSON_SUFFIX},
            {"role": "user", "content": brief},
        ],
        max_tokens=_OPENAI_MAX_TOKENS,
        temperature=0.0,  # extraction, not composition
    )
    text = (resp.choices[0].message.content or "").strip()
    raw = extract_json_object(text)
    if raw is None:
        log.warning("brief_parser: no JSON object in %r reply: %.120s", provider, text)
        return _empty()
    return _normalize(raw)


def parse(brief: str) -> ParsedBrief:
    """Run the parser. Synchronous — call via ``asyncio.to_thread``.

    Returns all-null on any failure (no API key, network error, malformed
    response). The downstream planner treats missing fields as "ask the
    user", so a parser failure degrades gracefully into the legacy
    conversational genre-guard flow.
    """
    if not (brief or "").strip():
        return _empty()
    provider = detect_provider()
    if provider == "mock":
        return _empty()
    try:
        if provider == "anthropic":
            return _parse_anthropic(brief)
        return _parse_openai_compatible(brief, provider)
    except Exception as exc:  # noqa: BLE001 — never crash a session POST
        log.exception("brief_parser failure: %s", exc)
    return _empty()
