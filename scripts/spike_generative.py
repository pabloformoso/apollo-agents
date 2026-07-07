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
from agent.generative.dispatch import all_notes_off, open_output, play_events
from agent.generative.interpreter import render, total_ticks
from agent.generative.mind import Mind, MindError
from agent.generative.spec import PatternSpec
from agent.generative.state import build_state

STARTER_SPECS = {
    "deep": {
        "for_bars": 8,
        "bpm": 122,
        "key": "8A",
        "roles": {
            "kick": {"pattern": "4-on-floor", "vel": 110},
            "hats": {"pattern": "offbeat", "vel": 80, "swing": 0.12},
            "bass": {"notes": [[0, "A1", 1.0], [6, "A1", 0.5], [10, "E2", 0.5], [12, "G1", 1.0]], "vel": 92},
            "pad": {"chord": "Am9", "voicing": "wide", "vel": 55},
        },
        "reason": "seed groove — establish a deep 122bpm Am foundation before the mind takes over",
        "rethink_in_bars": 8,
    },
    # v3.0 slice 1 (issue #62): patient, voice-led, no grid — a chord meditation.
    "ambient": {
        "for_bars": 8,
        "bpm": 70,
        "key": "8A",
        "roles": {
            "pad": {"progression": [[0, "Am9"], [2, "Fmaj7"], [4, "Cmaj7"], [6, "Em7"]],
                    "voicing": "wide", "hold": True, "vel": 60},
            "bass": {"notes": [[0, "A1", 32.0]], "vel": 58},
            "controls": {"ramps": [{"cc": 74, "from": 0.25, "to": 0.55, "start_bar": 0, "over_bars": 8}]},
        },
        "reason": "seed meditation — Am9 to Em7 voice-led drift over a low A drone, filter breathing open",
        "rethink_in_bars": 8,
    },
    "lofi": {
        "for_bars": 8,
        "bpm": 78,
        "key": "8A",
        "roles": {
            "kick": {"pattern": "x......x..x.....", "vel": 96},
            "snare": {"pattern": "....x.......x...", "vel": 70},
            "hats": {"pattern": "x.x.x.x.x.x.x.x.", "swing": 0.3, "vel": 52},
            "bass": {"notes": [[0, "A1", 3.0], [12, "E2", 2.0]], "vel": 76},
            "pad": {"progression": [[0, "Am9"], [4, "Fmaj7"]], "voicing": "close", "hold": True, "vel": 58},
        },
        "reason": "seed head-nod — dusty 78bpm two-chord loop, swung hats, lazy bass",
        "rethink_in_bars": 8,
    },
}


_EOF = "\x00eof"  # sentinel: stdin closed (terminal gone / piped input exhausted)


def _intent_reader(q: "queue.Queue[str]") -> None:
    for line in sys.stdin:
        q.put(line.strip())
    q.put(_EOF)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", default="loopMIDI", help="substring of the MIDI output port name")
    parser.add_argument("--genre", default="deep", choices=sorted(STARTER_SPECS),
                        help="starter spec / musical register")
    parser.add_argument("--bpm", type=float, default=None, help="override starter BPM")
    parser.add_argument("--key", default=None, help="override starter Camelot key")
    parser.add_argument("--bars", type=int, default=None, help="override bars per phrase")
    parser.add_argument("--phrases", type=int, default=0, help="stop after N phrases (0 = run until quit)")
    parser.add_argument("--seed", type=int, default=0, help="humanization RNG seed")
    parser.add_argument("--no-llm", action="store_true", help="loop the seed spec, no slow plane")
    parser.add_argument("--intent", default="", help="initial standing intent")
    args = parser.parse_args()

    load_dotenv()

    starter = dict(STARTER_SPECS[args.genre])
    if args.bpm:
        starter["bpm"] = args.bpm
    if args.key:
        starter["key"] = args.key
    if args.bars:
        starter["for_bars"] = starter["rethink_in_bars"] = args.bars
    spec = PatternSpec.from_dict(starter)

    port = open_output(args.port)
    print(f"[spike] MIDI out: {port.name}")
    mind = None if args.no_llm else Mind()
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
