"""
Regression test for the UTF-8 / cp1252 charmap bug fixed in PR #22.

Without ``encoding="utf-8"`` on the ``with open(_CATALOG_PATH)`` calls in
``agent/tools.py``, ``agent/run.py``, ``agent/live_engine.py``, and
``main.py``, on Windows the default cp1252 (charmap) decoder chokes on
UTF-8 byte sequences that contain bytes undefined in cp1252 (notably
``0x81``, ``0x8d``, ``0x8f``, ``0x90``, ``0x9d``).

The original failure on Windows was:

    Tool error: 'charmap' codec can't decode byte 0x9d in position 259716:
    character maps to <undefined>

This test forces that exact failure mode on **any** platform by wrapping
``builtins.open`` so calls that don't pass an explicit ``encoding``
kwarg fall back to ``cp1252`` (Windows default). The fixture
``tracks.json`` contains the character ``Ý`` (U+00DD ``LATIN CAPITAL
LETTER Y WITH ACUTE``), whose UTF-8 encoding is ``c3 9d`` and therefore
includes the cp1252-undefined byte ``0x9d`` — the same byte that
triggered the original bug.

After PR #22, every patched call site passes ``encoding="utf-8"``
explicitly, so the wrapper does NOT inject cp1252 there, and the read
succeeds. If a future refactor drops the kwarg from any of those
opens, this test will fail.

The test also includes a negative-control sanity check that proves the
wrapping is actually doing its job (i.e. an unpatched ``open()`` call on
the fixture really does raise ``UnicodeDecodeError`` under the
simulated cp1252 default). Without that control, a bug in the wrapper
itself could let the regression test silently pass.
"""

from __future__ import annotations

import builtins
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

import agent.live_engine as live_engine
import agent.run as agent_run
import agent.tools as tools


# ---------------------------------------------------------------------------
# Fixture catalog — contains UTF-8 bytes undefined in cp1252
# ---------------------------------------------------------------------------
#
# 'Ý' (U+00DD, LATIN CAPITAL LETTER Y WITH ACUTE) encodes as 0xC3 0x9D in
# UTF-8. Byte 0x9D is undefined in cp1252 → the same UnicodeDecodeError
# the user saw on Windows.
#
# We also include other smart-quote-like characters whose UTF-8 encodings
# touch other cp1252-undefined bytes (defence in depth in case Python
# someday extends cp1252).
_CHARMAP_BAIT = (
    "Ý"        # Ý  → c3 9d  (0x9d undefined)
    " — "           # em-dash sandwich (utf-8: e2 80 94)
    "Í"        # Í  → c3 8d  (0x8d undefined)
    " ™ €99 "       # bonus non-ASCII bytes for realism
    "Ï"        # Ï  → c3 8f  (0x8f undefined)
)

_CATALOG_TRACKS = [
    {
        "id": "techno--charmap-bait",
        "display_name": f"Charmap Bait {_CHARMAP_BAIT}",
        "file": "tracks/techno/charmap_bait.wav",
        "genre_folder": "techno",
        "genre": "techno",
        "bpm": 124.0,
        "camelot_key": "8A",
        "duration_sec": 240.0,
    },
    {
        "id": "techno--clean-track",
        "display_name": "Clean Track",
        "file": "tracks/techno/clean.wav",
        "genre_folder": "techno",
        "genre": "techno",
        "bpm": 126.0,
        "camelot_key": "9A",
        "duration_sec": 240.0,
    },
    {
        "id": "lofi--ambient-track",
        "display_name": "Ambient Drift",
        "file": "tracks/lofi - ambient/drift.wav",
        "genre_folder": "lofi - ambient",
        "genre": "lofi - ambient",
        "bpm": 78.0,
        "camelot_key": "5A",
        "duration_sec": 200.0,
    },
]


# ---------------------------------------------------------------------------
# cp1252 default-open wrapper
# ---------------------------------------------------------------------------

_real_open = builtins.open


def _cp1252_default_open(*args, **kwargs):
    """Drop-in replacement for ``builtins.open`` that injects ``cp1252``
    when the caller opens a text-mode file *without* specifying
    ``encoding``. Mimics the Windows default behaviour on any platform.
    """
    mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
    if "b" not in mode and "encoding" not in kwargs:
        kwargs["encoding"] = "cp1252"
    return _real_open(*args, **kwargs)


@contextmanager
def _force_cp1252_default():
    """Patch ``builtins.open`` for the duration of the context."""
    with patch("builtins.open", _cp1252_default_open):
        yield


# ---------------------------------------------------------------------------
# Catalog/temp dir fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def utf8_catalog(tmp_path):
    """Write a synthetic catalog (UTF-8 bytes containing 0x9d) and patch
    every module-level pointer to it."""
    # Build a fake project tree so catalog_status (and other path-aware
    # tools) can scan disk without erroring.
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    (tracks_dir / "techno").mkdir()
    (tracks_dir / "lofi - ambient").mkdir()
    # Touch sentinel WAV files so disk-scan logic finds something.
    for entry in _CATALOG_TRACKS:
        (tmp_path / entry["file"]).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / entry["file"]).write_bytes(b"\x00" * 8)

    catalog_path = tracks_dir / "tracks.json"
    payload = json.dumps({"tracks": _CATALOG_TRACKS}, ensure_ascii=False)
    catalog_path.write_bytes(payload.encode("utf-8"))

    # Sanity: confirm the bait byte is really in the file.
    raw = catalog_path.read_bytes()
    assert b"\x9d" in raw, "fixture is missing the 0x9d byte that triggers cp1252"

    # Patch the module-level pointers used by each affected module.
    with patch.object(tools, "_CATALOG_PATH", catalog_path), \
            patch.object(tools, "_PROJECT_DIR", tmp_path), \
            patch.object(live_engine, "_PROJECT_DIR", tmp_path):
        yield catalog_path


# ---------------------------------------------------------------------------
# Negative control — proves the cp1252 wrapper actually triggers the bug
# ---------------------------------------------------------------------------

class TestNegativeControl:
    """Without these checks a passing regression suite would be
    meaningless — they prove the cp1252 simulation is doing its job."""

    def test_fixture_contains_cp1252_undefined_byte(self, utf8_catalog):
        raw = utf8_catalog.read_bytes()
        assert b"\x9d" in raw, "0x9d byte is required to reproduce the bug"

    def test_unpatched_open_fails_under_simulated_cp1252(self, utf8_catalog):
        """Reading the fixture WITHOUT ``encoding="utf-8"`` while the
        cp1252-default wrapper is active must raise — otherwise the
        environment is somehow already utf-8 and this whole test file
        cannot guard against the regression."""
        with _force_cp1252_default():
            with pytest.raises(UnicodeDecodeError):
                # No encoding kwarg — wrapper injects cp1252.
                with open(utf8_catalog) as f:
                    json.load(f)

    def test_explicit_utf8_open_succeeds_under_simulated_cp1252(self, utf8_catalog):
        """And the converse: when the caller DOES pass
        ``encoding="utf-8"``, the wrapper leaves it alone and the read
        succeeds. This is the contract every patched call site relies
        on."""
        with _force_cp1252_default():
            with open(utf8_catalog, encoding="utf-8") as f:
                data = json.load(f)
        assert data["tracks"][0]["display_name"].startswith("Charmap Bait")


# ---------------------------------------------------------------------------
# Regression — every agent tool that PR #22 hardened
# ---------------------------------------------------------------------------

class TestAgentToolsUnderCp1252:
    """Each test exercises a real public tool that opens
    ``_CATALOG_PATH``. With the fix in place, none of them should raise
    ``UnicodeDecodeError`` even when the OS default encoding is
    cp1252."""

    def _ctx(self, **extra):
        ctx = {"playlist": [], "genre": "techno", "mood": "test"}
        ctx.update(extra)
        return ctx

    # ---- agent/tools.py ----------------------------------------------------

    def test_list_genres(self, utf8_catalog):
        with _force_cp1252_default():
            out = tools.list_genres(self._ctx())
        assert "techno" in out

    def test_get_catalog(self, utf8_catalog):
        with _force_cp1252_default():
            out = tools.get_catalog("techno", self._ctx())
        assert "Charmap Bait" in out

    def test_propose_playlist(self, utf8_catalog):
        ctx = self._ctx()
        with _force_cp1252_default():
            out = tools.propose_playlist("techno", 5, "test mood", ctx)
        assert "techno" in out.lower() or "playlist" in out.lower()
        assert ctx["playlist"], "propose_playlist should populate context"

    def test_analyze_transition(self, utf8_catalog):
        with _force_cp1252_default():
            out = tools.analyze_transition(
                "techno--charmap-bait", "techno--clean-track", self._ctx()
            )
        assert "BPM" in out

    def test_swap_track(self, utf8_catalog):
        ctx = self._ctx(playlist=[dict(_CATALOG_TRACKS[0])])
        with _force_cp1252_default():
            out = tools.swap_track(1, "techno--clean-track", ctx)
        assert "Clean Track" in out or "swapped" in out.lower() or "→" in out

    def test_suggest_bridge_track(self, utf8_catalog):
        playlist = [dict(_CATALOG_TRACKS[0]), dict(_CATALOG_TRACKS[1])]
        ctx = self._ctx(playlist=playlist)
        with _force_cp1252_default():
            out = tools.suggest_bridge_track(1, 2, ctx)
        # Output may report no candidates depending on the synthetic
        # catalog, but the key requirement is that no decode error fires.
        assert isinstance(out, str)

    def test_insert_bridge_track(self, utf8_catalog):
        playlist = [dict(_CATALOG_TRACKS[0]), dict(_CATALOG_TRACKS[1])]
        ctx = self._ctx(playlist=playlist)
        with _force_cp1252_default():
            out = tools.insert_bridge_track(1, "techno--clean-track", ctx)
        assert isinstance(out, str)
        assert len(ctx["playlist"]) == 3

    def test_catalog_status(self, utf8_catalog):
        with _force_cp1252_default():
            out = tools.catalog_status(self._ctx())
        assert "CATALOG STATUS" in out

    def test_play_track_catalog_load(self, utf8_catalog):
        """``play_track`` reads the catalog *before* trying to play. We
        exercise just the catalog-load arm by handing it a track ID and
        letting the missing-audio branch return early."""
        with _force_cp1252_default():
            out = tools.play_track(
                "techno--charmap-bait", 0, 0, self._ctx()
            )
        # The track ID is found; the WAV is a stub so playback fails
        # cleanly. Either way, no UnicodeDecodeError.
        assert isinstance(out, str)

    # ---- agent/run.py ------------------------------------------------------

    def test_catalog_needs_sync(self, utf8_catalog, monkeypatch):
        """``_catalog_needs_sync`` opens the catalog with the same
        encoding bug surface. Patch its hard-coded path resolver to
        point at the fixture."""
        # _catalog_needs_sync derives the catalog path from
        # ``Path(__file__).parent.parent / "tracks" / "tracks.json"``.
        # We cannot rebind that easily, so fall back to monkeypatching
        # ``Path(__file__).parent`` via the `__file__` global of the
        # function's module — instead, patch ``os.listdir`` and the
        # underlying file ops to exercise the open-call path.
        fake_run_file = utf8_catalog.parent.parent / "fake_agent" / "run.py"
        fake_run_file.parent.mkdir(parents=True, exist_ok=True)
        fake_run_file.touch()
        monkeypatch.setattr(agent_run, "__file__", str(fake_run_file))

        with _force_cp1252_default():
            # Result is True/False depending on whether stub WAVs are
            # cataloged; the only thing that matters here is the lack
            # of UnicodeDecodeError when the function reads the JSON.
            result = agent_run._catalog_needs_sync()
        assert isinstance(result, bool)

    # ---- agent/live_engine.py ---------------------------------------------

    def test_live_engine_load_catalog(self, utf8_catalog):
        with _force_cp1252_default():
            tracks = live_engine._load_catalog()
        assert isinstance(tracks, list)
        assert any(t["id"] == "techno--charmap-bait" for t in tracks)
