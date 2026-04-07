"""Tests for session memory read/write logic."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


def _make_session(genre="techno", rating=4, mood="dark build", swapped=None, problems=None):
    return {
        "session_name": "test-session",
        "timestamp": "2026-04-07T20:00:00",
        "genre": genre,
        "duration_min": 60,
        "mood": mood,
        "rating": rating,
        "notes": "",
        "critic_verdict": "APPROVED",
        "critic_problems": problems or [],
        "validator_status": "PASS",
        "validator_issues": [],
        "tracks_swapped": swapped or [],
        "final_playlist": ["Track A", "Track B"],
    }


class TestReadMemory:
    def _call(self, sessions, genre="techno"):
        """Call read_memory with a temporary memory file."""
        import agent.tools as tools

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"schema_version": 1, "sessions": sessions}, f)
            tmp = Path(f.name)

        try:
            with patch.object(tools, "_MEMORY_PATH", tmp):
                return tools.read_memory(genre, {})
        finally:
            tmp.unlink(missing_ok=True)

    def test_no_file_returns_no_memory(self):
        import agent.tools as tools
        with patch.object(tools, "_MEMORY_PATH", Path("/nonexistent/memory.json")):
            result = tools.read_memory("techno", {})
        assert "No memory" in result

    def test_empty_genre_match_returns_no_memory(self):
        result = self._call([_make_session(genre="deep house")], genre="techno")
        assert "No memory" in result

    def test_genre_filter_case_insensitive(self):
        result = self._call([_make_session(genre="Techno")], genre="techno")
        assert "MEMORY SUMMARY" in result

    def test_avoid_list_tracks_swapped_twice(self):
        sessions = [
            _make_session(swapped=["Rave Doctrine"]),
            _make_session(swapped=["Rave Doctrine"]),
        ]
        result = self._call(sessions)
        assert "Rave Doctrine" in result
        assert "swapped" in result.lower()

    def test_single_swap_not_in_avoid_list(self):
        sessions = [_make_session(swapped=["Solo Track"])]
        result = self._call(sessions)
        # Should not appear in avoid list (only swapped once)
        assert "Solo Track" not in result

    def test_high_rated_session_surfaced(self):
        sessions = [_make_session(rating=5, mood="peak energy")]
        result = self._call(sessions)
        assert "peak energy" in result

    def test_low_rated_session_not_in_high_rated(self):
        sessions = [_make_session(rating=2, mood="boring set")]
        result = self._call(sessions)
        assert "boring set" not in result

    def test_recurring_critic_problems_shown(self):
        problem = "key clash 5A → 11A at position 3"
        sessions = [
            _make_session(problems=[problem]),
            _make_session(problems=[problem]),
        ]
        result = self._call(sessions)
        assert "key clash" in result

    def test_capped_at_last_10_sessions(self):
        # 15 sessions; only last 10 should count for avoid list
        early = _make_session(swapped=["Old Track"])  # session 1-5 (old, outside window)
        recent = _make_session(swapped=["New Track"])
        sessions = [early] * 5 + [recent] * 10
        result = self._call(sessions)
        # New Track swapped 10× → definitely in avoid
        assert "New Track" in result


class TestWriteSessionRecord:
    def test_creates_memory_file(self):
        import agent.tools as tools

        with tempfile.TemporaryDirectory() as tmp_dir:
            mem_path = Path(tmp_dir) / "memory.json"
            with patch.object(tools, "_MEMORY_PATH", mem_path):
                tools.write_session_record(
                    "test-session", "techno", 60, "dark", 4, "great set",
                    "APPROVED", "[]", "PASS", "[]", "[]", '["Track A"]',
                    {},
                )
            assert mem_path.exists()
            data = json.loads(mem_path.read_text())
            assert len(data["sessions"]) == 1
            assert data["sessions"][0]["session_name"] == "test-session"

    def test_appends_to_existing_records(self):
        import agent.tools as tools

        existing = {"schema_version": 1, "sessions": [_make_session()]}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(existing, f)
            tmp = Path(f.name)

        try:
            with patch.object(tools, "_MEMORY_PATH", tmp):
                tools.write_session_record(
                    "new-session", "techno", 30, "mellow", 3, "",
                    "NEEDS_FIXES", '["key clash"]', "PASS", "[]", "[]", "[]",
                    {},
                )
            data = json.loads(tmp.read_text())
            assert len(data["sessions"]) == 2
            assert data["sessions"][-1]["session_name"] == "new-session"
        finally:
            tmp.unlink(missing_ok=True)

    def test_caps_at_50_sessions(self):
        import agent.tools as tools

        sessions = [_make_session() for _ in range(50)]
        existing = {"schema_version": 1, "sessions": sessions}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(existing, f)
            tmp = Path(f.name)

        try:
            with patch.object(tools, "_MEMORY_PATH", tmp):
                tools.write_session_record(
                    "overflow-session", "techno", 60, "peak", 5, "",
                    "APPROVED", "[]", "PASS", "[]", "[]", "[]",
                    {},
                )
            data = json.loads(tmp.read_text())
            assert len(data["sessions"]) == 50
            assert data["sessions"][-1]["session_name"] == "overflow-session"
        finally:
            tmp.unlink(missing_ok=True)

    def test_parses_json_list_args(self):
        import agent.tools as tools

        with tempfile.TemporaryDirectory() as tmp_dir:
            mem_path = Path(tmp_dir) / "memory.json"
            with patch.object(tools, "_MEMORY_PATH", mem_path):
                tools.write_session_record(
                    "s", "techno", 60, "dark", 4, "",
                    "NEEDS_FIXES", '["clash at pos 2"]',
                    "WARNING", '["spectral flatness"]',
                    '["Weak Track"]', '["Strong A", "Strong B"]',
                    {},
                )
            data = json.loads(mem_path.read_text())
            rec = data["sessions"][0]
            assert rec["critic_problems"] == ["clash at pos 2"]
            assert rec["validator_issues"] == ["spectral flatness"]
            assert rec["tracks_swapped"] == ["Weak Track"]
            assert rec["final_playlist"] == ["Strong A", "Strong B"]
