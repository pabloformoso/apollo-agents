"""E-2: patch registry completeness + SplitPort drum routing."""

import pytest

mido = pytest.importorskip("mido")

from agent.generative.dispatch import SplitPort, all_notes_off, event_to_message
from agent.generative.genres import GENRE_PACKS
from agent.generative.interpreter import DRUM_CHANNEL, MidiEvent
from agent.generative.patches import PATCH_REGISTRY, ROLE_ROUTING, expected_setup, get_patch


class FakePort:
    def __init__(self, name="fake"):
        self.name = name
        self.sent = []
        self.closed = False

    def send(self, msg):
        self.sent.append(msg)

    def close(self):
        self.closed = True


# --- registry -------------------------------------------------------------------

def test_registry_covers_every_genre_pack():
    assert set(PATCH_REGISTRY) == set(GENRE_PACKS)


def test_registry_covers_the_roles_each_starter_uses():
    for genre, pack in GENRE_PACKS.items():
        roles = set(pack["starter"]["roles"])
        if roles & {"kick", "snare", "hats"}:
            assert get_patch(genre, "drums"), f"{genre} starter has drums but no drum patch"
        for role in roles & {"bass", "pad"}:
            assert get_patch(genre, role), f"{genre} starter uses {role} but registry lacks it"


def test_registry_entries_are_complete():
    for genre, entries in PATCH_REGISTRY.items():
        for role, info in entries.items():
            assert role in ROLE_ROUTING, f"{genre}.{role} has no routing"
            for field in ("patch", "location", "character"):
                assert info.get(field), f"{genre}.{role} missing {field}"


def test_expected_setup_prints_patches_and_channels():
    text = expected_setup("ambient")
    assert "Deep Space 1" in text
    assert "channel 2" in text
    assert "docs/surge-multitimbral-setup.md" in text


def test_expected_setup_unknown_genre():
    assert "no patch registry" in expected_setup("polka")


# --- SplitPort --------------------------------------------------------------------

def test_split_port_routes_drums_away():
    main, drums = FakePort("main"), FakePort("drums")
    port = SplitPort(main, drums)
    port.send(event_to_message(MidiEvent(0, "on", DRUM_CHANNEL, 36, 100)))
    port.send(event_to_message(MidiEvent(0, "on", 0, 33, 90)))
    port.send(event_to_message(MidiEvent(0, "cc", 0, 41, 64)))
    assert [m.channel for m in drums.sent] == [DRUM_CHANNEL]
    assert [m.channel for m in main.sent] == [0, 0]


def test_split_port_without_drum_port_passes_through():
    main = FakePort("main")
    port = SplitPort(main)
    port.send(event_to_message(MidiEvent(0, "on", DRUM_CHANNEL, 36, 100)))
    assert len(main.sent) == 1
    assert port.name == "main"


def test_split_port_all_notes_off_reaches_both():
    main, drums = FakePort(), FakePort()
    all_notes_off(SplitPort(main, drums))  # channels (0, 1, 9)
    assert [m.channel for m in drums.sent] == [9]
    assert sorted(m.channel for m in main.sent) == [0, 1]


def test_split_port_close_closes_both():
    main, drums = FakePort(), FakePort()
    SplitPort(main, drums).close()
    assert main.closed and drums.closed


def test_split_port_name_mentions_both():
    assert "drums:" in SplitPort(FakePort("a"), FakePort("b")).name
