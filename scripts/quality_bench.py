"""Quality bench CLI (S-1 / #71): render a generative session, measure, compare.

    uv run python scripts/quality_bench.py --genre lofi --phrases 3
    uv run python scripts/quality_bench.py --genre ambient --llm --strict

--strict exits nonzero on reference_informed failures; advisory failures
always print and exit 0. Reports land in output/quality/<genre>-<seed>/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from agent.generative.bench import run_bench
from agent.generative.genres import GENRE_PACKS
from agent.generative.spec import PatternSpec
from agent.generative.state import build_state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--genre", default="lofi", choices=sorted(GENRE_PACKS))
    parser.add_argument("--phrases", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--llm", action="store_true", help="evolve specs via the mind")
    parser.add_argument("--intent", default="")
    parser.add_argument("--strict", action="store_true",
                        help="exit nonzero on reference_informed failures")
    parser.add_argument("-o", "--out", default=None)
    args = parser.parse_args()

    load_dotenv()
    specs = None
    if args.llm:
        from agent.generative.mind import Mind, MindError
        spec = PatternSpec.from_dict(GENRE_PACKS[args.genre]["starter"])
        specs, reasons, bars = [spec], [spec.reason], spec.for_bars
        mind = Mind(genre=args.genre)
        for _ in range(args.phrases - 1):
            try:
                spec = mind.next_spec(build_state(specs[-1], bars, args.intent, reasons), args.intent)
            except MindError as exc:
                print(f"[hold] {exc}")
            specs.append(spec)
            reasons.append(spec.reason)
            bars += spec.for_bars

    out = args.out or f"output/quality/{args.genre}-{args.seed}"
    report, passed = run_bench(args.genre, args.phrases, args.seed, out_dir=out, specs=specs)
    print(Path(out, "report.md").read_text(encoding="utf-8"))
    if not passed:
        print(f"[bench] reference_informed FAIL — {'; '.join(report['reference_informed_failures'])}")
        return 1 if args.strict else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
