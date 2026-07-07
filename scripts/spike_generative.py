"""Thin-vertical spike: reasoned generative MIDI engine (§11 of the spec doc).

Wires the fast plane (clock -> interpreter -> MIDI port) to one slow-plane
call per phrase. Type natural-language direction while it plays:

    uv run python scripts/spike_generative.py                 # LLM-driven
    uv run python scripts/spike_generative.py --no-llm        # loop the seed spec
    uv run python scripts/spike_generative.py --phrases 4     # bounded run

    > darker            (any line becomes the standing intent)
    > build to a peak
    > quit              (or q / Ctrl+C)

Needs: `uv sync --group synth`, loopMIDI running, a synth listening on the
port. Run from the main checkout so .env is present for the LLM.

Reason-ahead (A7-lite): the next spec is requested in a background thread
at the START of each phrase; if it isn't ready when the phrase ends, the
current spec loops one more phrase (reject-and-hold — audio never stops).
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from agent.generative.clock import Clock
from agent.generative.controls import LiveControls
from agent.generative.dispatch import SplitPort, all_notes_off, open_output, play_events
from agent.generative.patches import expected_setup
from agent.generative.interpreter import render, total_ticks
from agent.generative.mind import Mind, MindError
from agent.generative.spec import PatternSpec
from agent.generative.state import build_state

# Starter specs + genre briefs live in one place (M-6).
from agent.generative.genres import GENRE_PACKS


_EOF = "\x00eof"  # sentinel: stdin closed (terminal gone / piped input exhausted)


def _intent_reader(q: "queue.Queue[str]") -> None:
    for line in sys.stdin:
        q.put(line.strip())
    q.put(_EOF)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", default="loopMIDI", help="substring of the MIDI output port name")
    parser.add_argument("--drum-port", default=None,
                        help="substring of a SECOND port for drums (ch 10) — see "
                             "docs/surge-multitimbral-setup.md")
    parser.add_argument("--genre", default="deep", choices=sorted(GENRE_PACKS),
                        help="genre pack: starter spec + idiom brief for the mind")
    parser.add_argument("--bpm", type=float, default=None, help="override starter BPM")
    parser.add_argument("--key", default=None, help="override starter Camelot key")
    parser.add_argument("--bars", type=int, default=None, help="override bars per phrase")
    parser.add_argument("--phrases", type=int, default=0, help="stop after N phrases (0 = run until quit)")
    parser.add_argument("--seed", type=int, default=0, help="humanization RNG seed")
    parser.add_argument("--no-llm", action="store_true", help="loop the seed spec, no slow plane")
    parser.add_argument("--intent", default="", help="initial standing intent")
    args = parser.parse_args()

    load_dotenv()

    starter = dict(GENRE_PACKS[args.genre]["starter"])
    if args.bpm:
        starter["bpm"] = args.bpm
    if args.key:
        starter["key"] = args.key
    if args.bars:
        starter["for_bars"] = starter["rethink_in_bars"] = args.bars
    spec = PatternSpec.from_dict(starter)

    port = open_output(args.port)
    if args.drum_port:
        port = SplitPort(port, open_output(args.drum_port))
    print(f"[spike] MIDI out: {port.name}")
    print(expected_setup(args.genre))
    mind = None if args.no_llm else Mind(genre=args.genre)
    intent = args.intent
    reasons: list[str] = [spec.reason]

    intents: "queue.Queue[str]" = queue.Queue()
    threading.Thread(target=_intent_reader, args=(intents,), daemon=True).start()
    print("[spike] type direction ('darker', 'build', ...) or 'quit'\n")

    stop = threading.Event()
    live = LiveControls()
    holder = {"intent": intent}
    bars_elapsed = 0
    phrase = 0

    def drain_intents(now_tick: int = 0) -> None:
        """Consume typed lines: quit stops NOW, direction ramps CCs NOW."""
        while not intents.empty():
            line = intents.get_nowait()
            if line == _EOF:
                # Unbounded runs need a live stdin — once the terminal is
                # gone nothing could ever say "quit", so don't orphan-loop.
                # Bounded runs (--phrases N) may legitimately run headless.
                if args.phrases == 0:
                    print("[spike] stdin closed — stopping (no way to receive 'quit')")
                    stop.set()
            elif line.lower() in ("quit", "q", "exit"):
                stop.set()
            elif line:
                holder["intent"] = line
                ramped = live.trigger(line, now_tick)
                print(f"[intent] -> {line!r}" + (" (CC ramp started)" if ramped else ""))

    def controller(tick: int):
        drain_intents(tick)
        return live.on_tick(tick)

    try:
        while not stop.is_set() and (args.phrases == 0 or phrase < args.phrases):
            drain_intents()
            if stop.is_set():
                break
            intent = holder["intent"]

            clock = Clock(spec.bpm)
            events = render(spec, seed=args.seed + phrase)

            # Reason-ahead: ask for phrase N+1 while N plays.
            next_holder: dict = {}
            if mind is not None:
                state = build_state(spec, bars_elapsed, intent, reasons)

                def think(holder=next_holder, state=state, current_intent=intent):
                    try:
                        holder["spec"] = mind.next_spec(state, current_intent)
                    except MindError as exc:
                        holder["error"] = str(exc)

                thinker = threading.Thread(target=think, daemon=True)
                thinker.start()

            print(f"[phrase {phrase + 1}] {spec.summary()}")
            print(f"[reason] {spec.reason}")
            play_events(events, clock, port, total_ticks(spec), stop_event=stop,
                        controller=controller)
            stats = clock.jitter_stats()
            print(f"[clock]  p50 {stats['p50_ms']}ms  p99 {stats['p99_ms']}ms  max {stats['max_ms']}ms")

            bars_elapsed += spec.for_bars
            phrase += 1

            if mind is not None:
                if "spec" in next_holder:
                    spec = next_holder["spec"]
                    reasons.append(spec.reason)
                elif "error" in next_holder:
                    print(f"[hold]   {next_holder['error']}")
                else:
                    print("[hold]   mind not ready — looping current spec (A7 gap)")
            print()
    except KeyboardInterrupt:
        pass
    finally:
        all_notes_off(port)
        port.close()
    print(f"[spike] done — {phrase} phrases, {bars_elapsed} bars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
