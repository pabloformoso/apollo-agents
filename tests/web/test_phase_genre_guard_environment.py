"""Tests for v2.5.0 — environment field flows through Genre Guard into ctx.

The interesting glue is in ``agent/run.py::_parse_confirmed_block`` (which
``web/backend/pipeline.py`` re-exports through its own
``phase_genre_guard``). These tests pin three properties:

1. A 4-field CONFIRMED block parses cleanly and ``environment`` lands in
   the returned dict (and therefore in ``ctx`` once ``app.py`` does
   ``s.context_variables.update(confirmed)``).
2. A pre-v2.5 3-field CONFIRMED block keeps parsing — ``environment``
   defaults to ``"unspecified"`` so older sessions/CLI flows don't break.
3. Free-text values containing punctuation (commas, dashes, quotes,
   accented characters) round-trip exactly — the parser strips outer
   whitespace but otherwise leaves the string intact.

We test the parser directly (it lives in ``agent.run`` and the pipeline
re-exports it) rather than spinning up a full streaming run, because the
genre-guard phase is just `_parse_confirmed_block(streamed_response)`.
"""
from __future__ import annotations

from agent.run import _parse_confirmed_block
from web.backend import pipeline


# ---------------------------------------------------------------------------
# Property 1 — full 4-field block populates environment in the parsed dict
# ---------------------------------------------------------------------------

class TestConfirmedBlockParsesEnvironmentField:
    def test_confirmed_block_parses_environment_field(self):
        """A 4-field block emits {genre, duration_min, mood, environment}
        with each field set to the user's literal value."""
        text = (
            "Sounds good — confirming.\n"
            "CONFIRMED\n"
            "genre: techno\n"
            "duration_min: 60\n"
            "mood: dark industrial build\n"
            "environment: loud crowded bar\n"
        )
        result = _parse_confirmed_block(text)
        assert result is not None
        assert result["genre"] == "techno"
        assert result["duration_min"] == 60
        assert result["mood"] == "dark industrial build"
        assert result["environment"] == "loud crowded bar"

    def test_pipeline_reexports_same_parser(self):
        """``web/backend/pipeline.py`` imports ``_parse_confirmed_block``
        from ``agent.run`` and reuses it inside ``phase_genre_guard``. We
        verify the symbol is the same object so any future change to the
        parser is automatically picked up by the pipeline."""
        assert pipeline._parse_confirmed_block is _parse_confirmed_block


# ---------------------------------------------------------------------------
# Property 2 — backward compat with pre-v2.5 (3-field) blocks
# ---------------------------------------------------------------------------

class TestConfirmedBlockBackwardCompat:
    def test_confirmed_block_defaults_to_unspecified_when_missing(self):
        """A 3-field block (no environment line) parses successfully and
        the returned dict carries ``environment="unspecified"``."""
        text = (
            "CONFIRMED\n"
            "genre: lofi - ambient\n"
            "duration_min: 30\n"
            "mood: rainy afternoon\n"
        )
        result = _parse_confirmed_block(text)
        assert result is not None
        assert result["environment"] == "unspecified"

    def test_empty_environment_value_normalizes_to_unspecified(self):
        """An ``environment:`` line with an empty value (the LLM may emit
        ``environment: `` if the user said "skip") normalizes to the
        sentinel — downstream code reads ``ctx.environment`` and assumes
        a non-empty string."""
        text = (
            "CONFIRMED\n"
            "genre: techno\n"
            "duration_min: 60\n"
            "mood: dark\n"
            "environment: \n"
        )
        result = _parse_confirmed_block(text)
        assert result is not None
        assert result["environment"] == "unspecified"


# ---------------------------------------------------------------------------
# Property 3 — special characters round-trip
# ---------------------------------------------------------------------------

class TestConfirmedBlockEnvironmentSpecialChars:
    def test_confirmed_block_environment_with_special_chars(self):
        """Values like "smoky club, low light" round-trip correctly. The
        parser strips outer whitespace but does NOT mangle commas or
        other punctuation embedded in the value."""
        text = (
            "CONFIRMED\n"
            "genre: cyberpunk\n"
            "duration_min: 45\n"
            "mood: gritty\n"
            "environment: smoky club, low light\n"
        )
        result = _parse_confirmed_block(text)
        assert result is not None
        assert result["environment"] == "smoky club, low light"

    def test_confirmed_block_environment_with_accents_and_punctuation(self):
        """Accented characters (Spanish "í", "ñ"), apostrophes, and
        em-dashes survive the round trip. This protects the ES/EN
        bilingual user base."""
        text = (
            "CONFIRMED\n"
            "genre: deep house\n"
            "duration_min: 60\n"
            "mood: noche tropical\n"
            "environment: bar íntimo — al aire libre, en la playa\n"
        )
        result = _parse_confirmed_block(text)
        assert result is not None
        assert result["environment"] == "bar íntimo — al aire libre, en la playa"

    def test_confirmed_block_environment_value_is_trimmed(self):
        """Outer whitespace is stripped; inner whitespace is preserved."""
        text = (
            "CONFIRMED\n"
            "genre: techno\n"
            "duration_min: 60\n"
            "mood: dark\n"
            "environment:    loud crowded bar    \n"
        )
        result = _parse_confirmed_block(text)
        assert result is not None
        assert result["environment"] == "loud crowded bar"


# ---------------------------------------------------------------------------
# phase_plan integration — the env line lands in the planner prompt
# ---------------------------------------------------------------------------

def test_phase_plan_injects_environment_into_prompt(tmp_db, monkeypatch):
    """End-to-end check: when ctx carries ``environment``, ``phase_plan``
    includes an "Environment: ..." line in the prompt sent to the LLM. We
    capture the prompt by stubbing ``run_agent_streaming``."""
    import asyncio

    captured: list[str] = []

    async def _capture(system, tool_fns, messages, ctx, emit, max_turns=20):
        text = "\n\n".join(
            (m.get("content") if isinstance(m.get("content"), str) else "")
            for m in messages
        )
        captured.append(text)
        return "ok"

    async def _noop_emit(_event):
        pass

    # Stub catalog so the prompt-building path doesn't crash on disk I/O.
    monkeypatch.setattr(
        pipeline,
        "load_catalog",
        lambda genre=None: ([], ["techno"]),
    )
    monkeypatch.setattr(pipeline, "run_agent_streaming", _capture)

    ctx = {
        "genre": "techno",
        "duration_min": 60,
        "mood": "dark",
        "environment": "loud crowded bar",
    }
    asyncio.run(pipeline.phase_plan(ctx, _noop_emit, memory_summary=""))

    assert captured, "run_agent_streaming was not called"
    assert "loud crowded bar" in captured[0]
    assert "Environment:" in captured[0]


def test_phase_plan_omits_environment_line_when_unspecified(tmp_db, monkeypatch):
    """``environment="unspecified"`` is the no-op signal — the planner
    prompt should NOT carry a noisy "Environment: unspecified" line that
    the planner is told to ignore anyway."""
    import asyncio

    captured: list[str] = []

    async def _capture(system, tool_fns, messages, ctx, emit, max_turns=20):
        text = "\n\n".join(
            (m.get("content") if isinstance(m.get("content"), str) else "")
            for m in messages
        )
        captured.append(text)
        return "ok"

    async def _noop_emit(_event):
        pass

    monkeypatch.setattr(
        pipeline,
        "load_catalog",
        lambda genre=None: ([], ["techno"]),
    )
    monkeypatch.setattr(pipeline, "run_agent_streaming", _capture)

    ctx = {
        "genre": "techno",
        "duration_min": 60,
        "mood": "dark",
        "environment": "unspecified",
    }
    asyncio.run(pipeline.phase_plan(ctx, _noop_emit, memory_summary=""))

    assert captured
    assert "Environment:" not in captured[0]
