"""S2 slow plane: LLM transport and the Node validator are both mocked.

These exercise the contract that keeps mind-written Strudel away from the
speakers: fence tolerance, the validator subprocess call, reject-and-hold with
one retry, and the "say what to run" errors when the spike is not installed.

The unit tests must pass on a box with NO node and NO scripts/algorave-spike
node_modules (backend CI has neither), so they stub `require_validator` and
`subprocess.run`. The real validator is exercised separately at the bottom of
the file, behind a skip guard.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.generative import strudel_mind
from agent.generative.strudel_mind import (
    B2B_USER_LINE,
    FEW_SHOT_DEEPHOUSE,
    PALETTE,
    SYSTEM_PROMPT,
    StrudelCode,
    StrudelMind,
    StrudelMindError,
    _extract_code,
    _leading_reason,
    _resolve_model,
    build_system_prompt,
)

VALID_CODE = 'stack(s("bd*4"), s("[~ oh]*4"))'


# ─── fakes ─────────────────────────────────────────────────────────────

def _verdict(valid=True, error=None, reason="opened the bass filter", events=64):
    return {
        "valid": valid,
        "error": error,
        "reason": reason if valid else None,
        "stats": {
            "events": events,
            "cycles_checked": 4,
            "sounds": ["bd", "oh"],
            "kick_four_on_floor": True,
            "out_of_key": [],
        } if valid else {},
    }


def _rejected(error):
    return _verdict(valid=False, error=error)


class _FakeRun:
    """Scripted stand-in for subprocess.run.

    Yields the queued verdicts in order and then repeats the last one, so a
    "fails the same way twice" test needs only one entry. A queued exception is
    raised instead (that is how TimeoutExpired / FileNotFoundError are tested).
    """

    def __init__(self, items):
        self.items = list(items)
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, subprocess.CompletedProcess):
            return item
        return subprocess.CompletedProcess(cmd, 0, json.dumps(item) + "\n", "")


@pytest.fixture
def validator(monkeypatch):
    """Neutralise the install check; return a factory that scripts the verdicts."""
    monkeypatch.setattr(strudel_mind, "require_validator", lambda: None)

    def script(*items):
        fake = _FakeRun(items)
        monkeypatch.setattr(strudel_mind.subprocess, "run", fake)
        return fake

    return script


def _replying(*replies):
    """An llm that returns the given replies in order, recording its prompts."""
    prompts: list[tuple[str, str]] = []

    def llm(system, user):
        prompts.append((system, user))
        return replies[min(len(prompts) - 1, len(replies) - 1)]

    llm.prompts = prompts  # type: ignore[attr-defined]
    return llm


def _state(current_code=""):
    return {
        "current_code": current_code,
        "bars_elapsed": 16,
        "recent_reasons": ["seed groove"],
    }


# ─── _extract_code / _leading_reason ───────────────────────────────────

def test_extracts_bare_code():
    assert _extract_code(VALID_CODE) == VALID_CODE


def test_strips_a_fenced_block():
    reply = f"Here you go:\n```javascript\n{VALID_CODE}\n```\nEnjoy!"
    assert _extract_code(reply) == VALID_CODE


def test_strips_an_untagged_fence():
    assert _extract_code(f"```\n{VALID_CODE}\n```") == VALID_CODE


def test_tolerates_a_fence_the_model_never_closed():
    """A truncated reply still carries usable code — take what is there."""
    assert _extract_code(f"```js\n{VALID_CODE}") == VALID_CODE


def test_empty_reply_is_an_error_not_empty_code():
    with pytest.raises(StrudelMindError, match="no code"):
        _extract_code("   \n  ")


def test_reason_line_is_read_off_the_code():
    code = f"// reason: darker, closed the filter\n{VALID_CODE}"
    assert _leading_reason(code) == "darker, closed the filter"


def test_code_without_a_reason_line_has_none():
    assert _leading_reason(VALID_CODE) is None


# ─── prompt ────────────────────────────────────────────────────────────

def test_system_prompt_states_the_output_contract():
    assert "ONLY code" in SYSTEM_PROMPT
    assert "// reason:" in SYSTEM_PROMPT
    assert "setcps" in SYSTEM_PROMPT           # tempo is the harness's
    assert "import" in SYSTEM_PROMPT           # token screen announced up front
    for sound in PALETTE:
        assert sound in SYSTEM_PROMPT


def test_deep_genre_prompt_carries_brief_key_and_few_shot():
    prompt = build_system_prompt("deep")
    assert prompt.startswith(SYSTEM_PROMPT)
    assert "GENRE: deep house" in prompt
    assert 'scale("A:minor")' in prompt
    assert FEW_SHOT_DEEPHOUSE in prompt


def test_unknown_genre_keeps_the_dialect_lesson():
    """No brief for a genre we have no idiom for — but the few-shot stays,
    because it teaches the dialect, not the genre."""
    prompt = build_system_prompt("gabber")
    assert "GENRE:" not in prompt
    assert FEW_SHOT_DEEPHOUSE in prompt


def test_few_shot_obeys_its_own_contract():
    """The example the model copies must not model forbidden behaviour."""
    for banned in ("import", "require(", "setcps", "fetch(", "process."):
        assert banned not in FEW_SHOT_DEEPHOUSE
    assert FEW_SHOT_DEEPHOUSE.startswith("// reason:")
    assert "'" not in FEW_SHOT_DEEPHOUSE  # double-quoted mini strings only


def test_empty_state_asks_for_an_opening_pattern(validator):
    validator(_verdict())
    llm = _replying(VALID_CODE)
    StrudelMind(llm=llm).next_code(_state(), "darker")
    user = llm.prompts[0][1]
    assert "Nothing is playing yet" in user
    assert "darker" in user
    assert "seed groove" in user  # state is serialized into the prompt


def test_current_code_turns_the_call_into_a_mutation(validator):
    validator(_verdict())
    llm = _replying(VALID_CODE)
    StrudelMind(llm=llm).next_code(_state(current_code=FEW_SHOT_DEEPHOUSE), "build")
    user = llm.prompts[0][1]
    assert "MUTATE" in user
    assert "say what you changed" in user
    # Shown once, as code — not a second time inside the state JSON blob.
    assert user.count('s("bd*4")') == 1


# ─── B2B: the one duet line (§9.2) ─────────────────────────────────────
#
# The contract is deliberately narrow — ONE line, in the USER message, present
# exactly when the state says the pen is alternating — because the system prompt
# is what `scripts/bench_strudel_mind.py` scores a model against. A duet that
# quietly reworded the system prompt would make every B2B session incomparable
# to the bench that qualified the model for it.

def _prompts_for(validator, state, intent="darker"):
    """The (system, user) pair a single next_code call actually sent."""
    validator(_verdict())
    llm = _replying(VALID_CODE)
    StrudelMind(llm=llm).next_code(state, intent)
    return llm.prompts[0]


def test_b2b_state_appends_the_duet_line_to_the_user_message(validator):
    _, user = _prompts_for(validator, {**_state(current_code=VALID_CODE), "b2b": True})
    assert B2B_USER_LINE in user
    assert user.count(B2B_USER_LINE) == 1


def test_the_duet_line_is_the_contract_wording_verbatim():
    """§9.2 pins the sentence, not a paraphrase: it names recent_reasons as the
    partner's channel and forbids undoing their move. Reword it and the mind is
    answering a different brief from the one the plan describes."""
    assert B2B_USER_LINE == (
        "You are in a back-to-back set. recent_reasons carries your partner's "
        "moves — acknowledge the LAST one and answer it; never undo it."
    )


def test_without_b2b_the_user_message_has_no_duet_line(validator):
    _, solo = _prompts_for(validator, _state(current_code=VALID_CODE))
    assert B2B_USER_LINE not in solo
    assert "back-to-back" not in solo


def test_b2b_false_is_solo_not_a_duet(validator):
    """The page omits the key in free mode, but an explicit false must not be
    read as truthy — `state.get("b2b")` is the whole gate."""
    _, user = _prompts_for(validator, {**_state(current_code=VALID_CODE), "b2b": False})
    assert B2B_USER_LINE not in user


def test_the_duet_prompt_is_the_solo_prompt_plus_exactly_that_one_line(validator):
    """"Appends ONE line" taken literally — the only difference between the two
    user messages is the line itself, appended at the end. The flag is kept out
    of the serialized state so it is not also said a second time as JSON."""
    state = _state(current_code=FEW_SHOT_DEEPHOUSE)
    _, solo = _prompts_for(validator, state)
    _, duet = _prompts_for(validator, {**state, "b2b": True})

    assert duet == f"{solo}\n\n{B2B_USER_LINE}"
    assert '"b2b"' not in duet  # said once, as a sentence — not twice
    assert duet.rstrip().endswith("never undo it.")


def test_the_duet_line_survives_the_opening_pattern_case(validator):
    """An empty buffer is still a turn: the mind may be handed the pen first."""
    _, user = _prompts_for(validator, {**_state(), "b2b": True})
    assert "Nothing is playing yet" in user
    assert B2B_USER_LINE in user


def test_the_system_prompt_is_byte_identical_with_and_without_b2b(validator):
    """The bench comparability guarantee, asserted rather than asserted-to."""
    state = _state(current_code=VALID_CODE)
    solo_system, _ = _prompts_for(validator, state)
    duet_system, _ = _prompts_for(validator, {**state, "b2b": True})

    assert duet_system == solo_system
    assert duet_system == build_system_prompt("deep", "A:minor")
    assert B2B_USER_LINE not in duet_system
    assert "back-to-back" not in duet_system


# ─── next_code: happy path ─────────────────────────────────────────────

def test_happy_path_returns_validated_code(validator):
    run = validator(_verdict(reason="four-on-floor with an offbeat hat"))
    llm = _replying(VALID_CODE)

    out = StrudelMind(llm=llm).next_code(_state(), "darker")

    assert isinstance(out, StrudelCode)
    assert out.code == VALID_CODE
    assert out.reason == "four-on-floor with an offbeat hat"
    assert out.stats["events"] == 64
    assert len(llm.prompts) == 1 and len(run.calls) == 1
    assert llm.prompts[0][0] == build_system_prompt("deep")


def test_fences_are_stripped_before_the_validator_sees_the_code(validator):
    run = validator(_verdict())
    llm = _replying(f"```javascript\n{VALID_CODE}\n```")

    out = StrudelMind(llm=llm).next_code(_state(), "x")

    assert out.code == VALID_CODE
    assert run.calls[0][1]["input"] == VALID_CODE  # no backticks reach node


def test_reason_falls_back_to_the_code_comment(validator):
    """A validator that reports no reason does not lose one the code carries."""
    validator(_verdict(reason=None))
    code = f"// reason: stripped the stabs\n{VALID_CODE}"
    out = StrudelMind(llm=_replying(code)).next_code(_state(), "strip it back")
    assert out.reason == "stripped the stabs"


def test_validator_is_invoked_as_node_validate_mjs_in_the_spike_dir(validator):
    run = validator(_verdict())
    StrudelMind(llm=_replying(VALID_CODE), key="F:minor", cycles=8).next_code(_state(), "x")

    cmd, kwargs = run.calls[0]
    assert cmd[:2] == ["node", "validate.mjs"]
    assert "--cycles" in cmd and "8" in cmd
    assert "--key" in cmd and "F:minor" in cmd
    assert kwargs["cwd"] == str(strudel_mind.SPIKE_DIR)
    assert kwargs["capture_output"] is True and kwargs["text"] is True


def test_verdict_is_read_past_node_noise(validator):
    """Node warnings on stdout must not be mistaken for the verdict line."""
    noisy = subprocess.CompletedProcess(
        ["node"], 0,
        "(node:1) ExperimentalWarning: blah\n" + json.dumps(_verdict()) + "\n", "",
    )
    validator(noisy)
    assert StrudelMind(llm=_replying(VALID_CODE)).next_code(_state(), "x").stats["events"] == 64


# ─── next_code: reject-and-hold ────────────────────────────────────────

def test_retry_recovers_after_an_invalid_first_attempt(validator):
    validator(_rejected("SyntaxError: Unexpected token )"), _verdict())
    llm = _replying("broken(", VALID_CODE)

    out = StrudelMind(llm=llm).next_code(_state(), "build")

    assert out.code == VALID_CODE
    assert len(llm.prompts) == 2
    retry = llm.prompts[1][1]
    assert "REJECTED" in retry and "Unexpected token" in retry


def test_two_rejections_raise_carrying_both_errors(validator):
    validator(_rejected("SyntaxError: Unexpected token )"), _rejected("no events in 4 cycles"))
    llm = _replying("broken(", "also broken(")

    with pytest.raises(StrudelMindError) as exc:
        StrudelMind(llm=llm).next_code(_state(), "x")

    message = str(exc.value)
    assert "failed twice" in message
    assert "Unexpected token" in message and "no events" in message
    assert len(llm.prompts) == 2  # exactly one retry, never two


def test_token_screen_verdict_retries_then_raises(validator):
    """The hygiene screen is a normal rejection: retried once, then held."""
    screened = _rejected("forbidden token 'import' in submitted code")
    run = validator(screened)
    llm = _replying('import { s } from "@strudel/core"; ' + VALID_CODE)

    with pytest.raises(StrudelMindError, match="forbidden token"):
        StrudelMind(llm=llm).next_code(_state(), "x")

    assert len(run.calls) == 2 and len(llm.prompts) == 2


def test_a_reply_with_no_code_is_a_rejection_not_a_crash(validator):
    validator(_verdict())
    llm = _replying("", VALID_CODE)

    out = StrudelMind(llm=llm).next_code(_state(), "x")

    assert out.code == VALID_CODE
    assert "no code" in llm.prompts[1][1]


def test_rejection_without_an_error_message_still_reports_something(validator):
    validator({"valid": False, "error": None, "reason": None, "stats": {}})
    with pytest.raises(StrudelMindError, match="rejected without an error message"):
        StrudelMind(llm=_replying(VALID_CODE)).next_code(_state(), "x")


def test_validator_timeout_is_treated_as_a_rejection(validator):
    """A pattern whose query never terminates is bad code, not broken plumbing —
    so it gets the same one retry as any other rejection."""
    run = validator(subprocess.TimeoutExpired(cmd="node", timeout=30.0))

    with pytest.raises(StrudelMindError, match="timed out"):
        StrudelMind(llm=_replying(VALID_CODE)).next_code(_state(), "x")

    assert len(run.calls) == 2


# ─── harness breakage never masquerades as a bad idea ──────────────────

def test_nonzero_exit_raises_immediately_without_a_retry(validator):
    """§8.1: exit 0 whenever a verdict was computed. Nonzero means the
    validator broke, which is not the model's fault and must not be retried."""
    broken = subprocess.CompletedProcess(["node"], 1, "", "TypeError: evalScope is not a function")
    run = validator(broken)
    llm = _replying(VALID_CODE)

    with pytest.raises(StrudelMindError, match="validator exited 1"):
        StrudelMind(llm=llm).next_code(_state(), "x")

    assert len(run.calls) == 1 and len(llm.prompts) == 1


def test_verdict_that_is_not_json_raises(validator):
    validator(subprocess.CompletedProcess(["node"], 0, "not json at all\n", ""))
    with pytest.raises(StrudelMindError, match="no verdict JSON"):
        StrudelMind(llm=_replying(VALID_CODE)).next_code(_state(), "x")


# ─── require_validator: the message must carry the fix ─────────────────

@pytest.fixture
def spike(tmp_path, monkeypatch):
    """Point the module at a throwaway spike dir and pretend node exists."""
    monkeypatch.setattr(strudel_mind, "SPIKE_DIR", tmp_path)
    monkeypatch.setattr(strudel_mind, "VALIDATOR", tmp_path / "validate.mjs")
    monkeypatch.setattr(strudel_mind.shutil, "which", lambda name: "/usr/bin/node")
    return tmp_path


def test_missing_validator_file_says_npm_install(spike):
    (spike / "node_modules").mkdir()
    with pytest.raises(StrudelMindError) as exc:
        strudel_mind.require_validator()
    assert "npm install" in str(exc.value) and "validate.mjs" in str(exc.value)


def test_missing_node_modules_says_npm_install(spike):
    (spike / "validate.mjs").write_text("// stub", encoding="utf-8")
    with pytest.raises(StrudelMindError) as exc:
        strudel_mind.require_validator()
    assert "npm install" in str(exc.value) and "node_modules" in str(exc.value)


def test_missing_node_binary_says_install_node(spike, monkeypatch):
    (spike / "validate.mjs").write_text("// stub", encoding="utf-8")
    (spike / "node_modules").mkdir()
    monkeypatch.setattr(strudel_mind.shutil, "which", lambda name: None)
    with pytest.raises(StrudelMindError) as exc:
        strudel_mind.require_validator()
    assert "Node.js" in str(exc.value) and "npm install" in str(exc.value)


def test_a_complete_install_passes_the_check(spike):
    (spike / "validate.mjs").write_text("// stub", encoding="utf-8")
    (spike / "node_modules").mkdir()
    strudel_mind.require_validator()  # must not raise


def test_a_missing_install_is_caught_before_the_subprocess(spike, monkeypatch):
    """No traceback out of subprocess: the check runs first, every time."""
    def explode(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("subprocess.run was reached with no validator")

    monkeypatch.setattr(strudel_mind.subprocess, "run", explode)
    with pytest.raises(StrudelMindError, match="npm install"):
        strudel_mind.validate_code(VALID_CODE)


# ─── model resolution (#123 precedent) ─────────────────────────────────

def _fake_openai(monkeypatch, reply="stack()"):
    """Install a fake `openai` module and capture what the client is asked for."""
    captured: dict = {}

    class _Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            captured["create"] = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=reply))]
            )

    module = types.ModuleType("openai")
    module.OpenAI = _Client
    module.AzureOpenAI = _Client
    monkeypatch.setitem(sys.modules, "openai", module)
    return captured


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "ollama")
    for var in ("GENERATIVE_MODEL", "AGENT_MODEL", "GENERATIVE_MAX_TOKENS"):
        monkeypatch.delenv(var, raising=False)


def test_resolve_model_prefers_generative_model(monkeypatch):
    monkeypatch.setenv("GENERATIVE_MODEL", "qwen/qwen3.6-27b")
    monkeypatch.setenv("AGENT_MODEL", "google/gemma-4-e4b")
    assert _resolve_model("fallback") == "qwen/qwen3.6-27b"


def test_resolve_model_falls_back_to_agent_model(monkeypatch):
    monkeypatch.delenv("GENERATIVE_MODEL", raising=False)
    monkeypatch.setenv("AGENT_MODEL", "google/gemma-4-e4b")
    assert _resolve_model("fallback") == "google/gemma-4-e4b"


def test_resolve_model_falls_back_to_the_provider_default(monkeypatch):
    monkeypatch.delenv("GENERATIVE_MODEL", raising=False)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    assert _resolve_model("gemma4:4b") == "gemma4:4b"


def test_ollama_path_sends_generative_model_over_agent_model(clean_env, monkeypatch):
    captured = _fake_openai(monkeypatch)
    monkeypatch.setenv("AGENT_MODEL", "google/gemma-4-e4b")
    monkeypatch.setenv("GENERATIVE_MODEL", "qwen/qwen3.6-27b")

    strudel_mind._default_llm("sys", "usr")

    assert captured["create"]["model"] == "qwen/qwen3.6-27b"


def test_ollama_path_uses_agent_model_when_generative_is_unset(clean_env, monkeypatch):
    captured = _fake_openai(monkeypatch)
    monkeypatch.setenv("AGENT_MODEL", "google/gemma-4-e4b")

    strudel_mind._default_llm("sys", "usr")

    assert captured["create"]["model"] == "google/gemma-4-e4b"


def test_ollama_path_sets_an_explicit_token_budget(clean_env, monkeypatch):
    """The #123 lesson: assume a reasoner, or the code is truncated away."""
    captured = _fake_openai(monkeypatch)
    strudel_mind._default_llm("sys", "usr")
    assert captured["create"]["max_tokens"] == 4096


def test_token_budget_is_env_tunable(clean_env, monkeypatch):
    captured = _fake_openai(monkeypatch)
    monkeypatch.setenv("GENERATIVE_MAX_TOKENS", "8192")
    strudel_mind._default_llm("sys", "usr")
    assert captured["create"]["max_tokens"] == 8192


def test_a_junk_token_budget_falls_back_instead_of_crashing(clean_env, monkeypatch):
    captured = _fake_openai(monkeypatch)
    monkeypatch.setenv("GENERATIVE_MAX_TOKENS", "lots")
    strudel_mind._default_llm("sys", "usr")
    assert captured["create"]["max_tokens"] == 4096


def test_ollama_path_returns_the_reply_text(clean_env, monkeypatch):
    _fake_openai(monkeypatch, reply=VALID_CODE)
    assert strudel_mind._default_llm("sys", "usr") == VALID_CODE


# ─── integration: the REAL validator ───────────────────────────────────
#
# These are the only tests here that spawn Node. They exist to prove the
# plumbing — argv, cwd, stdin, verdict parsing — against the real thing, and
# they SKIP rather than fail whenever the real thing is not available:
#
#   * backend CI has neither node nor the spike's node_modules;
#   * the spike is a separate npm package, so `npm install` is a local step;
#   * `validate.mjs` may exist and not yet implement the §8.1 verdict contract
#     (it was a hardcoded API probe while this module was being written).
#
# The last one is why the guard probes instead of only stat-ing the file: a
# validator that is still being written is "absent" for our purposes, and the
# place its contract is pinned is the spike's own vitest suite, not here. The
# skip reason always names what was actually seen, so a permanently broken
# validator shows up as a loud skip rather than silence.

_SPIKE = Path(__file__).resolve().parents[1] / "scripts" / "algorave-spike"


def _real_validator_ready() -> tuple[bool, str]:
    if shutil.which("node") is None:
        return False, "node is not on PATH"
    if not (_SPIKE / "validate.mjs").exists():
        return False, "scripts/algorave-spike/validate.mjs does not exist"
    if not (_SPIKE / "node_modules").is_dir():
        return False, "scripts/algorave-spike/node_modules is absent (npm install)"
    try:
        verdict = strudel_mind.validate_code('stack(s("bd*4"))', cycles=1)
    except StrudelMindError as exc:  # no verdict line, crash, unparseable output
        return False, f"validate.mjs does not speak the 8.1 verdict contract yet: {exc}"
    if not verdict.get("valid"):
        return False, f"validate.mjs rejects a bare four-on-floor kick: {verdict.get('error')}"
    return True, ""


_READY, _WHY_NOT = _real_validator_ready()
_needs_validator = pytest.mark.skipif(not _READY, reason=f"real validator unavailable: {_WHY_NOT}")


@_needs_validator
def test_real_validator_accepts_a_minimal_stack():
    mind = StrudelMind(llm=lambda system, user: 'stack(s("bd*4"), s("hh*8"))')
    out = mind.next_code(_state(), "keep it simple")
    assert out.stats.get("events", 0) >= 1


@_needs_validator
def test_real_validator_accepts_the_few_shot_we_teach():
    """If the example in the system prompt does not validate, every model that
    copies it faithfully is scored as a failure."""
    mind = StrudelMind(llm=lambda system, user: FEW_SHOT_DEEPHOUSE)
    out = mind.next_code(_state(), "seed the set")
    assert out.stats.get("events", 0) >= 1
    assert out.reason


@_needs_validator
def test_real_validator_rejects_broken_code_twice_and_the_mind_holds():
    mind = StrudelMind(llm=lambda system, user: 'stack(s("bd*4"')
    with pytest.raises(StrudelMindError, match="failed twice"):
        mind.next_code(_state(), "break it")
