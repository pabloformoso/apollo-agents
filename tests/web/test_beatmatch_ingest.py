"""W1 — beatmatch measurement ingest (the measurements.jsonl sink).

Unit tests for ``record_beatmatch_measurement`` in web/backend/app.py: the
helper the live WS read-loop calls on a ``beatmatch_measurement`` frame. Pure
function (path injected), so no WS / TestClient needed.

Acceptance (build-beatmatch-loop-knowledge, W1):
  - malformed messages dropped (returned False), never raised;
  - well-formed appends exactly one JSON line;
  - missing file/dir created on first write;
  - multiple appends accumulate (one line each), no interleave.
"""
from __future__ import annotations

import json

from web.backend.app import record_beatmatch_measurement


def _read_lines(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


class TestRecordBeatmatchMeasurement:
    def test_wellformed_appends_one_line(self, tmp_path):
        target = tmp_path / "nested" / "measurements.jsonl"
        ok = record_beatmatch_measurement(
            {"profile": "8A->8B|bpm120-122", "offset_ms": 18.4, "pitch_bend_ms": 12.0},
            path=target,
        )
        assert ok is True
        lines = _read_lines(target)
        assert len(lines) == 1
        assert lines[0]["profile"] == "8A->8B|bpm120-122"
        assert lines[0]["offset_ms"] == 18.4
        assert lines[0]["pitch_bend_ms"] == 12.0

    def test_missing_dir_and_file_are_created(self, tmp_path):
        target = tmp_path / "a" / "b" / "c" / "measurements.jsonl"
        assert not target.exists()
        assert record_beatmatch_measurement(
            {"profile": "p", "offset_ms": 1.0}, path=target
        )
        assert target.exists()

    def test_optional_fields_passthrough_when_present(self, tmp_path):
        target = tmp_path / "m.jsonl"
        record_beatmatch_measurement(
            {
                "profile": "p",
                "offset_ms": 2.0,
                "key_pair": "8A->8B",
                "bpm_bucket": "120-122",
                "ts": "2026-06-29T10:00:00Z",
            },
            path=target,
        )
        rec = _read_lines(target)[0]
        assert rec["key_pair"] == "8A->8B"
        assert rec["bpm_bucket"] == "120-122"
        assert rec["ts"] == "2026-06-29T10:00:00Z"

    def test_optional_fields_absent_when_not_given(self, tmp_path):
        target = tmp_path / "m.jsonl"
        record_beatmatch_measurement({"profile": "p", "offset_ms": 2.0}, path=target)
        rec = _read_lines(target)[0]
        assert "pitch_bend_ms" not in rec
        assert "key_pair" not in rec

    def test_multiple_appends_accumulate(self, tmp_path):
        target = tmp_path / "m.jsonl"
        for i in range(5):
            assert record_beatmatch_measurement(
                {"profile": f"p{i}", "offset_ms": float(i)}, path=target
            )
        lines = _read_lines(target)
        assert len(lines) == 5
        assert [l["profile"] for l in lines] == [f"p{i}" for i in range(5)]

    # --- malformed → dropped (False), never raised --------------------------
    def test_missing_profile_dropped(self, tmp_path):
        target = tmp_path / "m.jsonl"
        assert record_beatmatch_measurement({"offset_ms": 1.0}, path=target) is False
        assert not target.exists()

    def test_empty_profile_dropped(self, tmp_path):
        target = tmp_path / "m.jsonl"
        assert record_beatmatch_measurement(
            {"profile": "", "offset_ms": 1.0}, path=target
        ) is False

    def test_missing_offset_dropped(self, tmp_path):
        target = tmp_path / "m.jsonl"
        assert record_beatmatch_measurement({"profile": "p"}, path=target) is False

    def test_nonnumeric_offset_dropped(self, tmp_path):
        target = tmp_path / "m.jsonl"
        assert record_beatmatch_measurement(
            {"profile": "p", "offset_ms": "nope"}, path=target
        ) is False

    def test_nonnumeric_pitch_bend_dropped(self, tmp_path):
        target = tmp_path / "m.jsonl"
        assert record_beatmatch_measurement(
            {"profile": "p", "offset_ms": 1.0, "pitch_bend_ms": "x"}, path=target
        ) is False

    def test_none_offset_dropped(self, tmp_path):
        target = tmp_path / "m.jsonl"
        assert record_beatmatch_measurement(
            {"profile": "p", "offset_ms": None}, path=target
        ) is False

    def test_integer_offset_coerced_to_float(self, tmp_path):
        target = tmp_path / "m.jsonl"
        assert record_beatmatch_measurement({"profile": "p", "offset_ms": 5}, path=target)
        assert _read_lines(target)[0]["offset_ms"] == 5.0
