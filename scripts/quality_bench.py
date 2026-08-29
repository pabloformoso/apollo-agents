"""Quality bench CLI (S-1 / #71): render a generative session, measure, compare.

    uv run python scripts/quality_bench.py --genre lofi --phrases 3
    uv run python scripts/quality_bench.py --genre ambient --llm --strict
    uv run python scripts/quality_bench.py --wav output/algorave/deephouse-30s.wav --genre deep

--strict exits nonzero on reference_informed failures; advisory failures
always print and exit 0. Reports land in output/quality/<genre>-<seed>/.

--wav scores audio the bench did NOT render (the algorave/Strudel lane)
against the same genre references. It prints the report and writes only
when -o is given — an existing render is not ours to copy around.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from agent.generative.bench import (
    REFERENCES_PATH,
    BenchInputError,
    bench_wav,
    run_bench,
    to_markdown,
)
from agent.generative.genres import GENRE_PACKS
from agent.generative.spec import PatternSpec
from agent.generative.state import build_state

RENDER_ONLY_FLAGS = ("--phrases", "--seed", "--llm", "--intent")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--genre", default=None,
                        help=f"pack to render ({', '.join(sorted(GENRE_PACKS))}; default lofi) "
                             "— with --wav, any genre the references file carries")
    parser.add_argument("--phrases", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--llm", action="store_true", help="evolve specs via the mind")
    parser.add_argument("--intent", default=None)
    parser.add_argument("--wav", default=None,
                        help="score this externally rendered WAV instead of rendering one")
    parser.add_argument("--references", default=str(REFERENCES_PATH),
                        help="reference bands JSON (default: the committed catalog references)")
    parser.add_argument("--strict", action="store_true",
                        help="exit nonzero on reference_informed failures")
    parser.add_argument("-o", "--out", default=None,
                        help="report directory — the render mode always writes one, "
                             "--wav only when this is given")
    args = parser.parse_args(argv)

    if args.wav:
        return _score_wav(parser, args)

    load_dotenv()
    genre = args.genre or "lofi"
    if genre not in GENRE_PACKS:
        parser.error(f"--genre: no pack for '{genre}' (have: {', '.join(sorted(GENRE_PACKS))})")
    phrases = 2 if args.phrases is None else args.phrases
    seed = 0 if args.seed is None else args.seed
    intent = args.intent or ""

    specs = None
    if args.llm:
        from agent.generative.mind import Mind, MindError
        spec = PatternSpec.from_dict(GENRE_PACKS[genre]["starter"])
        specs, reasons, bars = [spec], [spec.reason], spec.for_bars
        mind = Mind(genre=genre)
        for _ in range(phrases - 1):
            try:
                spec = mind.next_spec(build_state(specs[-1], bars, intent, reasons), intent)
            except MindError as exc:
                print(f"[hold] {exc}")
            specs.append(spec)
            reasons.append(spec.reason)
            bars += spec.for_bars

    out = args.out or f"output/quality/{genre}-{seed}"
    report, passed = run_bench(genre, phrases, seed, out_dir=out, specs=specs,
                               references_path=args.references)
    print(Path(out, "report.md").read_text(encoding="utf-8"))
    if not passed:
        print(f"[bench] reference_informed FAIL — {'; '.join(report['reference_informed_failures'])}")
        return 1 if args.strict else 0
    return 0


def _score_wav(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """--wav path: measure an existing render, no synthesis, no seed."""
    given = [flag for flag, used in zip(RENDER_ONLY_FLAGS,
                                        (args.phrases is not None, args.seed is not None,
                                         args.llm, args.intent is not None)) if used]
    if given:
        parser.error("--wav scores an existing render and cannot be combined with "
                     f"the render-mode flags ({', '.join(given)})")
    if not args.genre:
        parser.error("--wav needs --genre: which genre's reference bands to score against")

    try:
        report, passed = bench_wav(args.wav, args.genre, out_dir=args.out,
                                   references_path=args.references)
    except BenchInputError as exc:
        parser.error(str(exc))
    print(to_markdown(report))
    if not passed:
        print(f"[bench] reference_informed FAIL — {'; '.join(report['reference_informed_failures'])}")
        return 1 if args.strict else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
