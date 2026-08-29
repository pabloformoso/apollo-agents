"""Unit tests for the Strudel-mind bench.

`scripts/bench_strudel_mind.py` is the gate that decides whether a model is
allowed to write code for a live set, so the parts that turn raw trials into a
verdict — the preflight refusal, the failure buckets, the JSONL, the rates and
percentiles — are tested without a model, an endpoint or Node anywhere near
them.

`scripts/` is not an importable package, so the module is loaded from its path
(same pattern as tests/test_bench_extend_set.py). It defines a ``@dataclass``,
and ``dataclasses`` resolves a class's module through ``sys.modules`` — so the
module must be registered there BEFORE ``exec_module`` or the decorator dies on
a ``None`` lookup.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.generative.strudel_mind import StrudelCode, StrudelMindError

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bench_strudel_mind.py"
_spec = importlib.util.spec_from_file_location("bench_strudel_mind", _SCRIPT)
assert _spec is not None and _spec.loader is not None
bench = importlib.util.module_from_spec(_spec)
sys.modules["bench_strudel_mind"] = bench
_spec.loader.exec_module(bench)


# ─── trial plan ────────────────────────────────────────────────────────

def test_plan_alternates_generate_and_mutate():
    modes = [mode for mode, _ in bench.plan_trials(6)]
    assert modes == [bench.GENERATE, bench.MUTATE] * 3


def test_plan_rotates_the_intent_every_pair():
    """Each intent is seen once per mode — otherwise 'darker' would only ever
    be a generate and the two modes could not be compared."""
    plan = bench.plan_trials(8)
    assert [intent for _, intent in plan] == [i for i in bench.INTENTS for _ in (0, 1)]
    assert plan[0] == (bench.GENERATE, "darker")
    assert plan[1] == (bench.MUTATE, "darker")


def test_plan_wraps_past_the_rotation():
    plan = bench.plan_trials(10)
    assert len(plan) == 10
    assert plan[8] == (bench.GENERATE, "darker")


def test_plan_of_nothing_is_empty():
    assert bench.plan_trials(0) == [] and bench.plan_trials(-3) == []


# ─── classify_error ────────────────────────────────────────────────────

def test_syntax_failure_is_invalid_js():
    msg = "slow plane failed twice — holding current code (1st: SyntaxError: x; 2nd: y)"
    assert bench.classify_error(msg) == bench.INVALID_JS


def test_no_events_has_its_own_bucket():
    """A pattern that parses but emits nothing is a different bug from one
    that does not parse."""
    assert bench.classify_error("no events in 4 cycles") == bench.NO_EVENTS
    assert bench.classify_error("pattern produced no events") == bench.NO_EVENTS


def test_palette_violation_is_bucketed():
    assert bench.classify_error("sound 'clave' is not in the palette") == bench.PALETTE
    assert bench.classify_error("unknown sound: piano") == bench.PALETTE


def test_token_screen_is_bucketed_even_if_the_wording_changes():
    assert bench.classify_error("forbidden token 'import'") == bench.TOKEN_SCREEN
    assert bench.classify_error("blocked token: process") == bench.TOKEN_SCREEN
    # Unknown wording still gets caught by the token itself.
    assert bench.classify_error("Cannot use import statement here") == bench.TOKEN_SCREEN


def test_timeout_text_beats_every_other_signature():
    assert bench.classify_error("validator timed out after 30s") == bench.TIMEOUT


def test_unrecognised_failure_is_mind_error_not_a_silent_invalid():
    assert bench.classify_error("node was not found on PATH") == bench.MIND_ERROR
    assert bench.classify_error("") == bench.MIND_ERROR


def test_first_signature_in_a_double_failure_wins():
    both = "failed twice (1st: no events in 4 cycles; 2nd: SyntaxError: bad)"
    assert bench.classify_error(both) == bench.NO_EVENTS


def test_looks_like_timeout_reads_the_exception_type():
    class APITimeoutError(Exception):
        pass

    assert bench.looks_like_timeout(APITimeoutError("request took too long"))
    assert bench.looks_like_timeout(RuntimeError("connection timed out"))
    assert not bench.looks_like_timeout(ValueError("nope"))


# ─── run_trial ─────────────────────────────────────────────────────────

class _Mind:
    """Stand-in for StrudelMind: returns or raises whatever the test wants."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.states: list[dict] = []
        self.intents: list[str] = []

    def next_code(self, state, intent):
        self.states.append(state)
        self.intents.append(intent)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def test_valid_code_is_an_ok_trial_carrying_reason_and_stats():
    mind = _Mind(StrudelCode(code="stack()", reason="opened the filter",
                             stats={"events": 42}))
    trial = bench.run_trial(mind, "m", bench.GENERATE, "darker")
    assert trial.verdict == bench.OK
    assert trial.reason == "opened the filter"
    assert trial.stats == {"events": 42}
    assert trial.code == "stack()"
    assert trial.error == ""
    assert trial.latency_s >= 0


def test_mind_error_is_bucketed_by_its_message():
    mind = _Mind(StrudelMindError("failed twice (1st: no events; 2nd: no events)"))
    trial = bench.run_trial(mind, "m", bench.MUTATE, "build to a peak")
    assert trial.verdict == bench.NO_EVENTS
    assert "no events" in trial.error


def test_transport_timeout_is_a_timeout_trial_not_a_model_failure():
    class APITimeoutError(Exception):
        pass

    trial = bench.run_trial(_Mind(APITimeoutError("timed out")), "m",
                            bench.GENERATE, "darker")
    assert trial.verdict == bench.TIMEOUT


def test_any_other_exception_is_reported_not_raised():
    """A bench reports, never crashes — one broken trial must not kill the run."""
    trial = bench.run_trial(_Mind(ValueError("boom")), "m", bench.GENERATE, "darker")
    assert trial.verdict == bench.MIND_ERROR
    assert "ValueError: boom" in trial.error


def test_generate_mode_starts_from_an_empty_page():
    mind = _Mind(StrudelCode(code="stack()"))
    bench.run_trial(mind, "m", bench.GENERATE, "darker")
    assert mind.states[0]["current_code"] == ""


def test_mutate_mode_hands_the_mind_the_seed_pattern():
    mind = _Mind(StrudelCode(code="stack()"))
    bench.run_trial(mind, "m", bench.MUTATE, "more swing")
    assert mind.states[0]["current_code"] == bench.SEED_CODE
    assert mind.intents == ["more swing"]


def test_the_seed_pattern_obeys_the_validator_contract():
    """The seed is fed back to the model verbatim; the committed .js module
    could not be used as-is because its `import` lines are screened out."""
    for banned in ("import ", "require(", "setcps"):
        assert banned not in bench.SEED_CODE


# ─── stats ─────────────────────────────────────────────────────────────

def test_summarize_reports_every_bucket_including_zeros():
    counts = bench.summarize([bench.OK, bench.OK, bench.PALETTE])
    assert counts[bench.OK] == 2 and counts[bench.PALETTE] == 1
    assert counts[bench.TIMEOUT] == 0 and counts[bench.NO_EVENTS] == 0


def test_valid_rate_counts_only_ok():
    verdicts = [bench.OK, bench.INVALID_JS, bench.OK, bench.TIMEOUT]
    assert bench.valid_rate(verdicts) == 0.5


def test_valid_rate_of_nothing_is_zero_not_a_crash():
    assert bench.valid_rate([]) == 0.0


def test_percentile_interpolates():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert bench.percentile(values, 50) == 3.0
    assert bench.percentile(values, 95) == pytest.approx(4.8)
    assert bench.percentile(values, 0) == 1.0


def test_percentile_edge_cases():
    assert bench.percentile([], 50) == 0.0
    assert bench.percentile([7.5], 95) == 7.5


def test_percentile_does_not_assume_sorted_input():
    assert bench.percentile([5.0, 1.0, 3.0], 50) == 3.0


def test_slug_makes_a_model_id_filename_safe():
    assert bench.slug("qwen/qwen3.6-27b") == "qwen-qwen3.6-27b"


# ─── JSONL ─────────────────────────────────────────────────────────────

def _trial(**kw):
    base = dict(model="m", mode=bench.GENERATE, intent="darker",
                latency_s=1.5, verdict=bench.OK)
    base.update(kw)
    return bench.Trial(**base)


def test_each_trial_is_one_json_line(tmp_path):
    path = tmp_path / "run.jsonl"
    bench.append_trial(path, _trial(reason="a"))
    bench.append_trial(path, _trial(verdict=bench.PALETTE, error="bad sound"))

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first, second = (json.loads(line) for line in lines)
    assert first["verdict"] == bench.OK and first["reason"] == "a"
    assert second["error"] == "bad sound"


def test_the_jsonl_carries_every_field_the_report_needs(tmp_path):
    path = tmp_path / "run.jsonl"
    bench.append_trial(path, _trial(code="stack()", stats={"events": 4}))
    row = json.loads(path.read_text(encoding="utf-8").strip())
    for key in ("model", "mode", "intent", "latency_s", "verdict", "error",
                "reason", "code", "stats"):
        assert key in row


def test_the_out_directory_is_created_on_demand(tmp_path):
    path = tmp_path / "nested" / "deeper" / "run.jsonl"
    bench.append_trial(path, _trial())
    assert path.exists()


def test_trial_path_is_stamped_and_per_model(tmp_path):
    path = bench.trial_path(tmp_path, "qwen/qwen3.6-27b", "20260829T101500")
    assert path.name == "20260829T101500-qwen-qwen3.6-27b.jsonl"
    assert path.parent == Path(tmp_path)


# ─── report ────────────────────────────────────────────────────────────

def _fixed_trials():
    return [
        _trial(latency_s=2.0, reason="four on the floor"),
        _trial(latency_s=4.0, verdict=bench.INVALID_JS, error="SyntaxError: x"),
        _trial(latency_s=6.0, reason="opened the filter"),
        _trial(latency_s=8.0, verdict=bench.NO_EVENTS, error="no events"),
    ]


def test_report_states_the_rate_and_the_breakdown():
    text = bench.format_report("qwen/qwen3.6-27b", _fixed_trials(), pass_rate=0.7)
    assert "valid rate    50%  (2/4)" in text
    assert "FAIL" in text and "bar 70%" in text
    assert "ok=2" in text and "invalid_js=1" in text and "no_events=1" in text
    assert "timeout" not in text.split("breakdown")[1].split("\n")[0]  # zeros hidden


def test_report_separates_all_latency_from_valid_only_latency():
    """A model that is fast only when it fails is not a fast model."""
    text = bench.format_report("m", _fixed_trials())
    all_line = next(ln for ln in text.splitlines() if "latency all" in ln)
    valid_line = next(ln for ln in text.splitlines() if "latency valid" in ln)
    assert "p50 5.0s" in all_line and "(n=4)" in all_line
    assert "p50 4.0s" in valid_line and "(n=2)" in valid_line


def test_report_shows_at_most_three_sample_reasons():
    trials = [_trial(reason=f"reason {i}") for i in range(5)]
    text = bench.format_report("m", trials)
    assert text.count("    - reason") == 3
    assert "PASS" in text


def test_report_survives_a_run_where_everything_failed():
    trials = [_trial(verdict=bench.TIMEOUT, error="timed out") for _ in range(3)]
    text = bench.format_report("m", trials)
    assert "valid rate    0%" in text
    assert "latency valid p50 0.0s" in text and "(n=0)" in text


# ─── preflight ─────────────────────────────────────────────────────────

class _ModelsAPI:
    def __init__(self, ids=(), error=None):
        self._ids, self._error = ids, error

    def list(self):
        if self._error:
            raise self._error
        return SimpleNamespace(data=[SimpleNamespace(id=i) for i in self._ids])


def _probe(ids=(), error=None):
    return SimpleNamespace(models=_ModelsAPI(ids, error))


def test_preflight_passes_when_every_model_is_served():
    ok, why = bench.check_endpoint(_probe(["a", "b"]), ["a"])
    assert ok is True and why == ""


def test_preflight_refuses_a_dead_endpoint():
    """A dead host and a mute model land in the same bucket — refuse up front."""
    ok, why = bench.check_endpoint(_probe(error=ConnectionError("no route")), ["a"])
    assert ok is False and "unreachable" in why and "no route" in why


def test_preflight_refuses_an_unserved_model_and_lists_what_is_there():
    ok, why = bench.check_endpoint(_probe(["real-a"]), ["typo-model"])
    assert ok is False and "typo-model" in why and "real-a" in why


# ─── make_llm ──────────────────────────────────────────────────────────

def test_make_llm_sends_the_same_shape_the_live_path_sends():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="stack()"))]
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    out = bench.make_llm(client, "qwen/qwen3.6-27b", 4096)("SYS", "USR")

    assert out == "stack()"
    assert captured["model"] == "qwen/qwen3.6-27b"
    assert captured["max_tokens"] == 4096
    assert captured["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USR"},
    ]


def test_make_llm_turns_a_null_completion_into_an_empty_string():
    create = lambda **kw: SimpleNamespace(  # noqa: E731
        choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    assert bench.make_llm(client, "m", 10)("s", "u") == ""


# ─── main ──────────────────────────────────────────────────────────────

def _fake_openai(monkeypatch):
    module = types.ModuleType("openai")
    module.OpenAI = lambda **kwargs: SimpleNamespace(models=_ModelsAPI([]), chat=None)
    monkeypatch.setitem(sys.modules, "openai", module)


def test_main_refuses_when_the_validator_is_not_installed(monkeypatch, capsys):
    """Without the validator EVERY trial fails identically, which reads like a
    model verdict and is not one."""
    def missing():
        raise StrudelMindError("node_modules is missing — run `npm install` in ...")

    monkeypatch.setattr(bench.strudel_mind, "require_validator", missing)
    assert bench.main(["--models", "m"]) == 1
    out = capsys.readouterr().out
    assert "PREFLIGHT FAILED" in out and "npm install" in out


def test_main_refuses_a_dead_endpoint_before_benching(monkeypatch, capsys):
    monkeypatch.setattr(bench.strudel_mind, "require_validator", lambda: None)
    monkeypatch.setattr(bench, "check_endpoint", lambda c, m: (False, "endpoint unreachable: boom"))
    _fake_openai(monkeypatch)

    assert bench.main(["--models", "m", "--base-url", "http://dead:1/v1"]) == 1
    out = capsys.readouterr().out
    assert "PREFLIGHT FAILED" in out and "unreachable" in out
    assert "Nothing was benched" in out


def test_main_with_no_models_does_nothing(monkeypatch, capsys):
    monkeypatch.setattr(bench.strudel_mind, "require_validator", lambda: None)
    assert bench.main(["--models"]) == 1
    assert "No models" in capsys.readouterr().out


def test_models_accept_a_comma_separated_list():
    assert bench._split_models(["a,b", "c"]) == ["a", "b", "c"]


def test_default_arguments_match_the_documented_contract():
    args = bench.build_parser().parse_args([])
    assert args.base_url == "http://100.68.5.104:1234/v1"
    assert args.trials == 10
    assert args.timeout == 120.0
    assert args.out == "output/quality/strudel-mind-bench"
