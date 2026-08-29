"""External-WAV scoring mode for the quality bench (`--wav`).

The bench could only score audio it rendered itself, so the algorave/Strudel
lane — which hands us a finished 48 kHz stereo WAV and no spec sequence —
had no way to be gated against the committed references.

Band assertions are measured, not guessed: every case synthesizes a WAV,
runs it through the SAME load+analyze path the bench uses, and then writes
a references file whose bands are built around (pass) or far outside (fail)
the numbers that came back. The fail bands clear the bench's own margins
(2.5x on centroid, +-8 dB/oct on tilt) on purpose — a band that only looks
disjoint would be widened back into a pass.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import soundfile as sf

from agent.generative.bench import (
    BenchInputError,
    bench_wav,
    load_wav_mono,
    to_markdown,
)
from agent.generative.quality import NORM_TARGET_LUFS, analyze_wav
from agent.generative.render_audio import SR

from scripts.quality_bench import main

GENRE = "deep"


# --- fixtures: synthetic audio + references built around what it measures -----

def write_wav(path, seconds=2.0, sr=SR, channels=1, freq=220.0, amp=0.3, seed=7):
    """A tone with a little noise: loud enough for LUFS, tilted enough for slope."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * sr)) / sr
    mono = amp * np.sin(2 * np.pi * freq * t) + 0.02 * rng.standard_normal(t.size)
    data = mono if channels == 1 else np.stack([mono, mono * 0.5], axis=1)
    sf.write(str(path), data.astype(np.float32), sr)
    return path


def measure(path) -> dict:
    """Exactly what bench_wav will do to the file — no independent guessing."""
    mono, _, _ = load_wav_mono(path)
    return analyze_wav(mono, SR)


def bands(metrics: dict, matching: bool) -> dict:
    ri = metrics["reference_informed"]
    c, t = ri["centroid_hz"], ri["tilt_db_per_oct"]
    if matching:
        return {"centroid_hz": {"min": round(c * 0.95, 1), "max": round(c * 1.05, 1)},
                "tilt_db_per_oct": {"min": round(t - 0.5, 2), "max": round(t + 0.5, 2)}}
    return {"centroid_hz": {"min": round(c * 10, 1), "max": round(c * 20, 1)},
            "tilt_db_per_oct": {"min": round(t + 30, 2), "max": round(t + 40, 2)}}


def write_references(tmp_path, metrics, matching=True, genre=GENRE, name="refs.json"):
    payload = {genre: {"files": ["synthetic.wav"],
                       "norm_target_lufs": NORM_TARGET_LUFS,
                       **bands(metrics, matching),
                       "advisory_lufs": {"min": -20.0, "max": -16.0}}}
    path = tmp_path / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def scored(tmp_path):
    """(wav, metrics) for a plain mono render at the bench's own rate."""
    wav = write_wav(tmp_path / "render.wav")
    return wav, measure(wav)


# --- verdicts ----------------------------------------------------------------

def test_in_band_wav_passes(scored, tmp_path):
    wav, metrics = scored
    refs = write_references(tmp_path, metrics, matching=True)
    report, passed = bench_wav(wav, GENRE, references_path=refs)
    assert passed is True
    assert report["reference_informed_failures"] == []
    assert main(["--wav", str(wav), "--genre", GENRE, "--references", str(refs)]) == 0


def test_out_of_band_wav_fails_and_names_both_metrics(scored, tmp_path):
    wav, metrics = scored
    refs = write_references(tmp_path, metrics, matching=False)
    report, passed = bench_wav(wav, GENRE, references_path=refs)
    assert passed is False
    joined = " ".join(report["reference_informed_failures"])
    assert "centroid" in joined and "tilt" in joined


def test_strict_exits_nonzero_when_out_of_band(scored, tmp_path):
    wav, metrics = scored
    refs = write_references(tmp_path, metrics, matching=False)
    code = main(["--wav", str(wav), "--genre", GENRE, "--references", str(refs), "--strict"])
    assert code == 1


def test_without_strict_exits_zero_but_the_report_says_fail(scored, tmp_path, capsys):
    wav, metrics = scored
    refs = write_references(tmp_path, metrics, matching=False)
    code = main(["--wav", str(wav), "--genre", GENRE, "--references", str(refs)])
    out = capsys.readouterr().out
    assert code == 0                      # advisory-by-default, same as render mode
    assert "FAIL:" in out                 # the markdown verdict
    assert "[bench] reference_informed FAIL" in out


def test_strict_exits_zero_when_in_band(scored, tmp_path):
    wav, metrics = scored
    refs = write_references(tmp_path, metrics, matching=True)
    assert main(["--wav", str(wav), "--genre", GENRE, "--references", str(refs), "--strict"]) == 0


# --- loading: downmix + resample ---------------------------------------------

def test_stereo_downmix_is_the_channel_mean(tmp_path):
    wav = write_wav(tmp_path / "stereo.wav", channels=2)
    mono, sr, channels = load_wav_mono(wav)
    raw, _ = sf.read(str(wav), always_2d=True)
    assert (sr, channels) == (SR, 2)
    assert mono.ndim == 1
    assert np.allclose(mono, raw.mean(axis=1), atol=1e-6)


def test_stereo_48k_is_downmixed_and_resampled_then_scored(tmp_path):
    """The shape the algorave lane actually produces: 48 kHz stereo."""
    wav = write_wav(tmp_path / "algorave.wav", sr=48000, channels=2)
    mono, sr, channels = load_wav_mono(wav)
    assert (sr, channels) == (48000, 2)
    assert mono.ndim == 1
    assert len(mono) == pytest.approx(2.0 * SR, rel=0.01)   # 2 s at the bench rate

    refs = write_references(tmp_path, analyze_wav(mono, SR), matching=True)
    report, passed = bench_wav(wav, GENRE, references_path=refs)
    assert passed is True
    assert report["source_sample_rate"] == 48000
    assert report["source_channels"] == 2
    assert report["duration_sec"] == pytest.approx(2.0, abs=0.05)


# --- operator errors: a message, never a traceback ----------------------------

def test_missing_file_is_a_clean_exit(tmp_path, capsys):
    missing = tmp_path / "nope.wav"
    with pytest.raises(SystemExit) as exc:
        main(["--wav", str(missing), "--genre", GENRE])
    assert exc.value.code == 2
    assert "WAV not found" in capsys.readouterr().err


def test_unreadable_audio_is_a_clean_exit(tmp_path, capsys):
    fake = tmp_path / "not-really.wav"
    fake.write_text("this is not a RIFF header", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main(["--wav", str(fake), "--genre", GENRE])
    assert exc.value.code == 2
    assert "cannot read" in capsys.readouterr().err


def test_unknown_genre_is_a_clean_exit(scored, capsys):
    wav, _ = scored
    with pytest.raises(SystemExit) as exc:
        main(["--wav", str(wav), "--genre", "gabber"])
    assert exc.value.code == 2
    assert "no references for genre 'gabber'" in capsys.readouterr().err


def test_references_file_without_that_genre_is_a_clean_exit(scored, tmp_path, capsys):
    wav, metrics = scored
    refs = write_references(tmp_path, metrics, genre="deep")
    with pytest.raises(SystemExit) as exc:
        main(["--wav", str(wav), "--genre", "lofi", "--references", str(refs)])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "no references for genre 'lofi'" in err
    assert "has: deep" in err              # says what IS available


def test_missing_references_file_is_a_clean_exit(scored, tmp_path, capsys):
    wav, _ = scored
    with pytest.raises(SystemExit) as exc:
        main(["--wav", str(wav), "--genre", GENRE,
              "--references", str(tmp_path / "gone.json")])
    assert exc.value.code == 2
    assert "references file not found" in capsys.readouterr().err


def test_malformed_references_file_is_a_clean_exit(scored, tmp_path, capsys):
    wav, _ = scored
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main(["--wav", str(wav), "--genre", GENRE, "--references", str(broken)])
    assert exc.value.code == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_empty_wav_is_a_clean_error(tmp_path):
    empty = tmp_path / "empty.wav"
    sf.write(str(empty), np.zeros((0,), dtype=np.float32), SR)
    with pytest.raises(BenchInputError, match="no audio frames"):
        load_wav_mono(empty)


# --- argument wiring ----------------------------------------------------------

@pytest.mark.parametrize("flag", [["--phrases", "3"], ["--seed", "5"], ["--llm"],
                                  ["--intent", "darker"]])
def test_render_only_flags_cannot_be_combined_with_wav(scored, flag, capsys):
    wav, _ = scored
    with pytest.raises(SystemExit) as exc:
        main(["--wav", str(wav), "--genre", GENRE] + flag)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert flag[0] in err and "cannot be combined" in err


def test_wav_requires_a_genre(scored, capsys):
    wav, _ = scored
    with pytest.raises(SystemExit) as exc:
        main(["--wav", str(wav)])
    assert exc.value.code == 2
    assert "--wav needs --genre" in capsys.readouterr().err


def test_render_mode_still_rejects_an_unknown_genre(capsys):
    """--genre lost its argparse `choices`; the check moved, it did not vanish."""
    with pytest.raises(SystemExit) as exc:
        main(["--genre", "gabber"])
    assert exc.value.code == 2
    assert "no pack for 'gabber'" in capsys.readouterr().err


def test_out_writes_a_valid_json_report(scored, tmp_path):
    wav, metrics = scored
    refs = write_references(tmp_path, metrics, matching=True)
    out = tmp_path / "report-dir"
    assert main(["--wav", str(wav), "--genre", GENRE,
                 "--references", str(refs), "-o", str(out)]) == 0
    written = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert written["genre"] == GENRE
    assert written["passed"] is True
    assert written["wav"] == str(wav)
    assert written["phrases"] == []       # no specs behind an external render
    assert {"advisory", "reference_informed"} <= set(written["audio"])
    assert "Verdict" in (out / "report.md").read_text(encoding="utf-8")


def test_no_out_writes_nothing(scored, tmp_path):
    """An existing render is not ours to copy around."""
    wav, metrics = scored
    refs = write_references(tmp_path, metrics, matching=True)
    before = set(tmp_path.iterdir())
    assert main(["--wav", str(wav), "--genre", GENRE, "--references", str(refs)]) == 0
    assert set(tmp_path.iterdir()) == before


# --- report rendering ---------------------------------------------------------

def test_wav_report_keeps_the_render_report_format(scored, tmp_path, capsys):
    wav, metrics = scored
    refs = write_references(tmp_path, metrics, matching=True)
    main(["--wav", str(wav), "--genre", GENRE, "--references", str(refs)])
    out = capsys.readouterr().out
    assert out.startswith(f"# Quality bench — {GENRE} (wav render.wav)")
    assert "## Audio" in out and "## Verdict" in out
    assert "*(advisory)*" in out                        # advisory tier still printed
    assert "LUFS" in out and "crest" in out
    assert "## Phrases" not in out                      # nothing symbolic to show
    assert f"@ {SR} Hz" in out                          # says what it measured


RENDER_MARKDOWN = """\
# Quality bench — lofi (seed 3)

## Audio
- LUFS -21.5 · LRA 3.2 · crest 12.0 dB *(advisory)*
- centroid 900.1 Hz · tilt -9.5 dB/oct *(reference_informed, normalized to -20.0 LUFS)*

## Phrases
1. energy 0.01 · density {'drums': 4.0}
   open
2. energy 0.02 · novelty 0.3 · density {'drums': 8.0}
   lift

## Verdict
PASS
"""


def test_render_report_markdown_is_byte_identical():
    """The WAV branch must not have moved a single character of the old format."""
    report = {
        "genre": "lofi", "seed": 3,
        "audio": {"advisory": {"lufs": -21.5, "lra": 3.2, "crest_db": 12.0},
                  "reference_informed": {"centroid_hz": 900.1, "tilt_db_per_oct": -9.5}},
        "phrases": [{"energy": 0.01, "note_density": {"drums": 4.0}, "reason": "open"},
                    {"energy": 0.02, "note_density": {"drums": 8.0}, "reason": "lift",
                     "novelty_vs_prev": 0.3}],
        "reference_informed_failures": [],
        "passed": True,
    }
    assert to_markdown(report) == RENDER_MARKDOWN
