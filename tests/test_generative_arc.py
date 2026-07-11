"""S-4 (#73): section arc — validation, position, revision, energy correlation."""

import numpy as np
import pytest

from agent.generative.arc import ArcSpec, ArcState, Section, apply_arc_to_spec
from agent.generative.genres import GENRE_PACKS
from agent.generative.quality import energy_proxy
from agent.generative.render_audio import render_wav
from agent.generative.spec import PatternSpec, SpecError
from agent.generative.state import build_state

from tests.test_generative_spec import valid_spec_dict

ARC = [
    {"name": "intro", "phrases": 2, "energy_target": 0.3, "density_target": 0.3},
    {"name": "peak", "phrases": 3, "energy_target": 0.9, "density_target": 0.9},
]


# --- validation --------------------------------------------------------------------

def test_arc_parses():
    arc = ArcSpec.from_dict(ARC)
    assert arc.total_phrases == 5
    assert arc.sections[1].name == "peak"


@pytest.mark.parametrize("bad", [
    [],                                                        # empty
    "intro",                                                   # not a list
    [{"name": "", "phrases": 2, "energy_target": 0.5, "density_target": 0.5}],
    [{"name": "a", "phrases": 0, "energy_target": 0.5, "density_target": 0.5}],
    [{"name": "a", "phrases": 2, "energy_target": 1.5, "density_target": 0.5}],
    [{"name": "a", "phrases": 2, "energy_target": 0.5}],       # missing target
    [{"name": "a", "phrases": True, "energy_target": 0.5, "density_target": 0.5}],
])
def test_bad_arc_rejected(bad):
    with pytest.raises(SpecError):
        ArcSpec.from_dict(bad)


def test_every_genre_pack_arc_validates():
    for genre, pack in GENRE_PACKS.items():
        arc = ArcSpec.from_dict(pack["arc"])
        assert arc.total_phrases >= 3, genre


# --- position / advance ---------------------------------------------------------------

def test_position_advances_across_sections():
    state = ArcState(ArcSpec.from_dict(ARC))
    names = []
    for _ in range(5):
        names.append(state.current().name)
        state.advance()
    assert names == ["intro", "intro", "peak", "peak", "peak"]


def test_arc_loops_for_endless_sessions():
    state = ArcState(ArcSpec.from_dict(ARC))
    for _ in range(5):
        state.advance()
    assert state.current().name == "intro"  # wrapped


def test_section_position_reports_within_section():
    state = ArcState(ArcSpec.from_dict(ARC))
    state.advance()
    assert state.section_position() == (2, 2)
    state.advance()
    assert state.section_position() == (1, 3)


# --- revision (reject-and-hold, FS3 parity) --------------------------------------------

def test_revision_replaces_cleanly():
    state = ArcState(ArcSpec.from_dict(ARC))
    state.advance()
    state.revise([{"name": "outro", "phrases": 2, "energy_target": 0.2, "density_target": 0.2}])
    assert state.current().name == "outro"
    assert state.phrase_index == 0


def test_malformed_revision_holds_previous_arc():
    state = ArcState(ArcSpec.from_dict(ARC))
    state.advance()
    with pytest.raises(SpecError):
        state.revise([{"name": "broken", "phrases": -1}])
    assert state.current().name == "intro"      # held
    assert state.phrase_index == 1              # position untouched


# --- prompt injection --------------------------------------------------------------------

def test_arc_lands_in_state_and_prompt():
    import json

    from agent.generative.mind import Mind

    spec = PatternSpec.from_dict(valid_spec_dict())
    arc_state = ArcState(ArcSpec.from_dict(ARC))
    state = build_state(spec, 8, "x", [], arc_state=arc_state)
    assert state["arc"]["section"] == "intro"
    assert state["arc"]["energy_target"] == 0.3

    captured = {}

    def llm(system, user):
        captured["user"] = user
        return json.dumps(valid_spec_dict())

    Mind(llm=llm).next_spec(state, "x")
    assert '"section": "intro"' in captured["user"]
    assert "energy_target" in captured["user"]


# --- energy correlation (scripted, no LLM) --------------------------------------------------

def _spearman(a, b):
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    return float(np.corrcoef(ra, rb)[0, 1])


def scripted_specs():
    """6-phrase session with monotonically rising density/energy targets."""
    targets = [0.15, 0.3, 0.45, 0.6, 0.8, 1.0]
    specs = []
    base = valid_spec_dict(for_bars=2)
    base["roles"]["snare"] = {"pattern": "backbeat", "vel": 85}
    for t in targets:
        section = Section(name="s", phrases=1, energy_target=t, density_target=t)
        specs.append(PatternSpec.from_dict(apply_arc_to_spec(base, section)))
    return targets, specs


def test_energy_correlates_with_arc_targets():
    targets, specs = scripted_specs()
    energies = [energy_proxy(s, seed=4) for s in specs]
    assert _spearman(targets, energies) >= 0.6


def test_arc_session_render_is_deterministic():
    _, specs = scripted_specs()
    import soundfile as sf
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        a, b = os.path.join(td, "a.wav"), os.path.join(td, "b.wav")
        render_wav(specs, a, seed=2)
        render_wav(specs, b, seed=2)
        da, _ = sf.read(a)
        db, _ = sf.read(b)
        assert np.array_equal(da, db)


def test_apply_arc_maps_density_to_drums_and_energy_to_velocities():
    section = Section(name="s", phrases=1, energy_target=1.0, density_target=0.4)
    src = valid_spec_dict()
    out = apply_arc_to_spec(src, section)
    assert out["roles"]["kick"]["density"] == 0.4
    assert out["roles"]["hats"]["density"] == 0.4
    assert "density" not in out["roles"]["bass"]
    assert "density" not in out["roles"]["pad"]
    # energy scales every role's velocity (1.1x at target 1.0), clamped to MIDI
    assert out["roles"]["pad"]["vel"] == min(127, round(src["roles"]["pad"]["vel"] * 1.1))
    assert out["roles"]["kick"]["vel"] > src["roles"]["kick"]["vel"]
    # source dict untouched (pure transform)
    assert "density" not in src["roles"]["kick"]
