"""Offline render: pattern-spec -> WAV (B-3). The remote ear test.

Pure numpy additive/subtractive voices — no synth, no DAW, no MIDI port,
no new dependencies. Deliberately plain: the point is to judge NOTES,
GROOVE and VOICE LEADING from anywhere, not to sound like the live Surge
chain. Deterministic: same spec + seed -> byte-identical samples.

Not rendered (v1 limitations, by design):
- 'controls' CC ramps (timbral automation needs the real synth)
- swing feel of the *synth* (envelope character etc.)

Voices: kick = sine sweep w/ exp decay; snare = noise burst + tone;
hats = differentiated noise tick; bass = 3-partial saw-ish with ADSR;
pad = detuned 2-layer partials with slow attack.
"""

from __future__ import annotations

import numpy as np

from .interpreter import (
    BASS_CHANNEL,
    DRUM_CHANNEL,
    DRUM_NOTES,
    PAD_CHANNEL,
    TICKS_PER_BEAT,
    MidiEvent,
    render,
    total_ticks,
)
from .spec import PatternSpec

SR = 44100

_GAINS = {"kick": 0.9, "snare": 0.55, "hats": 0.3, "perc": 0.4, "shaker": 0.22,
          "clap": 0.5, "bass": 0.55, "pad": 0.4}


def _midi_to_freq(note: int) -> float:
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


def _kick(dur_s: float, vel: float) -> np.ndarray:
    t = np.arange(int(dur_s * SR)) / SR
    freq = 120.0 * np.exp(-t * 30.0) + 45.0
    phase = 2 * np.pi * np.cumsum(freq) / SR
    return np.sin(phase) * np.exp(-t * 14.0) * vel


def _lowpass(sig: np.ndarray, cutoff_hz: float) -> np.ndarray:
    """Cheap deterministic FFT-domain 2nd-order-ish lowpass for short voices.

    Unfiltered differentiated noise put the render's centroid near 10 kHz —
    the quality bench (#71) flagged it against the catalog references; real
    lofi/ambient sits dark. This keeps the noise voices genre-plausible.
    """
    spectrum = np.fft.rfft(sig)
    freqs = np.fft.rfftfreq(len(sig), 1.0 / SR)
    spectrum *= 1.0 / (1.0 + (freqs / cutoff_hz) ** 2)
    return np.fft.irfft(spectrum, n=len(sig))


def _snare(dur_s: float, vel: float, rng: np.random.Generator) -> np.ndarray:
    n = int(dur_s * SR)
    t = np.arange(n) / SR
    noise = _lowpass(np.diff(rng.uniform(-1, 1, n + 1)), 3500.0)
    tone = np.sin(2 * np.pi * 185.0 * t) * np.exp(-t * 30.0)
    return (noise * np.exp(-t * 25.0) * 1.6 + tone * 0.5) * vel


def _hat(dur_s: float, vel: float, rng: np.random.Generator) -> np.ndarray:
    n = int(dur_s * SR)
    t = np.arange(n) / SR
    noise = _lowpass(np.diff(rng.uniform(-1, 1, n + 1)), 6500.0)
    return noise * np.exp(-t * 60.0) * vel * 1.8


def _tonal(note: int, dur_s: float, vel: float, *, partials, attack_s: float,
           release_s: float, detune: float = 0.0) -> np.ndarray:
    n = int((dur_s + release_s) * SR)
    t = np.arange(n) / SR
    freq = _midi_to_freq(note)
    sig = np.zeros(n)
    for mult, amp in partials:
        sig += amp * np.sin(2 * np.pi * freq * mult * t)
        if detune:
            sig += amp * 0.5 * np.sin(2 * np.pi * freq * mult * (1 + detune) * t)
    env = np.ones(n)
    a = max(1, int(attack_s * SR))
    env[:a] = np.linspace(0.0, 1.0, a)
    r = max(1, int(release_s * SR))
    env[-r:] *= np.linspace(1.0, 0.0, r)
    return sig * env * vel


def _bass(note: int, dur_s: float, vel: float) -> np.ndarray:
    return _tonal(note, dur_s, vel, partials=((1, 1.0), (2, 0.35), (3, 0.12)),
                  attack_s=0.005, release_s=0.05)


def _pad(note: int, dur_s: float, vel: float) -> np.ndarray:
    attack = min(0.4, dur_s * 0.25)
    return _tonal(note, dur_s, vel, partials=((1, 1.0), (2, 0.4), (4, 0.1)),
                  attack_s=attack, release_s=0.35, detune=0.0015)


def _paired_notes(events: list[MidiEvent]) -> list[tuple[int, int, int, int, int]]:
    """(on_tick, off_tick, channel, note, velocity) — FIFO pairing per (ch, note)."""
    open_notes: dict[tuple[int, int], list[tuple[int, int]]] = {}
    pairs = []
    for ev in sorted(events):
        key = (ev.channel, ev.note)
        if ev.kind == "on":
            open_notes.setdefault(key, []).append((ev.tick, ev.velocity))
        elif ev.kind == "off" and open_notes.get(key):
            on_tick, vel = open_notes[key].pop(0)
            pairs.append((on_tick, ev.tick, ev.channel, ev.note, vel))
    return pairs


def render_audio(spec: PatternSpec, seed: int = 0) -> np.ndarray:
    """One phrase of a spec -> float32 mono samples in [-1, 1]."""
    events = render(spec, seed)
    sec_per_tick = 60.0 / (spec.bpm * TICKS_PER_BEAT)
    n_total = int(total_ticks(spec) * sec_per_tick * SR) + int(0.5 * SR)  # + release tail
    out = np.zeros(n_total)
    rng = np.random.default_rng(seed)  # noise voices only — seeded, deterministic

    drum_names = {num: name for name, num in DRUM_NOTES.items()}
    for on_tick, off_tick, channel, note, velocity in _paired_notes(events):
        start = int(on_tick * sec_per_tick * SR)
        dur_s = max(0.01, (off_tick - on_tick) * sec_per_tick)
        vel = (velocity / 127.0) ** 1.5
        if channel == DRUM_CHANNEL:
            name = drum_names.get(note, "hats")
            if name == "kick":
                sig = _kick(0.35, vel) * _GAINS["kick"]
            elif name in ("snare", "clap"):
                sig = _snare(0.25, vel, rng) * _GAINS[name]
            elif name == "perc":
                sig = _snare(0.09, vel, rng) * _GAINS["perc"]  # rimshot-ish: short snare burst
            else:  # hats, shaker
                sig = _hat(0.1, vel, rng) * _GAINS[name]
        elif channel == BASS_CHANNEL:
            sig = _bass(note, dur_s, vel) * _GAINS["bass"]
        elif channel == PAD_CHANNEL:
            sig = _pad(note, dur_s, vel) * _GAINS["pad"]
        else:
            continue
        end = min(start + len(sig), n_total)
        out[start:end] += sig[:end - start]

    peak = np.abs(out).max()
    if peak > 0.85:
        out *= 0.85 / peak
    return out.astype(np.float32)


def render_wav(specs: list[PatternSpec], out_path: str, seed: int = 0) -> float:
    """Render consecutive phrases (one spec each) to a WAV. Returns seconds."""
    import soundfile as sf

    chunks = []
    for i, spec in enumerate(specs):
        audio = render_audio(spec, seed=seed + i)
        # trim the release tail except on the last phrase, so phrases butt-join on the grid
        phrase_samples = int(total_ticks(spec) * 60.0 / (spec.bpm * TICKS_PER_BEAT) * SR)
        chunks.append(audio[:phrase_samples] if i < len(specs) - 1 else audio)
    full = np.concatenate(chunks)
    sf.write(out_path, full, SR)
    return len(full) / SR
