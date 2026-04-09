"""Tests for response parser helpers in agent/run.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.run import _parse_critic_response, _parse_validator_response, _parse_confirmed_block


class TestParseCriticResponse:
    def test_approved_no_problems(self):
        text = "The playlist looks solid.\nVERDICT: APPROVED"
        verdict, problems, _ = _parse_critic_response(text)
        assert verdict == "APPROVED"
        assert problems == []

    def test_needs_fixes_with_problems(self):
        text = (
            "PROBLEMS:\n"
            "- [pos 2→3] key clash 5A → 11A\n"
            "- [pos 5→6] BPM jump too large\n"
            "VERDICT: NEEDS_FIXES"
        )
        verdict, problems, _ = _parse_critic_response(text)
        assert verdict == "NEEDS_FIXES"
        assert len(problems) == 2
        assert "key clash" in problems[0]
        assert "BPM jump" in problems[1]

    def test_reject_verdict(self):
        text = "PROBLEMS:\n- Entire arc is broken\nVERDICT: REJECT"
        verdict, problems, _ = _parse_critic_response(text)
        assert verdict == "REJECT"
        assert len(problems) == 1

    def test_problems_none_means_no_problems(self):
        text = "PROBLEMS: none\nVERDICT: APPROVED"
        verdict, problems, _ = _parse_critic_response(text)
        assert verdict == "APPROVED"
        assert problems == []

    def test_empty_text_defaults_to_approved(self):
        verdict, problems, _ = _parse_critic_response("")
        assert verdict == "APPROVED"
        assert problems == []

    def test_case_insensitive_verdict(self):
        text = "verdict: needs_fixes"
        verdict, _, _ = _parse_critic_response(text)
        assert verdict == "NEEDS_FIXES"

    def test_case_insensitive_problems(self):
        text = "problems:\n- issue one\nVERDICT: APPROVED"
        verdict, problems, _ = _parse_critic_response(text)
        assert verdict == "APPROVED"
        assert len(problems) == 1


class TestParseValidatorResponse:
    def test_pass_no_issues(self):
        text = "AUDIO QUALITY REPORT\nDuration: 60:00\nStatus: PASS\nNo issues detected."
        status, issues = _parse_validator_response(text)
        assert status == "PASS"
        assert issues == []

    def test_warning_with_issues(self):
        text = (
            "Status: WARNING\n"
            "Issues (2):\n"
            "- [00:30] High spectral flatness (0.45)\n"
            "- [01:00] Silence gap of 2.3s\n"
        )
        status, issues = _parse_validator_response(text)
        assert status == "WARNING"
        assert len(issues) == 2
        assert "spectral flatness" in issues[0]

    def test_fail_status(self):
        text = "Status: FAIL\nIssues:\n- Peak clipping at 00:12"
        status, issues = _parse_validator_response(text)
        assert status == "FAIL"
        assert len(issues) == 1

    def test_empty_text_defaults_to_pass(self):
        status, issues = _parse_validator_response("")
        assert status == "PASS"
        assert issues == []

    def test_issues_stop_at_recommendations(self):
        text = (
            "Status: WARNING\n"
            "Issues:\n"
            "- Clipping at 00:05\n"
            "Recommendations:\n"
            "- Lower gain\n"
        )
        status, issues = _parse_validator_response(text)
        assert len(issues) == 1


class TestParseConfirmedBlock:
    def test_valid_block(self):
        text = (
            "I've confirmed the details.\n"
            "CONFIRMED\n"
            "genre: techno\n"
            "duration_min: 60\n"
            "mood: dark industrial build\n"
        )
        result = _parse_confirmed_block(text)
        assert result is not None
        assert result["genre"] == "techno"
        assert result["duration_min"] == 60
        assert result["mood"] == "dark industrial build"

    def test_no_confirmed_returns_none(self):
        text = "genre: techno\nduration_min: 60\nmood: dark"
        assert _parse_confirmed_block(text) is None

    def test_missing_field_returns_none(self):
        text = "CONFIRMED\ngenre: techno\nduration_min: 60"  # no mood
        assert _parse_confirmed_block(text) is None

    def test_non_integer_duration_returns_none(self):
        text = "CONFIRMED\ngenre: techno\nduration_min: sixty\nmood: dark"
        assert _parse_confirmed_block(text) is None

    def test_duration_parsed_as_int(self):
        text = "CONFIRMED\ngenre: deep house\nduration_min: 45\nmood: smooth sunset"
        result = _parse_confirmed_block(text)
        assert isinstance(result["duration_min"], int)
