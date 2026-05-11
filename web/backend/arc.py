"""Energy-arc metrics for a session playlist.

Exposed on ``GET /api/sessions/:id`` so the redesign screens (Curate,
Editor, Render) render the arc strip without per-screen re-derivation.
"""
from __future__ import annotations

from typing import Iterable

# Same coarse linear scale the original v2.5 frontend uses
# (curate/page.tsx `energyFor`): lo-fi ~60 BPM ≈ 3, techno ~130 BPM ≈ 8.
# Replace with a per-track field once the catalog stores energy directly.
_BPM_FALLBACK_BASE = 50
_BPM_FALLBACK_SLOPE = 12.0
_ENERGY_MIN = 1.0
_ENERGY_MAX = 10.0
_FLAT_PEAK_THRESHOLD = 5.0


def _energy_for_track(track: dict) -> float:
    energy = track.get("energy")
    if isinstance(energy, (int, float)):
        return max(_ENERGY_MIN, min(_ENERGY_MAX, float(energy)))
    bpm = track.get("bpm")
    if not isinstance(bpm, (int, float)):
        bpm = _BPM_FALLBACK_BASE + _BPM_FALLBACK_SLOPE * 1.0  # neutral 6.0
    return max(
        _ENERGY_MIN,
        min(_ENERGY_MAX, (float(bpm) - _BPM_FALLBACK_BASE) / _BPM_FALLBACK_SLOPE),
    )


def compute_arc(playlist: Iterable[dict]) -> dict | None:
    """Return ``{ flat, max, peak_pos, points }`` for the given playlist.

    Returns ``None`` for an empty playlist so callers can short-circuit on
    sessions that have no plan yet.
    """
    points = [_energy_for_track(t) for t in playlist]
    if not points:
        return None
    peak = max(points)
    peak_pos = points.index(peak)
    return {
        "flat": peak < _FLAT_PEAK_THRESHOLD,
        "max": peak,
        "peak_pos": peak_pos,
        "points": points,
    }
