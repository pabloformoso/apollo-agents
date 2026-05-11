"""Unit tests for v2.6.0 ``web.backend.arc.compute_arc``."""
from __future__ import annotations

from web.backend.arc import compute_arc


def test_empty_playlist_returns_none():
    assert compute_arc([]) is None


def test_uses_explicit_energy_when_present():
    arc = compute_arc([
        {"id": "a", "energy": 2.0},
        {"id": "b", "energy": 8.0},
        {"id": "c", "energy": 5.0},
    ])
    assert arc is not None
    assert arc["points"] == [2.0, 8.0, 5.0]
    assert arc["max"] == 8.0
    assert arc["peak_pos"] == 1
    assert arc["flat"] is False  # peak >= 5 threshold


def test_falls_back_to_bpm_when_energy_missing():
    arc = compute_arc([
        {"id": "lofi", "bpm": 60},   # → (60-50)/12 ≈ 0.83 → clamped to 1.0
        {"id": "techno", "bpm": 130},  # → (130-50)/12 ≈ 6.67
    ])
    assert arc is not None
    assert arc["points"][0] == 1.0
    assert round(arc["points"][1], 2) == 6.67
    assert arc["peak_pos"] == 1


def test_flat_when_no_peak_reaches_threshold():
    arc = compute_arc([
        {"id": "a", "bpm": 60},
        {"id": "b", "bpm": 64},
        {"id": "c", "bpm": 62},
    ])
    assert arc is not None
    assert arc["flat"] is True  # all energies < 5


def test_clamps_to_range():
    arc = compute_arc([
        {"id": "too_low", "energy": -3},
        {"id": "too_high", "energy": 99},
    ])
    assert arc is not None
    assert arc["points"] == [1.0, 10.0]
