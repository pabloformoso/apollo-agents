"""MidiEvent -> mido/rtmidi -> virtual MIDI port (A-4).

The ONLY module in the package that touches the optional `synth` deps
(mido + python-rtmidi). Import is guarded: everything upstream stays
importable and testable without them.

The live path is a local virtual port (loopMIDI on Windows) with an
external synth listening — the Archaeopteryx model. What makes sound is
swappable and lives outside our code.
"""

from __future__ import annotations

from .clock import Clock
from .interpreter import MidiEvent

_INSTALL_HINT = (
    "generative engine not installed — MIDI output needs the optional synth "
    "deps: run `uv sync --group synth` (and install loopMIDI + a synth on Windows)"
)


def _mido():
    try:
        import mido
        return mido
    except ImportError as exc:  # pragma: no cover - exercised only without the group
        raise RuntimeError(_INSTALL_HINT) from exc


def list_ports() -> list[str]:
    return list(_mido().get_output_names())


def open_output(substring: str = "loopMIDI"):
    """Open the first output port whose name contains `substring` (case-insensitive)."""
    mido = _mido()
    names = mido.get_output_names()
    if not names:
        raise RuntimeError("no MIDI output ports found — is loopMIDI running?")
    for name in names:
        if substring.lower() in name.lower():
            return mido.open_output(name)
    raise RuntimeError(f"no MIDI port matching {substring!r}; available: {names}")


def event_to_message(ev: MidiEvent):
    """MidiEvent -> mido.Message. Pure conversion, unit-testable."""
    mido = _mido()
    if ev.kind == "on":
        return mido.Message("note_on", channel=ev.channel, note=ev.note, velocity=ev.velocity)
    if ev.kind == "off":
        return mido.Message("note_off", channel=ev.channel, note=ev.note, velocity=0)
    if ev.kind == "cc":
        return mido.Message("control_change", channel=ev.channel, control=ev.note, value=ev.velocity)
    raise ValueError(f"unknown event kind: {ev.kind!r}")


def all_notes_off(port, channels=(0, 1, 9)) -> None:
    mido = _mido()
    for ch in channels:
        port.send(mido.Message("control_change", channel=ch, control=123, value=0))


def play_events(events: list[MidiEvent], clock: Clock, port, total_ticks: int | None = None,
                stop_event=None, controller=None) -> None:
    """Run one phrase: schedule `events` on `clock`, sending to `port`.

    Blocks for exactly `total_ticks` ticks (pass interpreter.total_ticks(spec)
    so back-to-back phrases stay on the grid; defaults to the last event).

    controller: optional callable(tick) -> list[MidiEvent], invoked every
    tick AFTER the scheduled events — the live control plane (instant CC
    ramps, mid-phrase intent handling) rides the same clock as the notes.
    """
    by_tick: dict[int, list[MidiEvent]] = {}
    for ev in events:
        by_tick.setdefault(ev.tick, []).append(ev)
    if total_ticks is None:
        total_ticks = max(by_tick) + 1 if by_tick else 0

    def on_tick(tick: int) -> None:
        for ev in by_tick.get(tick, ()):
            port.send(event_to_message(ev))
        if controller is not None:
            for ev in controller(tick):
                port.send(event_to_message(ev))

    try:
        clock.run(total_ticks, on_tick, stop_event=stop_event)
    finally:
        if stop_event is not None and stop_event.is_set():
            all_notes_off(port)
