"""Quality bench runner + reference extraction (S-1 / issue #71).

- extract_references(): deterministic sweep over catalog WAVs (fixed sort,
  first N per genre) -> reference ranges JSON. Genre->folder map is explicit:
  lofi AND ambient share `tracks/lofi - ambient`.
- run_bench(): render a session, compute all metrics, compare against the
  references, write report.{json,md} + WAV. Two tiers: reference_informed
  failures gate --strict; advisory failures only print.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from .genres import GENRE_PACKS
from .quality import (
    NORM_TARGET_LUFS,
    analyze_wav,
    load_references,
    session_report,
)
from .render_audio import SR, render_audio
from .spec import PatternSpec

GENRE_FOLDERS = {
    "lofi": "lofi - ambient",
    "ambient": "lofi - ambient",
    "deep": "deep house",
}

REFERENCES_PATH = Path(__file__).parent / "quality_references.json"

# reference_informed margins: the render is sparse even after loudness
# normalization, so ranges are generous by design — the tier catches
# gross wrongness (screeching brightness, white-noise tilt), not taste.
CENTROID_RATIO_MAX = 2.5   # render centroid within [ref_min/R, ref_max*R]
TILT_DELTA_MAX = 8.0       # dB/oct beyond the reference range
NOVELTY_MAX = 0.95         # consecutive phrases sharing ~nothing = mode chaos


def extract_references(genre_dirs: dict[str, Path], n: int = 5, sr_limit: int | None = None) -> dict:
    """Analyze the first `n` WAVs (sorted by name) per genre. Deterministic."""
    refs: dict = {}
    for genre, folder in sorted(genre_dirs.items()):
        files = sorted(Path(folder).glob("*.wav"))[:n]
        if not files:
            continue
        centroids, tilts, lufs_vals = [], [], []
        for path in files:
            audio, sr = sf.read(str(path), always_2d=True)
            mono = audio.mean(axis=1)
            if sr_limit and len(mono) > sr * sr_limit:
                mono = mono[: sr * sr_limit]
            metrics = analyze_wav(mono.astype(np.float32), sr)
            ri, adv = metrics["reference_informed"], metrics["advisory"]
            if ri["centroid_hz"] is not None:
                centroids.append(ri["centroid_hz"])
            if ri["tilt_db_per_oct"] is not None:
                tilts.append(ri["tilt_db_per_oct"])
            if adv["lufs"] is not None:
                lufs_vals.append(adv["lufs"])
        refs[genre] = {
            "files": [p.name for p in files],
            "norm_target_lufs": NORM_TARGET_LUFS,
            "centroid_hz": {"min": round(min(centroids), 1), "max": round(max(centroids), 1)},
            "tilt_db_per_oct": {"min": round(min(tilts), 2), "max": round(max(tilts), 2)},
            "advisory_lufs": {"min": round(min(lufs_vals), 1), "max": round(max(lufs_vals), 1)},
        }
    return refs


def _check_reference_informed(genre_ref: dict, audio_metrics: dict, phrase_novelties: list[float]) -> list[str]:
    failures = []
    ri = audio_metrics["reference_informed"]
    c = ri["centroid_hz"]
    if c is not None and genre_ref:
        lo = genre_ref["centroid_hz"]["min"] / CENTROID_RATIO_MAX
        hi = genre_ref["centroid_hz"]["max"] * CENTROID_RATIO_MAX
        if not lo <= c <= hi:
            failures.append(f"centroid {c:.0f}Hz outside [{lo:.0f}, {hi:.0f}]")
    t = ri["tilt_db_per_oct"]
    if t is not None and genre_ref:
        lo = genre_ref["tilt_db_per_oct"]["min"] - TILT_DELTA_MAX
        hi = genre_ref["tilt_db_per_oct"]["max"] + TILT_DELTA_MAX
        if not lo <= t <= hi:
            failures.append(f"tilt {t:.1f}dB/oct outside [{lo:.1f}, {hi:.1f}]")
    for i, nov in enumerate(phrase_novelties):
        if nov > NOVELTY_MAX:
            failures.append(f"novelty {nov} > {NOVELTY_MAX} at phrase {i + 2} (mode chaos)")
    return failures


def run_bench(genre: str, phrases: int = 2, seed: int = 0, out_dir=None,
              specs: list[PatternSpec] | None = None,
              references_path=REFERENCES_PATH) -> tuple[dict, bool]:
    """Render + measure + compare. Returns (report, reference_informed_passed)."""
    if specs is None:
        starter = PatternSpec.from_dict(GENRE_PACKS[genre]["starter"])
        specs = [starter] * phrases

    chunks = [render_audio(s, seed + i) for i, s in enumerate(specs)]
    audio = np.concatenate(chunks)
    audio_metrics = analyze_wav(audio)
    symbolic = session_report(specs, seed)
    novelties = [p["novelty_vs_prev"] for p in symbolic["phrases"] if "novelty_vs_prev" in p]

    references = load_references(references_path) if Path(references_path).exists() else {}
    genre_ref = references.get(genre, {})
    failures = _check_reference_informed(genre_ref, audio_metrics, novelties)

    report = {
        "genre": genre,
        "seed": seed,
        "phrases": symbolic["phrases"],
        "audio": audio_metrics,
        "reference": genre_ref,
        "reference_informed_failures": failures,
        "passed": not failures,
    }

    if out_dir is not None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        sf.write(str(out / "session.wav"), audio, SR)
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (out / "report.md").write_text(_to_markdown(report), encoding="utf-8")
    return report, not failures


def _to_markdown(report: dict) -> str:
    lines = [f"# Quality bench — {report['genre']} (seed {report['seed']})", ""]
    adv, ri = report["audio"]["advisory"], report["audio"]["reference_informed"]
    lines += ["## Audio",
              f"- LUFS {adv['lufs']} · LRA {adv['lra']} · crest {adv['crest_db']} dB *(advisory)*",
              f"- centroid {ri['centroid_hz']} Hz · tilt {ri['tilt_db_per_oct']} dB/oct "
              f"*(reference_informed, normalized to {NORM_TARGET_LUFS} LUFS)*", "",
              "## Phrases"]
    for i, p in enumerate(report["phrases"]):
        nov = f" · novelty {p['novelty_vs_prev']}" if "novelty_vs_prev" in p else ""
        lines.append(f"{i + 1}. energy {p['energy']}{nov} · density {p['note_density']}")
        lines.append(f"   {p['reason']}")
    lines += ["", "## Verdict",
              "PASS" if report["passed"] else "FAIL: " + "; ".join(report["reference_informed_failures"])]
    return "\n".join(lines) + "\n"
