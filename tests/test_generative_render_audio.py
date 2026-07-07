"""B-3: offline spec -> WAV render. Deterministic, bounded, correct length."""

import numpy as np
import pytest

from agent.generative.interpreter import TICKS_PER_BEAT, total_ticks
from agent.generative.render_audio import SR, render_audio, render_wav
from agent.generative.spec import PatternSpec

from tests.test_generative_spec import valid_spec_dict


def small_spec(**overrides):
    return PatternSpec.from_dict(valid_spec_dict(for_bars=2, **overrides))


def test_render_is_deterministic():
    spec = small_spec()
    a = render_audio(spec, seed=5)
    b = render_audio(spec, seed=5)
    assert np.array_equal(a, b)


def test_different_seed_differs():
    spec = small_spec()
    assert not np.array_equal(render_audio(spec, 1), render_audio(spec, 2))


def test_length_matches_phrase_plus_tail():
    spec = small_spec()
    audio = render_audio(spec, 0)
    phrase_s = total_ticks(spec) * 60.0 / (spec.bpm * TICKS_PER_BEAT)
    assert len(audio) == int(phrase_s * SR) + int(0.5 * SR)


def test_audio_is_bounded_and_nonsilent():
    audio = render_audio(small_spec(), 0)
    assert audio.dtype == np.float32
    assert np.abs(audio).max() <= 0.85 + 1e-6
    assert np.abs(audio).max() > 0.05  # something actually sounds


def test_kick_puts_energy_at_beat_positions():
    d = valid_spec_dict(for_bars=1)
    d["roles"] = {"kick": {"pattern": "4-on-floor", "vel": 120}}
    audio = render_audio(PatternSpec.from_dict(d), 0)
    beat_s = 60.0 / 122
    window = int(0.05 * SR)
    for beat in range(4):
        start = int(beat * beat_s * SR)
        rms_at_beat = np.sqrt(np.mean(audio[start:start + window] ** 2))
        assert rms_at_beat > 0.01, f"no kick energy at beat {beat}"


def test_pad_only_spec_renders():
    d = valid_spec_dict(for_bars=2)
    d["roles"] = {"pad": {"progression": [[0, "Am9"], [1, "Fmaj7"]], "hold": True, "vel": 70}}
    audio = render_audio(PatternSpec.from_dict(d), 0)
    assert np.abs(audio).max() > 0.02


def test_controls_only_spec_is_silent():
    d = valid_spec_dict(for_bars=1)
    d["roles"] = {"controls": {"ramps": [{"cc": 74, "from": 0.0, "to": 1.0, "over_bars": 1}]}}
    audio = render_audio(PatternSpec.from_dict(d), 0)
    assert np.abs(audio).max() == 0.0  # CC automation is a documented non-render


def test_render_wav_concatenates_phrases(tmp_path):
    import soundfile as sf

    spec = small_spec()
    out = tmp_path / "test.wav"
    seconds = render_wav([spec, spec], str(out), seed=0)
    data, sr = sf.read(str(out))
    assert sr == SR
    phrase_s = total_ticks(spec) * 60.0 / (spec.bpm * TICKS_PER_BEAT)
    assert seconds == pytest.approx(2 * phrase_s + 0.5, abs=0.01)
    assert len(data) == int(seconds * SR)
