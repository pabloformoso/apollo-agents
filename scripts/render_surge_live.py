"""Real-Surge capture render (#68 plan B): surge-xt-cli + WASAPI loopback.

Launches headless Surge CLI instances — one per MIDI port, each with its
own patch from the registry (melodic roles on the main port, drums on the
drum port) — plays a generative session into them, and records the sound
card's loopback. Real Surge timbre, zero GUI, zero manual setup.

    uv run python scripts/render_surge_live.py --genre lofi --phrases 2

Requirements (machine-local, not CI): surge-xt-cli.exe (portable zip ships
it; default path below or SURGE_XT_CLI env var), loopMIDI ports, the
`soundcard` package (synth group), and an audible output device — the
session PLAYS OUT LOUD while it records. Not deterministic (real-time):
this is the ear/live path; the numpy renderer remains the CI path and
surgepy (when built) the offline-deterministic one.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.generative.genres import GENRE_PACKS
from agent.generative.patches import PATCH_REGISTRY

# Candidate CLI locations, most-specific first. ProgramData is the
# machine-global copy (works from elevated/other-user terminals whose
# Path.home() is not C:\Users\pablo).
CLI_CANDIDATES = [
    Path(r"C:\ProgramData\SurgeCLI\surge-xt-cli.exe"),
    Path.home() / "AppData/Local/SurgeCLI/surge-xt-cli.exe",
    Path(r"C:\Users\pablo\AppData\Local\SurgeCLI\surge-xt-cli.exe"),
    Path(r"C:\Program Files\Surge Synth Team\Surge XT\surge-xt-cli.exe"),
]
PATCH_DIRS = [Path(r"C:\ProgramData\Surge XT\patches_factory"),
              Path(r"C:\ProgramData\Surge XT\patches_3rdparty")]


def resolve_patch_path(name: str) -> Path | None:
    for root in PATCH_DIRS:
        if root.exists():
            hits = sorted(root.rglob(f"{name}.fxp"))
            if hits:
                return hits[0]
    return None


def cli_path() -> Path:
    env = os.environ.get("SURGE_XT_CLI")
    candidates = ([Path(env)] if env else []) + CLI_CANDIDATES
    for path in candidates:
        if path.exists():
            return path
    tried = "\n  ".join(str(p) for p in candidates)
    raise SystemExit(
        f"surge-xt-cli not found. Tried:\n  {tried}\n"
        f"(Path.home() here = {Path.home()}) — set SURGE_XT_CLI to the exe; "
        "the portable Surge zip ships it."
    )


def _cli_devices(cli: Path) -> str:
    out = subprocess.run([str(cli), "-l"], capture_output=True, text=True, timeout=60)
    return out.stdout + out.stderr


def midi_index(devices: str, port_substring: str) -> str:
    for line in devices.splitlines():
        if "MIDI Device" in line and port_substring.lower() in line.lower():
            return line.split("[")[1].split("]")[0]
    raise SystemExit(f"no MIDI device matching {port_substring!r} in surge-xt-cli -l")


def audio_interface_index(devices: str, speaker_name: str) -> str | None:
    """DirectSound index (e.g. '3.1') whose name matches the capture speaker.

    The CLI and the loopback MUST point at the same endpoint — audio devices
    come and go on this machine (monitor sleep kills the DP output), and a
    mismatch records perfect silence.
    """
    for line in devices.splitlines():
        if "Output Audio Device" in line and speaker_name.lower() in line.lower():
            return line.split("[")[1].split("]")[0]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--genre", default="lofi", choices=sorted(GENRE_PACKS))
    parser.add_argument("--phrases", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--port", default="loopMIDI Port")
    parser.add_argument("--drum-port", default="loopMIDI Drums")
    parser.add_argument("--speaker", default=None, help="substring of the output device to capture")
    parser.add_argument("--drum-boost", type=float, default=1.0,
                        help="drum velocity scale (note: Drum One ignores velocity)")
    parser.add_argument("--pad-duck", type=float, default=0.55,
                        help="melodic-port velocity scale — EP/pad patches ARE velocity-"
                             "sensitive, so ducking them rebalances the mix toward drums")
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("-o", "--out", default=None)
    args = parser.parse_args()

    import numpy as np
    import soundcard as sc
    import soundfile as sf

    cli = cli_path()
    registry = PATCH_REGISTRY[args.genre]
    devices = _cli_devices(cli)
    instances = [(midi_index(devices, args.port), registry["pad"]["patch"])]
    if "drums" in registry:
        instances.append((midi_index(devices, args.drum_port), registry["drums"]["patch"]))

    speaker = (next(s for s in sc.all_speakers() if args.speaker.lower() in s.name.lower())
               if args.speaker else sc.default_speaker())
    # Pin the CLI to the SAME endpoint the loopback records — a mismatch
    # captures perfect silence.
    audio_if = audio_interface_index(devices, speaker.name)
    print(f"[audio] capture + CLI on: {speaker.name} (interface {audio_if or 'default'})")
    loopback = sc.get_microphone(speaker.name, include_loopback=True)
    out_path = args.out or f"output/quality/surge-live-{args.genre}-{args.seed}.wav"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    sr = 48000

    procs = []
    try:
        for midi_idx, patch_name in instances:
            patch = resolve_patch_path(patch_name)
            if patch is None:
                print(f"[warn] patch {patch_name!r} not found — CLI will use its default")
            # CLI11 optional-value flags require '=' syntax — space-separated
            # values are silently treated as unexpected positionals and the
            # CLI exits without playing (found the hard way).
            cmd = [str(cli), f"--midi-input={midi_idx}", "--no-stdin"]
            if audio_if:
                cmd.append(f"--audio-interface={audio_if}")
            if patch:
                cmd.append(f"--init-patch={patch}")
            procs.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            print(f"[cli] midi[{midi_idx}] <- {patch_name}")
        time.sleep(4)  # device + patch load

        spike_cmd = [sys.executable, "scripts/spike_generative.py",
                     "--genre", args.genre, "--phrases", str(args.phrases),
                     "--seed", str(args.seed), "--drum-port", args.drum_port.split()[-1],
                     "--drum-boost", str(args.drum_boost), "--pad-duck", str(args.pad_duck)]
        if not args.llm:
            spike_cmd.append("--no-llm")
        chunks = []
        with loopback.recorder(samplerate=sr) as rec:
            spike = subprocess.Popen(spike_cmd, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            while spike.poll() is None:
                chunks.append(rec.record(numframes=sr // 4))
            chunks.append(rec.record(numframes=sr))
        audio = np.concatenate(chunks)
        sf.write(out_path, audio, sr)
        print(f"[capture] {len(audio) / sr:.1f}s peak {float(np.abs(audio).max()):.3f} -> {out_path}")
        for line in (spike.stdout.read() or "").splitlines():
            if "[reason]" in line or "[phrase" in line:
                print(line)
        return 0
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
