"""Tests for the v3.7.3 catalog-aware Genre Guard.

Live failure 2026-07-12: a freshly added 'aural' collection (65 tracks)
showed up in list_genres, but asking for it produced a lofi - ambient
playlist. The guard prompt only named example shorthands, so the small
local model normalized the unfamiliar request onto the example it could
see. Two-layer fix under test here:

1. ``genre_guard_system`` injects the REAL catalog genres + a hard
   no-substitution rule into the prompt.
2. ``enforce_mentioned_genre`` — deterministic backstop: the user's
   literal genre mention beats the model's normalization.
"""
from __future__ import annotations

from agent.run import _GENRE_GUARD_SYSTEM, enforce_mentioned_genre, genre_guard_system

GENRES = [
    "aural",
    "cocktail house",
    "deep house",
    "lofi - ambient",
    "soul jazz",
    "synthware",
]


# ---------------------------------------------------------------------------
# genre_guard_system
# ---------------------------------------------------------------------------

def test_prompt_includes_every_available_genre():
    prompt = genre_guard_system(GENRES)
    for g in GENRES:
        assert g in prompt


def test_prompt_carries_the_no_substitution_rule():
    prompt = genre_guard_system(GENRES)
    assert "NEVER substitute" in prompt
    assert "copied verbatim" in prompt


def test_prompt_falls_back_to_static_without_catalog():
    assert genre_guard_system([]) == _GENRE_GUARD_SYSTEM


def test_prompt_reads_catalog_when_genres_not_injected(monkeypatch):
    import agent.tools as tools_mod

    monkeypatch.setattr(tools_mod, "_load_catalog_genres", lambda: ["aural"])
    prompt = genre_guard_system()
    assert "aural" in prompt


# ---------------------------------------------------------------------------
# enforce_mentioned_genre
# ---------------------------------------------------------------------------

def _parsed(genre: str) -> dict:
    return {"genre": genre, "duration_min": 60, "mood": "calm", "environment": "unspecified"}


def test_override_when_user_named_a_genre_the_model_ignored():
    """THE live case: user asks for aural, guard confirms lofi - ambient."""
    got = enforce_mentioned_genre(
        "quiero una sesion de aural de 60 minutos, frecuencias del espacio",
        _parsed("lofi - ambient"),
        GENRES,
    )
    assert got is not None and got["genre"] == "aural"
    # The rest of the block survives untouched.
    assert got["duration_min"] == 60


def test_no_override_when_confirmed_genre_was_mentioned():
    got = enforce_mentioned_genre(
        "algo tipo lofi - ambient pero espacial",
        _parsed("lofi - ambient"),
        GENRES,
    )
    assert got is not None and got["genre"] == "lofi - ambient"


def test_no_override_when_user_mentioned_nothing_available():
    got = enforce_mentioned_genre(
        "musica del espacio con frecuencias sanadoras",
        _parsed("lofi - ambient"),
        GENRES,
    )
    assert got is not None and got["genre"] == "lofi - ambient"


def test_no_override_when_two_genres_mentioned():
    """Ambiguous — the model's disambiguation stands."""
    got = enforce_mentioned_genre(
        "dudo entre aural y synthware, sorprendeme",
        _parsed("synthware"),
        GENRES,
    )
    assert got is not None and got["genre"] == "synthware"


def test_mention_matching_is_case_insensitive():
    got = enforce_mentioned_genre(
        "Ponme AURAL para concentrarme",
        _parsed("lofi - ambient"),
        GENRES,
    )
    assert got is not None and got["genre"] == "aural"


def test_none_parse_and_empty_inputs_pass_through():
    assert enforce_mentioned_genre("aural", None, GENRES) is None
    assert enforce_mentioned_genre("", _parsed("aural"), GENRES)["genre"] == "aural"
    got = enforce_mentioned_genre("aural", _parsed("lofi - ambient"), [])
    assert got["genre"] == "lofi - ambient"  # no genre list → no backstop


def test_override_preserves_dict_identity_semantics():
    """The original parsed dict must not be mutated (callers may hold it)."""
    original = _parsed("lofi - ambient")
    got = enforce_mentioned_genre("sesion aural", original, GENRES)
    assert original["genre"] == "lofi - ambient"
    assert got["genre"] == "aural"


# ---------------------------------------------------------------------------
# v3.7.4 — propose_playlist: the confirmed ctx genre beats the LLM argument
# ---------------------------------------------------------------------------

def _mini_catalog(tmp_path, monkeypatch):
    import json

    import agent.tools as tools_mod

    catalog = {
        "tracks": [
            {"id": f"aural-{i}", "display_name": f"Aural {i}", "file": f"tracks/aural/a{i}.wav",
             "genre_folder": "aural", "genre": "aural", "bpm": 57.0 + i,
             "camelot_key": "8A", "duration_sec": 180.0, "variant_of": None}
            for i in range(6)
        ] + [
            {"id": f"lofi-{i}", "display_name": f"Lofi {i}", "file": f"tracks/lofi/l{i}.wav",
             "genre_folder": "lofi - ambient", "genre": "lofi - ambient", "bpm": 75.0 + i,
             "camelot_key": "9A", "duration_sec": 180.0, "variant_of": None}
            for i in range(6)
        ]
    }
    p = tmp_path / "tracks.json"
    p.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(tools_mod, "_CATALOG_PATH", p)
    return tools_mod


def test_propose_playlist_ctx_genre_beats_llm_argument(tmp_path, monkeypatch):
    """THE live bug: guard confirmed 'aural', the planner LLM called
    propose_playlist(genre='lofi - ambient') anyway. The confirmed ctx
    genre must win — playlist AND ctx stay aural."""
    tools_mod = _mini_catalog(tmp_path, monkeypatch)
    ctx = {"genre": "aural"}
    out = tools_mod.propose_playlist("lofi - ambient", 30, "chill", ctx)
    assert "Error" not in out
    assert ctx["genre"] == "aural"
    assert all(t["genre_folder"] == "aural" for t in ctx["playlist"])


def test_propose_playlist_ctx_genre_match_is_case_insensitive(tmp_path, monkeypatch):
    """'Aural' vs 'aural' is agreement, not an override — no log spam,
    same result."""
    tools_mod = _mini_catalog(tmp_path, monkeypatch)
    ctx = {"genre": "Aural"}
    out = tools_mod.propose_playlist("aural", 30, "chill", ctx)
    assert "Error" not in out
    assert all(t["genre_folder"] == "aural" for t in ctx["playlist"])


def test_propose_playlist_without_ctx_genre_uses_argument(tmp_path, monkeypatch):
    """No confirmed genre in ctx (direct tool use / tests) → the
    argument keeps working exactly as before."""
    tools_mod = _mini_catalog(tmp_path, monkeypatch)
    ctx = {}
    out = tools_mod.propose_playlist("lofi - ambient", 30, "chill", ctx)
    assert "Error" not in out
    assert ctx["genre"] == "lofi - ambient"
    assert all(t["genre_folder"] == "lofi - ambient" for t in ctx["playlist"])
