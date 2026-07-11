"""Offline ear test: render generative phrases to a WAV, no MIDI chain needed.

    uv run python scripts/render_generative.py --genre ambient --phrases 2 -o ambient.wav
    uv run python scripts/render_generative.py --genre lofi --phrases 3 --llm -o lofi.wav

--llm evolves the spec between phrases via the mind (needs .env); without it
the seed spec loops with per-phrase humanization variation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from agent.generative.genres import GENRE_PACKS
from agent.generative.render_audio import render_wav
from agent.generative.spec import PatternSpec
from agent.generative.state import build_state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--genre", default="ambient", choices=sorted(GENRE_PACKS))
    parser.add_argument("--phrases", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--llm", action="store_true", help="evolve specs phrase-to-phrase via the mind")
    parser.add_argument("--intent", default="", help="standing intent for --llm")
    parser.add_argument("-o", "--out", default=None, help="output WAV path")
    args = parser.parse_args()

    load_dotenv()
    out = args.out or f"render_{args.genre}_{args.phrases}p.wav"

    spec = PatternSpec.from_dict(GENRE_PACKS[args.genre]["starter"])
    specs = [spec]
    reasons = [spec.reason]
    if args.llm:
        from agent.generative.mind import Mind, MindError
        mind = Mind(genre=args.genre)
        bars = spec.for_bars
        for _ in range(args.phrases - 1):
            state = build_state(specs[-1], bars, args.intent, reasons)
            try:
                nxt = mind.next_spec(state, args.intent)
            except MindError as exc:
                print(f"[hold] {exc}")
                nxt = specs[-1]
            specs.append(nxt)
            reasons.append(nxt.reason)
            bars += nxt.for_bars
    else:
        specs = specs * args.phrases

    for i, s in enumerate(specs):
        print(f"[phrase {i + 1}] {s.summary()}")
        print(f"[reason]   {s.reason}")
    seconds = render_wav(specs, out, seed=args.seed)
    print(f"[render] {out} — {seconds:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
