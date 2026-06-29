"""Coverage for pure / lightly-mocked helpers in main.py.

Targets the testable logic (parsing, list/dedup, metadata) — NOT the
ffmpeg/moviepy/PIL render path. Heavy I/O functions are mocked at their
single boundary (`_wav_duration_sec`).
"""
from __future__ import annotations

import json
from unittest.mock import patch

import main as m


class TestFillDuration:
    def _tracks(self, n):
        return [
            {"display_name": f"T{i}", "file": f"tracks/g/t{i}.wav"} for i in range(n)
        ]

    def test_accumulates_until_target(self):
        tracks = self._tracks(5)
        with patch("main._wav_duration_sec", return_value=60.0):  # 1 min each
            out = m.fill_duration(tracks, duration_minutes=3)
        # Needs >= 180 s → 3 tracks of 60 s.
        assert len(out) == 3

    def test_dedupes_display_name_first_pass(self):
        tracks = [
            {"display_name": "Dup", "file": "a.wav"},
            {"display_name": "Dup", "file": "b.wav"},
            {"display_name": "Other", "file": "c.wav"},
        ]
        with patch("main._wav_duration_sec", return_value=600.0):  # 10 min each
            out = m.fill_duration(tracks, duration_minutes=5)
        # One 10-min track already exceeds 5 min → single entry, deduped.
        assert len(out) == 1
        assert out[0]["display_name"] == "Dup"

    def test_cycles_when_pool_exhausted(self):
        tracks = self._tracks(2)  # only 2 unique
        with patch("main._wav_duration_sec", return_value=60.0):
            out = m.fill_duration(tracks, duration_minutes=5)  # needs 5 → cycles
        assert len(out) >= 5  # cycled past the 2-track pool


class TestParseSunoSidecar:
    def test_returns_none_when_no_sidecar(self, tmp_path):
        audio = tmp_path / "x.wav"
        audio.write_bytes(b"")
        assert m.parse_suno_sidecar(str(audio)) is None

    def test_parses_fields(self, tmp_path):
        audio = tmp_path / "song.wav"
        audio.write_bytes(b"")
        sidecar = tmp_path / "song.wav.txt"
        sidecar.write_text(
            "Title: Midnight Drive\n"
            "Artist: Apollo\n"
            "Year: 2026\n"
            "Cover Art URL: https://x/y.png\n"
            "Prompt: deep house at dusk\n",
            encoding="utf-8",
        )
        info = m.parse_suno_sidecar(str(audio))
        assert info["title"] == "Midnight Drive"
        assert info["artist"] == "Apollo"
        assert info["year"] == "2026"
        assert info["cover_url"] == "https://x/y.png"
        assert info["prompt"] == "deep house at dusk"

    def test_parses_raw_api_id_and_tags(self, tmp_path):
        audio = tmp_path / "s.wav"
        audio.write_bytes(b"")
        raw = {"id": "abc-123", "metadata": {"tags": "deep house, night"}}
        (tmp_path / "s.wav.txt").write_text(
            "Title: T\n\n--- Raw API Response ---\n" + json.dumps(raw),
            encoding="utf-8",
        )
        info = m.parse_suno_sidecar(str(audio))
        assert info["suno_id"] == "abc-123"
        assert info["tags"] == "deep house, night"

    def test_empty_sidecar_returns_none(self, tmp_path):
        audio = tmp_path / "e.wav"
        audio.write_bytes(b"")
        (tmp_path / "e.wav.txt").write_text("nothing useful here", encoding="utf-8")
        assert m.parse_suno_sidecar(str(audio)) is None


class TestLooksLikeLegacyFilename:
    def test_none_or_empty_is_legacy(self):
        assert m._looks_like_legacy_filename(None) is True
        assert m._looks_like_legacy_filename("") is True

    def test_uuid_embedded_is_legacy(self):
        assert m._looks_like_legacy_filename(
            "track-12345678-1234-1234-1234-123456789abc"
        ) is True

    def test_clean_title_is_not_legacy(self):
        assert m._looks_like_legacy_filename("Midnight Drive") is False


class TestAttachSunoMetadata:
    def test_attaches_sidecar_and_sets_title(self, tmp_path):
        audio = tmp_path / "u.wav"
        audio.write_bytes(b"")
        (tmp_path / "u.wav.txt").write_text("Title: Real Title\n", encoding="utf-8")
        entry = {"display_name": "track-12345678-1234-1234-1234-123456789abc"}
        mutated = m._attach_suno_metadata(entry, str(audio))
        assert mutated is True
        assert entry["display_name"] == "Real Title"
        assert entry["suno"]["title"] == "Real Title"

    def test_no_sidecar_no_mutation(self, tmp_path):
        audio = tmp_path / "n.wav"
        audio.write_bytes(b"")
        entry = {"display_name": "Already Clean"}
        assert m._attach_suno_metadata(entry, str(audio)) is False


class TestCollisionGroups:
    def test_groups_shared_genre_and_name(self):
        entries = [
            {"genre_folder": "deep house", "display_name": "X"},
            {"genre_folder": "deep house", "display_name": "X"},
            {"genre_folder": "deep house", "display_name": "Y"},
        ]
        groups = m._collision_groups(entries)
        assert len(groups) == 1
        gf, name, members = groups[0]
        assert (gf, name) == ("deep house", "X")
        assert len(members) == 2

    def test_skips_empty_name(self):
        entries = [{"genre_folder": "g", "display_name": ""} for _ in range(3)]
        assert m._collision_groups(entries) == []

    def test_no_collisions(self):
        entries = [
            {"genre_folder": "g", "display_name": "A"},
            {"genre_folder": "g", "display_name": "B"},
        ]
        assert m._collision_groups(entries) == []
