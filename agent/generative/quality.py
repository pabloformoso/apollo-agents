"""Quality bench metrics (v3.2 S-1 / issue #71). Measure before scaling.

Two metric families:
- AUDIO metrics, computed from the rendered WAV: loudness (LUFS/LRA via
  pyloudnorm), crest factor, spectral centroid/tilt.
- SYMBOLIC metrics, computed from interpreter.render() event lists, never
  from audio: per-role note density and the FS8 novelty score. Symbolic
  metrics are seed-independent and byte-stable.

Fairness (two tiers): catalog references are full-mix MASTERED tracks; the
numpy render is sparse and unmastered, so absolute levels are not comparable.
- reference_informed (hard pass/fail): spectral centroid/tilt measured after
  loudness-normalizing both sides to NORM_TARGET_LUFS, note density, novelty.
- advisory (report-only): absolute LUFS, LRA, crest.

`energy_proxy(spec, seed)` is the ONE canonical energy proxy for the whole
project (windowed RMS of the offline render). CC-based proxies are out:
controls do not render (see render_audio.py).
"""

from __future__ import annotations

import json
import math

import numpy as np
import pyloudnorm as pyln

from .interpreter import BASS_CHANNEL, DRUM_CHANNEL, PAD_CHANNEL, MidiEvent, render
from .render_audio import SR, render_audio
from .spec import PatternSpec

NORM_TARGET_LUFS = -20.0
RMS_WINDOW_S = 0.5

_CHANNEL_ROLES = {DRUM_CHANNEL: "drums", BASS_CHANNEL: "bass", PAD_CHANNEL: "pad"}


# ---------------------------------------------------------------------------
# Audio metrics
# ---------------------------------------------------------------------------

def lufs_metrics(audio: np.ndarray, sr: int = SR) -> dict:
    """Integrated LUFS + a simple LRA (p95-p10 of 3s short-term loudness).

    Returns None values for silence instead of crashing (-inf handling).
    """
    meter = pyln.Meter(sr)
    if not np.any(audio):
        return {"lufs": None, "lra": None}
    integrated = meter.integrated_loudness(audio.astype(np.float64))
    if math.isinf(integrated):
        return {"lufs": None, "lra": None}
    window = int(3.0 * sr)
    shorts = []
    for start in range(0, max(1, len(audio) - window), window // 2):
        chunk = audio[start:start + window]
        if len(chunk) < window // 2 or not np.any(chunk):
            continue
        st = meter.integrated_loudness(chunk.astype(np.float64))
        if not math.isinf(st):
            shorts.append(st)
    lra = float(np.percentile(shorts, 95) - np.percentile(shorts, 10)) if len(shorts) >= 3 else None
    return {"lufs": float(integrated), "lra": lra}


def crest_factor_db(audio: np.ndarray) -> float | None:
    rms = float(np.sqrt(np.mean(audio ** 2)))
    peak = float(np.abs(audio).max())
    if rms == 0.0 or peak == 0.0:
        return None
    return 20.0 * math.log10(peak / rms)


def normalize_lufs(audio: np.ndarray, sr: int = SR, target: float = NORM_TARGET_LUFS) -> np.ndarray:
    """Gain-scale to the target LUFS so spectral comparisons are level-fair."""
    m = lufs_metrics(audio, sr)
    if m["lufs"] is None:
        return audio
    gain = 10.0 ** ((target - m["lufs"]) / 20.0)
    return audio * gain


def spectral_centroid_hz(audio: np.ndarray, sr: int = SR) -> float | None:
    if not np.any(audio):
        return None
    spectrum = np.abs(np.fft.rfft(audio.astype(np.float64)))
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sr)
    total = spectrum.sum()
    if total == 0:
        return None
    return float((spectrum * freqs).sum() / total)


def spectral_tilt(audio: np.ndarray, sr: int = SR) -> float | None:
    """Slope of log-magnitude vs log-frequency (dB/octave-ish; 0 ~= flat noise)."""
    if not np.any(audio):
        return None
    spectrum = np.abs(np.fft.rfft(audio.astype(np.float64)))
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sr)
    mask = (freqs >= 40) & (freqs <= 16000) & (spectrum > 0)
    if mask.sum() < 16:
        return None
    x = np.log2(freqs[mask])
    y = 20.0 * np.log10(spectrum[mask])
    slope = float(np.polyfit(x, y, 1)[0])
    return slope


# ---------------------------------------------------------------------------
# Symbolic metrics (event lists, never audio)
# ---------------------------------------------------------------------------

def note_density(events: list[MidiEvent], for_bars: int) -> dict[str, float]:
    """Note-ons per bar, per role group."""
    counts: dict[str, int] = {}
    for ev in events:
        if ev.kind != "on":
            continue
        role = _CHANNEL_ROLES.get(ev.channel, f"ch{ev.channel}")
        counts[role] = counts.get(role, 0) + 1
    return {role: round(n / for_bars, 3) for role, n in sorted(counts.items())}


def _event_fingerprint(events: list[MidiEvent]) -> set:
    # velocity-independent so humanization does not read as novelty
    return {(e.tick, e.kind, e.channel, e.note) for e in events if e.kind != "cc"}


def novelty(events_a: list[MidiEvent], events_b: list[MidiEvent]) -> float:
    """FS8 spec-distance between consecutive phrases: |symdiff| / |union|.

    0.0 = identical material, 1.0 = nothing shared. Pure function of the
    event lists; render both phrases with the SAME seed when comparing specs.
    """
    a, b = _event_fingerprint(events_a), _event_fingerprint(events_b)
    union = a | b
    if not union:
        return 0.0
    return round(len(a ^ b) / len(union), 4)


def energy_proxy(spec: PatternSpec, seed: int = 0) -> float:
    """THE canonical energy proxy: mean windowed RMS of the offline render."""
    audio = render_audio(spec, seed)
    window = int(RMS_WINDOW_S * SR)
    rms = [float(np.sqrt(np.mean(audio[s:s + window] ** 2)))
           for s in range(0, max(1, len(audio) - window), window)]
    return round(float(np.mean(rms)), 6) if rms else 0.0


# ---------------------------------------------------------------------------
# Session report
# ---------------------------------------------------------------------------

def analyze_wav(audio: np.ndarray, sr: int = SR) -> dict:
    """Full audio-metric set for any mono buffer (render or catalog track)."""
    normalized = normalize_lufs(audio, sr)
    return {
        "advisory": {
            "lufs": lufs_metrics(audio, sr)["lufs"],
            "lra": lufs_metrics(audio, sr)["lra"],
            "crest_db": crest_factor_db(audio),
        },
        "reference_informed": {
            "centroid_hz": spectral_centroid_hz(normalized, sr),
            "tilt_db_per_oct": spectral_tilt(normalized, sr),
        },
    }


def session_report(specs: list[PatternSpec], seed: int = 0) -> dict:
    """Render-free symbolic metrics + per-phrase energy for a spec sequence."""
    phrases = []
    prev_events = None
    for i, spec in enumerate(specs):
        events = render(spec, seed + i)
        entry = {
            "summary": spec.summary(),
            "reason": spec.reason,
            "note_density": note_density(events, spec.for_bars),
            "energy": energy_proxy(spec, seed + i),
        }
        if prev_events is not None:
            entry["novelty_vs_prev"] = novelty(render(spec, seed), prev_events)
        phrases.append(entry)
        prev_events = render(spec, seed)  # same-seed fingerprint for novelty
    return {"phrases": phrases}


def load_references(path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
