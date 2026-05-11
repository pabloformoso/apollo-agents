"""Unit tests for ``web.backend.brief_parser``.

The LLM call inside ``parse`` is exercised only via monkeypatched stubs
so the suite stays deterministic and free of network calls. The pure
``_normalize`` helper is the bulk of the coverage — it's where the
type-coercion + clamp + enum-validation logic lives.
"""
from __future__ import annotations

import pytest

from web.backend import brief_parser
from web.backend.brief_parser import _empty, _normalize, parse


# ─── _normalize ──────────────────────────────────────────────────────


def test_normalize_empty_input_returns_all_nulls():
    out = _normalize({})
    assert out == _empty()


def test_normalize_strips_and_lowercases_genre():
    out = _normalize({"genre": "  Deep House  "})
    assert out["genre"] == "deep house"


def test_normalize_rejects_blank_genre():
    out = _normalize({"genre": "   "})
    assert out["genre"] is None


def test_normalize_clamps_duration_range():
    assert _normalize({"duration_min": 0})["duration_min"] is None
    assert _normalize({"duration_min": -5})["duration_min"] is None
    assert _normalize({"duration_min": 1})["duration_min"] == 1
    assert _normalize({"duration_min": 600})["duration_min"] == 600
    assert _normalize({"duration_min": 601})["duration_min"] is None


def test_normalize_floors_float_duration():
    assert _normalize({"duration_min": 45.7})["duration_min"] == 45


def test_normalize_accepts_known_venues_only():
    assert _normalize({"venue": "garden"})["venue"] == "garden"
    assert _normalize({"venue": "  Bar "})["venue"] == "bar"
    # Unknown venue is stripped to None rather than passed through.
    assert _normalize({"venue": "stadium"})["venue"] is None


def test_normalize_accepts_known_energy_values_only():
    for v in ("plateau", "with peak", "building", "descending"):
        assert _normalize({"energy": v})["energy"] == v
    assert _normalize({"energy": "explosive"})["energy"] is None


def test_normalize_preserves_mood_and_tempo_strings():
    out = _normalize({"mood": " chill ", "tempo": "120–128 BPM"})
    assert out["mood"] == "chill"
    assert out["tempo"] == "120–128 BPM"


def test_normalize_handles_wrong_types_gracefully():
    out = _normalize({
        "genre": 42,             # non-string → null
        "duration_min": "thirty",  # non-numeric → null
        "mood": None,            # explicit null → null
        "venue": ["garden"],     # wrong shape → null
        "energy": "loud",        # not in enum → null
        "tempo": False,          # non-string → null
    })
    assert out == _empty()


# ─── parse (LLM seam monkeypatched) ──────────────────────────────────


def test_parse_empty_brief_short_circuits(monkeypatch):
    """No API call when the brief is empty / whitespace."""
    import anthropic

    called = {"n": 0}

    class _Boom:
        def __init__(self):
            called["n"] += 1
            raise AssertionError("Anthropic should not have been called")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(anthropic, "Anthropic", _Boom, raising=False)
    assert parse("") == _empty()
    assert parse("   \n\t") == _empty()
    assert called["n"] == 0


def test_parse_missing_api_key_returns_empty(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert parse("30 min of lofi") == _empty()


def test_parse_returns_normalized_payload(monkeypatch):
    """Stub the SDK so the parser receives a tool_use block and the
    output is run through ``_normalize``.

    The parser does ``from anthropic import Anthropic`` inside the
    function body so we patch the attribute on the ``anthropic``
    module itself rather than on ``brief_parser``.
    """
    import anthropic

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    class _Block:
        def __init__(self):
            self.type = "tool_use"
            self.name = "report_brief"
            self.input = {
                "genre": "LoFi",
                "duration_min": 30,
                "mood": "chill",
                "venue": "garden",
                "energy": "plateau",
                "tempo": "60–66 BPM",
            }

    class _Response:
        content = [_Block()]

    class _Messages:
        def create(self, **_):
            return _Response()

    class _Client:
        def __init__(self):
            self.messages = _Messages()

    monkeypatch.setattr(anthropic, "Anthropic", _Client, raising=False)
    out = parse("30 minute lofi set in a garden")
    assert out == {
        "genre": "lofi",       # lowercased by _normalize
        "duration_min": 30,
        "mood": "chill",
        "venue": "garden",
        "energy": "plateau",
        "tempo": "60–66 BPM",
    }


def test_parse_handles_sdk_exception(monkeypatch):
    """Any failure inside the LLM call must degrade to all-null rather
    than crash the calling endpoint."""
    import anthropic

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    class _ExplodingClient:
        def __init__(self):
            raise RuntimeError("simulated SDK failure")

    monkeypatch.setattr(anthropic, "Anthropic", _ExplodingClient, raising=False)
    assert parse("90 minute techno set") == _empty()


def test_parse_handles_response_without_tool_use(monkeypatch):
    """If the LLM somehow returns plain text instead of a tool_use block,
    fall through to all-null defensively."""
    import anthropic

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    class _TextBlock:
        type = "text"
        text = "no tool use here"

    class _Response:
        content = [_TextBlock()]

    class _Messages:
        def create(self, **_):
            return _Response()

    class _Client:
        def __init__(self):
            self.messages = _Messages()

    monkeypatch.setattr(anthropic, "Anthropic", _Client, raising=False)
    assert parse("anything") == _empty()
