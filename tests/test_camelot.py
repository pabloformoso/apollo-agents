"""Tests for Camelot wheel harmonic mixing logic."""

import pytest
from agent.tools import _camelot_neighbors, _camelot_compat


class TestCamelotNeighbors:
    def test_same_key_in_neighbors(self):
        assert "8A" in _camelot_neighbors("8A")

    def test_adjacent_number_same_letter(self):
        neighbors = _camelot_neighbors("8A")
        assert "9A" in neighbors  # +1
        assert "7A" in neighbors  # -1

    def test_opposite_letter_same_number(self):
        neighbors = _camelot_neighbors("8A")
        assert "8B" in neighbors

    def test_wraps_at_12(self):
        neighbors = _camelot_neighbors("12A")
        assert "1A" in neighbors   # 12+1 wraps to 1

    def test_wraps_at_1(self):
        neighbors = _camelot_neighbors("1A")
        assert "12A" in neighbors  # 1-1 wraps to 12

    def test_b_key(self):
        neighbors = _camelot_neighbors("5B")
        assert "5A" in neighbors
        assert "6B" in neighbors
        assert "4B" in neighbors

    def test_empty_key_returns_empty(self):
        assert _camelot_neighbors("") == set()

    def test_invalid_key_returns_empty(self):
        assert _camelot_neighbors("ZZ") == set()


class TestCamelotCompat:
    def test_same_key_is_perfect(self):
        result = _camelot_compat("8A", "8A")
        assert "perfect" in result

    def test_adjacent_number_is_compatible(self):
        result = _camelot_compat("8A", "9A")
        assert "compatible" in result

    def test_opposite_letter_is_compatible(self):
        result = _camelot_compat("8A", "8B")
        assert "compatible" in result

    def test_two_steps_is_acceptable(self):
        result = _camelot_compat("8A", "10A")
        assert "acceptable" in result

    def test_unrelated_key_is_clash(self):
        result = _camelot_compat("1A", "7B")
        assert "clash" in result

    def test_missing_key_returns_unknown(self):
        result = _camelot_compat("", "8A")
        assert "unknown" in result

    def test_both_missing_returns_unknown(self):
        result = _camelot_compat("", "")
        assert "unknown" in result
