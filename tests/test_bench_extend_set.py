"""Unit tests for the live-conditions ``extend_set`` bench.

`scripts/bench_extend_set.py` exists to answer a question the smoke gate
cannot: does a model actually append a track when the real live prompt, the
real ten tools and the real catalog are in play? Its verdict decides which
model drives a 24/7 stream, so the classifier must not credit a model for
merely *claiming* it appended — only the engine's recorder counts.

`scripts/` is not an importable package, so the module is loaded from its
path (same pattern as tests/test_smoke_local_llm.py). Unlike the smoke
module, this one defines a ``@dataclass``, and ``dataclasses`` resolves a
class's module through ``sys.modules`` — so the module must be registered
there BEFORE ``exec_module`` or the decorator dies on a ``None`` lookup.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bench_extend_set.py"
_spec = importlib.util.spec_from_file_location("bench_extend_set", _SCRIPT)
assert _spec is not None and _spec.loader is not None
bench = importlib.util.module_from_spec(_spec)
sys.modules["bench_extend_set"] = bench
_spec.loader.exec_module(bench)


# ─── classify_outcome ──────────────────────────────────────────────────

def test_append_beats_every_other_signal():
    """Ground truth wins: the engine recorded it, so it is an append."""
    assert bench.classify_outcome(["pick_next_track", "extend_set"], True) == bench.APPENDED


def test_append_credited_even_without_a_recorded_tool_name():
    """The recorder is the witness, not the call log."""
    assert bench.classify_outcome([], True) == bench.APPENDED


def test_extend_set_without_append_is_rejected():
    """The live failure where the model invents a plausible-looking id."""
    assert bench.classify_outcome(["pick_next_track", "extend_set"], False) == bench.REJECTED


def test_pick_without_extend_is_picked_only():
    assert bench.classify_outcome(["pick_next_track"], False) == bench.PICKED_ONLY


def test_unrelated_tool_is_other_tool():
    assert bench.classify_outcome(["emit_chat"], False) == bench.OTHER_TOOL


def test_no_tool_calls_is_silent():
    """Prose or an empty string — the exact 0-of-17 live symptom."""
    assert bench.classify_outcome([], False) == bench.SILENT


def test_rejected_outranks_picked_only():
    """Order matters: a hallucinated id is a different bug from never trying."""
    calls = ["pick_next_track", "extend_set", "pick_next_track"]
    assert bench.classify_outcome(calls, False) == bench.REJECTED


# ─── summarize / append_rate ───────────────────────────────────────────

def test_summarize_reports_every_bucket_including_zeros():
    counts = bench.summarize([bench.APPENDED, bench.SILENT, bench.APPENDED])
    assert counts == {
        bench.APPENDED: 2,
        bench.REJECTED: 0,
        bench.PICKED_ONLY: 0,
        bench.OTHER_TOOL: 0,
        bench.SILENT: 1,
    }


def test_summarize_of_nothing_is_all_zeros():
    assert set(bench.summarize([]).values()) == {0}


def test_append_rate_counts_only_appends():
    outcomes = [bench.APPENDED, bench.REJECTED, bench.PICKED_ONLY, bench.APPENDED]
    assert bench.append_rate(outcomes) == 0.5


def test_append_rate_of_empty_is_zero_not_a_crash():
    assert bench.append_rate([]) == 0.0


def test_append_rate_all_silent_is_zero():
    assert bench.append_rate([bench.SILENT] * 5) == 0.0


# ─── RecordingEngine ───────────────────────────────────────────────────

def test_engine_records_append_and_reports_position():
    engine = bench.RecordingEngine([{"id": "a", "display_name": "One"}])
    out = engine.append_track({"id": "b", "display_name": "Two"})
    assert engine.appended == [{"id": "b", "display_name": "Two"}]
    assert "Two" in out and "2" in out


def test_engine_starts_with_nothing_appended():
    assert bench.RecordingEngine([{"id": "a"}]).appended == []


def test_engine_does_not_mutate_the_caller_playlist():
    original = [{"id": "a"}]
    engine = bench.RecordingEngine(original)
    engine.append_track({"id": "b"})
    assert original == [{"id": "a"}]


def test_engine_state_exposes_the_fields_get_live_state_reads():
    engine = bench.RecordingEngine([{"id": "a", "display_name": "One"}])
    state = engine.get_state()
    for key in (
        "state", "position_sec", "current_track",
        "next_track", "seconds_to_crossfade", "playlist_remaining",
    ):
        assert key in state


def test_engine_state_on_empty_playlist_does_not_crash():
    assert bench.RecordingEngine([]).get_state()["current_track"] == {}


# ─── pick_scenario_tracks ──────────────────────────────────────────────

def _track(tid, genre="aural", bpm=52.0, duration=300.0):
    return {
        "id": tid,
        "display_name": tid,
        "genre_folder": genre,
        "bpm": bpm,
        "duration_sec": duration,
        "camelot_key": "8A",
    }


def test_picks_only_the_requested_genre():
    catalog = [_track("a", genre="lofi"), _track("b"), _track("c")]
    got = bench.pick_scenario_tracks(catalog, "aural")
    assert [t["id"] for t in got] == ["b", "c"]


def test_genre_match_is_case_insensitive():
    catalog = [_track("a", genre="Aural")]
    assert len(bench.pick_scenario_tracks(catalog, "AURAL")) == 1


def test_falls_back_to_the_genre_field_when_no_folder():
    catalog = [{"id": "a", "genre": "aural", "bpm": 52, "duration_sec": 300}]
    assert len(bench.pick_scenario_tracks(catalog, "aural")) == 1


def test_skips_tracks_without_a_numeric_bpm():
    """The turn text quotes the BPM and the pick window is built from it."""
    catalog = [_track("a", bpm=None), _track("b")]
    assert [t["id"] for t in bench.pick_scenario_tracks(catalog, "aural")] == ["b"]


def test_skips_session_ineligible_short_tracks():
    """Mirrors the v3.9.1 floor — a sub-120s track never reaches a session."""
    catalog = [_track("a", duration=60), _track("b")]
    assert [t["id"] for t in bench.pick_scenario_tracks(catalog, "aural")] == ["b"]


def test_stops_at_n():
    catalog = [_track(str(i)) for i in range(10)]
    assert len(bench.pick_scenario_tracks(catalog, "aural", n=3)) == 3


def test_no_match_returns_empty():
    assert bench.pick_scenario_tracks([_track("a", genre="techno")], "aural") == []


# ─── build_turn_text ───────────────────────────────────────────────────

def test_turn_text_carries_the_poke_and_the_instruction():
    playlist = [_track("a")]
    text = bench.build_turn_text(playlist[0], playlist)
    assert "PLAYLIST_RUNNING_LOW" in text
    assert "extend_set" in text
    assert "Current state" in text


def test_turn_text_names_the_current_track():
    current = _track("soft-focus")
    assert "soft-focus" in bench.build_turn_text(current, [current])


# ─── _median ───────────────────────────────────────────────────────────

def test_median_odd_even_and_empty():
    assert bench._median([3.0, 1.0, 2.0]) == 2.0
    assert bench._median([1.0, 2.0, 3.0, 4.0]) == 2.5
    assert bench._median([]) == 0.0


# ─── format_report ─────────────────────────────────────────────────────

def _trial(outcome, seconds=1.0, tools=None, shim=False):
    return bench.Trial(
        outcome=outcome, seconds=seconds,
        tools_called=tools or [], shim_used=shim,
    )


def test_report_says_pass_at_or_above_the_bar():
    trials = [_trial(bench.APPENDED)] * 7 + [_trial(bench.SILENT)] * 3
    assert "PASS" in bench.format_report("m", trials)


def test_report_says_fail_below_the_bar():
    trials = [_trial(bench.APPENDED)] * 6 + [_trial(bench.SILENT)] * 4
    report = bench.format_report("m", trials)
    assert "FAIL" in report and "60%" in report


def test_report_mentions_the_shim_only_when_it_fired():
    quiet = bench.format_report("m", [_trial(bench.APPENDED)])
    assert "llm-shim" not in quiet
    noisy = bench.format_report("m", [_trial(bench.APPENDED, shim=True)])
    assert "llm-shim" in noisy


def test_report_survives_zero_appends():
    """No appends must not divide by zero in the grace-window line."""
    assert "0%" in bench.format_report("m", [_trial(bench.SILENT)] * 3)


# ─── check_endpoint ────────────────────────────────────────────────────

class _ModelsAPI:
    def __init__(self, ids=(), error=None):
        self._ids = ids
        self._error = error

    def list(self):
        if self._error:
            raise self._error
        data = [type("M", (), {"id": i})() for i in self._ids]
        return type("L", (), {"data": data})()


def _probe(ids=(), error=None):
    return type("C", (), {"models": _ModelsAPI(ids, error)})()


def test_preflight_passes_when_every_model_is_served():
    ok, why = bench.check_endpoint(_probe(["a", "b"]), ["a"])
    assert ok is True and why == ""


def test_preflight_fails_on_an_unreachable_endpoint():
    """The 2026-08-14 miss: a stale base URL burned 21 minutes of timeouts
    and reported them as a clean 0% append rate."""
    ok, why = bench.check_endpoint(_probe(error=ConnectionError("no route")), ["a"])
    assert ok is False
    assert "unreachable" in why and "no route" in why


def test_preflight_fails_when_a_model_is_not_served():
    ok, why = bench.check_endpoint(_probe(["a"]), ["a", "typo-model"])
    assert ok is False
    assert "typo-model" in why


def test_preflight_lists_what_is_available_when_it_fails():
    """So the operator can fix the id without a second round-trip."""
    _, why = bench.check_endpoint(_probe(["real-a", "real-b"]), ["wrong"])
    assert "real-a" in why and "real-b" in why


def test_preflight_on_an_empty_server_fails():
    ok, _ = bench.check_endpoint(_probe([]), ["a"])
    assert ok is False


# ─── run_trial (LLM + tools injected) ──────────────────────────────────

class _FakeMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeCall:
    def __init__(self, cid, name, arguments):
        self.id = cid
        self.function = type("F", (), {"name": name, "arguments": arguments})()


class _FakeClient:
    """Replays a scripted list of assistant messages, one per turn."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls += 1
                outer.last_kwargs = kwargs
                reply = outer._replies.pop(0) if outer._replies else _FakeMessage("done")
                if isinstance(reply, Exception):
                    raise reply
                return type("R", (), {"choices": [type("C", (), {"message": reply})()]})()

        self.chat = type("Chat", (), {"completions": _Completions()})()


@pytest.fixture
def fake_tools():
    """Stand-ins for pick_next_track / extend_set with the real signatures."""
    def pick_next_track(bpm_min, bpm_max, context_variables, **_):
        return "| id | display_name |\n|---|---|\n| real-id-abc | Soft Focus |"

    def extend_set(track_id, context_variables, **_):
        if track_id != "real-id-abc":
            return f"Track ID '{track_id}' is NOT in the catalog."
        return context_variables["_engine"].append_track(
            {"id": track_id, "display_name": "Soft Focus"}
        )

    def emit_chat(text, context_variables, **_):
        return "published"

    return {
        "pick_next_track": pick_next_track,
        "extend_set": extend_set,
        "emit_chat": emit_chat,
    }


def _run(client, fake_tools):
    return bench.run_trial(
        client, "m", "aural", [_track("a")], "turn text",
        schemas=[], tool_index=fake_tools, temperature=0.0,
    )


def test_two_step_pick_then_extend_is_an_append(fake_tools):
    client = _FakeClient([
        _FakeMessage(tool_calls=[_FakeCall("1", "pick_next_track", '{"bpm_min":48,"bpm_max":56}')]),
        _FakeMessage(tool_calls=[_FakeCall("2", "extend_set", '{"track_id":"real-id-abc"}')]),
    ])
    trial = _run(client, fake_tools)
    assert trial.outcome == bench.APPENDED
    assert trial.tools_called == ["pick_next_track", "extend_set"]
    assert trial.detail == "Soft Focus"


def test_loop_stops_as_soon_as_a_track_is_appended(fake_tools):
    """No wasted turns once the goal is reached."""
    client = _FakeClient([
        _FakeMessage(tool_calls=[_FakeCall("1", "extend_set", '{"track_id":"real-id-abc"}')]),
        _FakeMessage(tool_calls=[_FakeCall("2", "emit_chat", '{"text":"hi"}')]),
    ])
    trial = _run(client, fake_tools)
    assert trial.outcome == bench.APPENDED
    assert client.calls == 1


def test_hallucinated_id_is_rejected_not_appended(fake_tools):
    client = _FakeClient([
        _FakeMessage(tool_calls=[_FakeCall("1", "extend_set", '{"track_id":"soft-focus"}')]),
        _FakeMessage("nothing more"),
    ])
    trial = _run(client, fake_tools)
    assert trial.outcome == bench.REJECTED
    assert "NOT in the catalog" in trial.detail


def test_prose_only_answer_is_silent(fake_tools):
    client = _FakeClient([_FakeMessage("Sure, I'll keep the set going!")])
    trial = _run(client, fake_tools)
    assert trial.outcome == bench.SILENT
    assert trial.tools_called == []
    assert "keep the set going" in trial.detail


def test_empty_response_is_silent_with_a_readable_detail(fake_tools):
    trial = _run(_FakeClient([_FakeMessage("")]), fake_tools)
    assert trial.outcome == bench.SILENT
    assert trial.detail == "(empty response)"


def test_textual_tool_call_is_recovered_by_the_shim(fake_tools):
    """The live loop applies this shim, so the bench must too."""
    client = _FakeClient([
        _FakeMessage('extend_set(track_id="real-id-abc")'),
        _FakeMessage("done"),
    ])
    trial = _run(client, fake_tools)
    assert trial.shim_used is True
    assert trial.outcome == bench.APPENDED


def test_api_error_is_reported_not_raised(fake_tools):
    trial = _run(_FakeClient([RuntimeError("connection refused")]), fake_tools)
    assert trial.outcome == bench.SILENT
    assert "connection refused" in trial.detail


def test_unparseable_arguments_do_not_crash_the_trial(fake_tools):
    client = _FakeClient([
        _FakeMessage(tool_calls=[_FakeCall("1", "extend_set", "{not json")]),
        _FakeMessage("gave up"),
    ])
    trial = _run(client, fake_tools)
    assert trial.outcome == bench.REJECTED
    assert trial.tools_called == ["extend_set"]


def test_trial_is_capped_at_the_live_max_turns(fake_tools):
    """A model that loops forever must not hang the bench."""
    client = _FakeClient([
        _FakeMessage(tool_calls=[_FakeCall(str(i), "pick_next_track", "{}")])
        for i in range(20)
    ])
    trial = _run(client, fake_tools)
    assert client.calls == bench.MAX_TURNS
    assert trial.outcome == bench.PICKED_ONLY


def test_tools_are_offered_to_the_model_every_turn(fake_tools):
    client = _FakeClient([_FakeMessage("prose")])
    bench.run_trial(
        client, "m", "aural", [_track("a")], "turn text",
        schemas=[{"type": "function"}], tool_index=fake_tools, temperature=0.3,
    )
    assert client.last_kwargs["tools"] == [{"type": "function"}]
    assert client.last_kwargs["temperature"] == 0.3


def test_the_genre_fence_reaches_the_tools(fake_tools):
    """ctx['genre'] is what makes the real tools reject out-of-genre picks."""
    seen = {}

    def spy(bpm_min, bpm_max, context_variables, **_):
        seen.update(context_variables)
        return "table"

    tools = dict(fake_tools, pick_next_track=spy)
    client = _FakeClient([
        _FakeMessage(tool_calls=[_FakeCall("1", "pick_next_track", '{"bpm_min":1,"bpm_max":2}')]),
        _FakeMessage("done"),
    ])
    _run(client, tools)
    assert seen["genre"] == "aural"
    assert isinstance(seen["_engine"], bench.RecordingEngine)
