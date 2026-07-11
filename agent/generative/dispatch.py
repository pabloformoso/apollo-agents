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


class SplitPort:
    """Port-like router: drum-channel messages go to a second port (E-2).

    Channel-split in one Surge instance covers bass (ch 1 -> Scene A) and
    pad (ch 2 -> Scene B), but anything above the split channel also lands
    in Scene B — so drums (ch 10) must leave the instance entirely. Wrap
    the two real ports in a SplitPort and hand it anywhere a port goes;
    with drum_port=None everything passes through to main (v0 behavior).
    """

    def __init__(self, main, drum_port=None, drum_channel: int = 9,
                 drum_vel_scale: float = 1.0, main_vel_scale: float = 1.0):
        # drum_vel_scale: gain staging for the drum instance. The CLI offers
        # no per-instance volume, and a dark mono percussion patch drowns
        # under a 5-voice pad — boosting note-on velocity is the one knob
        # we control end-to-end.
        self._main = main
        self._drums = drum_port
        self._drum_channel = drum_channel
        self._drum_vel_scale = drum_vel_scale
        self._main_vel_scale = main_vel_scale

    @property
    def name(self) -> str:
        if self._drums is None:
            return self._main.name
        return f"{self._main.name} + drums:{self._drums.name}"

    def send(self, msg) -> None:
        if self._drums is not None and getattr(msg, "channel", None) == self._drum_channel:
            if self._drum_vel_scale != 1.0 and msg.type == "note_on" and msg.velocity > 0:
                msg = msg.copy(velocity=max(1, min(127, int(round(msg.velocity * self._drum_vel_scale)))))
            self._drums.send(msg)
        else:
            if self._main_vel_scale != 1.0 and msg.type == "note_on" and msg.velocity > 0:
                msg = msg.copy(velocity=max(1, min(127, int(round(msg.velocity * self._main_vel_scale)))))
            self._main.send(msg)

    def close(self) -> None:
        self._main.close()
        if self._drums is not None:
            self._drums.close()


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
