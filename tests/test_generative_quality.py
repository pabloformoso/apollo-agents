"""S-1 (#71): quality metrics on synthetic signals + bench end-to-end + reference reproducibility."""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from agent.generative.bench import extract_references, run_bench
from agent.generative.interpreter import render
from agent.generative.quality import (
    NORM_TARGET_LUFS,
    crest_factor_db,
    energy_proxy,
    lufs_metrics,
    normalize_lufs,
    note_density,
    novelty,
    spectral_centroid_hz,
    spectral_tilt,
)
from agent.generative.render_audio import SR
from agent.generative.spec import PatternSpec

from tests.test_generative_spec import valid_spec_dict

FIXTURES = Path(__file__).parent / "fixtures" / "quality"


def sine(freq=440.0, seconds=1.0, amp=0.5):
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


# --- audio metrics on synthetic signals ------------------------------------------

def test_sine_centroid_near_its_frequency():
    c = spectral_centroid_hz(sine(440.0))
    assert 400 < c < 480


def test_silence_handled_without_crash():
    silent = np.zeros(SR, dtype=np.float32)
    assert lufs_metrics(silent) == {"lufs": None, "lra": None}
    assert crest_factor_db(silent) is None
    assert spectral_centroid_hz(silent) is None
    assert spectral_tilt(silent) is None


def test_white_noise_tilt_roughly_flat():
    rng = np.random.default_rng(3)
    noise = (0.3 * rng.uniform(-1, 1, 4 * SR)).astype(np.float32)
    tilt = spectral_tilt(noise)
    assert abs(tilt) < 3.0  # dB/oct — flat-ish


def test_sine_crest_factor_is_3db():
    assert crest_factor_db(sine()) == pytest.approx(20 * math.log10(math.sqrt(2)), abs=0.1)


def test_normalize_lufs_moves_loudness_to_target():
    quiet = sine(amp=0.05, seconds=4.0)
    normalized = normalize_lufs(quiet)
    assert lufs_metrics(normalized)["lufs"] == pytest.approx(NORM_TARGET_LUFS, abs=0.5)


# --- symbolic metrics ---------------------------------------------------------------

def spec_of(**overrides):
    return PatternSpec.from_dict(valid_spec_dict(**overrides))


def test_identical_phrases_novelty_zero():
    events = render(spec_of(), seed=4)
    assert novelty(events, events) == 0.0


def test_novelty_monotonic_with_change_count():
    base = spec_of()
    one = valid_spec_dict()
    one["roles"]["kick"] = {"pattern": "8ths", "vel": 110}
    two = valid_spec_dict()
    two["roles"]["kick"] = {"pattern": "8ths", "vel": 110}
    two["roles"]["hats"] = {"pattern": "16ths", "vel": 80}
    e0 = render(base, seed=4)
    n_one = novelty(e0, render(PatternSpec.from_dict(one), seed=4))
    n_two = novelty(e0, render(PatternSpec.from_dict(two), seed=4))
    assert 0.0 < n_one < n_two <= 1.0


def test_novelty_is_seed_independent():
    a, b = spec_of(), spec_of(for_bars=4)
    assert novelty(render(a, 1), render(b, 1)) == novelty(render(a, 99), render(b, 99))


def test_note_density_counts_per_bar():
    d = valid_spec_dict(for_bars=4)
    d["roles"] = {"kick": {"pattern": "4-on-floor", "vel": 110}}
    density = note_density(render(PatternSpec.from_dict(d), 0), 4)
    assert density == {"drums": 4.0}


def test_energy_proxy_deterministic_and_orders_density():
    sparse = valid_spec_dict(for_bars=2)
    sparse["roles"] = {"kick": {"pattern": "x" + "." * 15, "vel": 60}}
    dense = valid_spec_dict(for_bars=2)
    dense["roles"] = {"kick": {"pattern": "4-on-floor", "vel": 120},
                      "hats": {"pattern": "16ths", "vel": 100}}
    s, d = PatternSpec.from_dict(sparse), PatternSpec.from_dict(dense)
    assert energy_proxy(s, 5) == energy_proxy(s, 5)
    assert energy_proxy(d, 5) > energy_proxy(s, 5)


# --- bench end-to-end + references ---------------------------------------------------

@pytest.mark.parametrize("genre", ["lofi", "ambient"])
def test_bench_runs_headless_and_deterministic(genre, tmp_path):
    report1, _ = run_bench(genre, phrases=2, seed=3, out_dir=tmp_path / "a")
    report2, _ = run_bench(genre, phrases=2, seed=3, out_dir=tmp_path / "b")
    assert report1["phrases"] == report2["phrases"]
    assert (tmp_path / "a" / "report.md").exists()
    assert (tmp_path / "a" / "session.wav").exists()
    assert (tmp_path / "a" / "report.json").exists()


def test_bench_report_contains_all_metrics(tmp_path):
    report, _ = run_bench("lofi", phrases=2, seed=0, out_dir=tmp_path)
    assert {"lufs", "lra", "crest_db"} <= set(report["audio"]["advisory"])
    assert {"centroid_hz", "tilt_db_per_oct"} <= set(report["audio"]["reference_informed"])
    assert "note_density" in report["phrases"][0]
    assert "novelty_vs_prev" in report["phrases"][1]
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Verdict" in md


def test_reference_extraction_reproducible_on_fixtures():
    fresh = extract_references({"fixture": FIXTURES}, n=5)
    committed = json.loads((FIXTURES / "references_fixture.json").read_text(encoding="utf-8"))
    assert fresh == committed


def test_catalog_references_committed_and_complete():
    from agent.generative.bench import GENRE_FOLDERS, REFERENCES_PATH
    refs = json.loads(REFERENCES_PATH.read_text(encoding="utf-8"))
    assert set(refs) == set(GENRE_FOLDERS)
    for genre, ref in refs.items():
        assert len(ref["files"]) >= 5, genre
        assert ref["centroid_hz"]["min"] < ref["centroid_hz"]["max"]
