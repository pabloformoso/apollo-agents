"""Unit tests for the algorave playground server (plan §9 stage 1).

`scripts/algorave_playground.py` is the only thing standing between a browser
and `StrudelMind`, so what is tested here is the contract the page depends on:
the four failure codes are actually distinguishable (400 malformed, 502 the
mind held, 503 the validator is missing, 500 anything else), every one of them
carries CORS headers — a 502 the browser will not let the page read is a
swallowed error — and the whole request -> validate -> respond path runs with
`--mock` against the REAL Node validator.

No test opens an LLM connection. The unit tests stub `require_validator` and
inject their own mind factory, so they pass on a box with no node and no spike
`node_modules` (backend CI has neither); the real validator is exercised at the
bottom of the file behind the same skip guard `tests/test_strudel_mind.py` uses.

`scripts/` is loaded by path (the tests/test_bench_strudel_mind.py convention),
registered in `sys.modules` before `exec_module`.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import threading
import types
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.generative import strudel_mind
from agent.generative.strudel_mind import (
    FEW_SHOT_DEEPHOUSE,
    StrudelCode,
    StrudelMind,
    StrudelMindError,
)

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "algorave_playground.py"
_spec = importlib.util.spec_from_file_location("algorave_playground", _SCRIPT)
assert _spec is not None and _spec.loader is not None
playground = importlib.util.module_from_spec(_spec)
sys.modules["algorave_playground"] = playground
_spec.loader.exec_module(playground)

SPIKE = _ROOT / "scripts" / "algorave-spike"
SEED_FILE = SPIKE / "patterns" / "seed.repl.js"
PAGE_FILE = SPIKE / "patterns" / "playground.html"

ORIGIN = "http://127.0.0.1:4031"
OTHER_ORIGIN = "https://evil.example"


# ─── fakes ─────────────────────────────────────────────────────────────

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


def _factory(outcome):
    """A mind factory that hands every request the same fake mind."""
    mind = _Mind(outcome)
    calls: list[dict] = []

    def factory(request):
        calls.append(request)
        return mind

    factory.mind = mind
    factory.calls = calls
    return factory


@pytest.fixture
def validator_ok(monkeypatch):
    """No Node anywhere in the unit tests — the 503 path has its own test."""
    monkeypatch.setattr(strudel_mind, "require_validator", lambda: None)


@pytest.fixture
def serve():
    """Start a real server on an ephemeral port; returns its base URL."""
    started = []

    def _start(mind_factory, **kwargs):
        server = playground.make_server(mind_factory, "127.0.0.1", 0, quiet=True, **kwargs)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        started.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield _start
    for server in started:
        server.shutdown()
        server.server_close()


def _request(url, *, method="POST", body=None, origin=ORIGIN, path="/mind"):
    """(status, parsed body or raw text, headers) — errors are answers here."""
    headers = {"content-type": "application/json"}
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(url + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            head, status = dict(resp.headers), resp.status
    except urllib.error.HTTPError as exc:
        raw, head, status = exc.read(), dict(exc.headers), exc.code
    try:
        return status, json.loads(raw), head
    except json.JSONDecodeError:
        return status, raw.decode("utf-8", "replace"), head


def post(url, payload=None, *, raw=None, origin=ORIGIN, path="/mind"):
    body = raw if raw is not None else json.dumps(payload).encode("utf-8")
    return _request(url, method="POST", body=body, origin=origin, path=path)


# ─── parse_request ─────────────────────────────────────────────────────

def _body(**kw):
    return json.dumps(kw).encode("utf-8")


def test_a_minimal_request_gets_every_default_filled_in():
    req = playground.parse_request(_body(code="stack()", intent="darker"))
    assert req["code"] == "stack()" and req["intent"] == "darker"
    assert req["genre"] == "deep" and req["key"] == "A:minor"
    assert req["bars_elapsed"] == 0 and req["recent_reasons"] == []


def test_genre_and_key_are_per_request_overrides():
    req = playground.parse_request(
        _body(code="", intent="x", genre="lofi", key="F:minor"),
        default_genre="deep", default_key="A:minor",
    )
    assert req["genre"] == "lofi" and req["key"] == "F:minor"


def test_absent_code_is_the_open_the_set_case_not_an_error():
    """An empty buffer is exactly how a session starts — the mind handles it."""
    assert playground.parse_request(_body(intent="open"))["code"] == ""


def test_intent_is_required_because_it_is_the_whole_request():
    with pytest.raises(playground.BadRequest, match="intent"):
        playground.parse_request(_body(code="stack()"))


@pytest.mark.parametrize("payload", [
    b'{"code": "stack()", "intent": 7}',
    b'{"code": 7, "intent": "darker"}',
    b'{"code": "s", "intent": "d", "genre": 1}',
    b'{"code": "s", "intent": "d", "key": []}',
])
def test_wrong_types_are_refused_by_field(payload):
    with pytest.raises(playground.BadRequest):
        playground.parse_request(payload)


def test_broken_json_says_so():
    with pytest.raises(playground.BadRequest, match="valid JSON"):
        playground.parse_request(b'{"code": "stack()", ')


def test_a_json_array_is_not_a_request():
    with pytest.raises(playground.BadRequest, match="JSON object"):
        playground.parse_request(b'["stack()", "darker"]')


def test_undecodable_bytes_do_not_reach_json():
    with pytest.raises(playground.BadRequest, match="UTF-8"):
        playground.parse_request(b"\xff\xfe{}")


def test_bars_elapsed_must_be_a_non_negative_int_and_true_is_not_one():
    assert playground.parse_request(_body(intent="d", bars_elapsed=16))["bars_elapsed"] == 16
    for bad in (b'{"intent":"d","bars_elapsed":-1}', b'{"intent":"d","bars_elapsed":true}',
                b'{"intent":"d","bars_elapsed":"8"}'):
        with pytest.raises(playground.BadRequest, match="bars_elapsed"):
            playground.parse_request(bad)


def test_recent_reasons_must_be_strings():
    req = playground.parse_request(_body(intent="d", recent_reasons=["opened the filter"]))
    assert req["recent_reasons"] == ["opened the filter"]
    with pytest.raises(playground.BadRequest, match="recent_reasons"):
        playground.parse_request(b'{"intent":"d","recent_reasons":[1,2]}')


def test_an_absurd_body_is_refused_before_it_is_parsed():
    with pytest.raises(playground.BadRequest, match="larger than"):
        playground.parse_request(b"x" * (playground.MAX_BODY_BYTES + 1))


# ─── the b2b passthrough (§9.2) ────────────────────────────────────────
#
# The server's whole job here is to not lose the flag and not invent it. Four
# cases, because each is a different bug: true (a duet the mind must be told
# about), false and absent (a solo, which must reach the mind as the iteration-2
# state byte for byte), and a non-bool (a page bug, refused rather than coerced —
# a truthy "yes" would silently change the prompt).

def test_b2b_true_is_accepted_and_normalised():
    assert playground.parse_request(_body(intent="d", b2b=True))["b2b"] is True


def test_b2b_false_and_absent_both_mean_solo():
    assert playground.parse_request(_body(intent="d", b2b=False))["b2b"] is False
    assert playground.parse_request(_body(intent="d"))["b2b"] is False


@pytest.mark.parametrize("payload", [
    b'{"intent":"d","b2b":"true"}',
    b'{"intent":"d","b2b":1}',
    b'{"intent":"d","b2b":0}',
    b'{"intent":"d","b2b":null}',
    b'{"intent":"d","b2b":[]}',
    b'{"intent":"d","b2b":{}}',
])
def test_a_non_boolean_b2b_is_a_400_rather_than_a_coercion(payload):
    with pytest.raises(playground.BadRequest, match="b2b"):
        playground.parse_request(payload)


def test_b2b_reaches_the_state_the_mind_reads():
    state = playground.state_for(
        playground.parse_request(_body(code="stack()", intent="d", b2b=True))
    )
    assert state["b2b"] is True


@pytest.mark.parametrize("body", [
    _body(code="stack()", intent="d"),
    _body(code="stack()", intent="d", b2b=False),
])
def test_a_solo_state_carries_no_b2b_key_at_all(body):
    """Absent, not false: `strudel_mind` serializes whatever state it is handed,
    so a `b2b: false` in there would change the free-mode prompt for no reason.
    """
    state = playground.state_for(playground.parse_request(body))
    assert "b2b" not in state
    assert set(state) == {"current_code", "bars_elapsed", "recent_reasons"}


def test_state_for_carries_the_editor_code_as_current_code():
    """Non-empty current_code is what makes the call a MUTATION (§8.2)."""
    state = playground.state_for(playground.parse_request(
        _body(code="stack(s(\"bd*4\"))", intent="darker", bars_elapsed=8,
              recent_reasons=["a"])))
    assert state == {
        "current_code": 'stack(s("bd*4"))',
        "bars_elapsed": 8,
        "recent_reasons": ["a"],
    }


# ─── CORS ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("origin", ["http://127.0.0.1:4031", "http://localhost:4031"])
def test_both_spellings_of_the_spike_origin_are_allowed(origin):
    """They are different origins to a browser; the user types either one."""
    headers = playground.cors_headers(origin)
    assert headers["Access-Control-Allow-Origin"] == origin
    assert "POST" in headers["Access-Control-Allow-Methods"]
    assert headers["Vary"] == "Origin"


@pytest.mark.parametrize("origin", [None, "", OTHER_ORIGIN, "http://127.0.0.1:4010"])
def test_any_other_origin_gets_no_allow_origin_header(origin):
    headers = playground.cors_headers(origin)
    assert "Access-Control-Allow-Origin" not in headers
    assert headers["Vary"] == "Origin"


# ─── --allow-origin: serving the jam over the tailnet ──────────────────

def test_resolve_allowed_origins_defaults_to_the_spike_origins():
    assert playground.resolve_allowed_origins([]) == playground.SPIKE_ORIGINS
    assert playground.resolve_allowed_origins(None) == playground.SPIKE_ORIGINS


def test_resolve_allowed_origins_appends_normalized_and_deduped():
    allowed = playground.resolve_allowed_origins([
        "http://100.68.5.104:4031/",   # trailing slash — browsers never send it
        " http://100.68.5.104:4031 ",  # whitespace + duplicate collapses
        "",                            # empty is ignored, not an origin
        "http://127.0.0.1:4031",       # already a default — not doubled
    ])
    assert allowed == playground.SPIKE_ORIGINS + ("http://100.68.5.104:4031",)


def test_build_parser_collects_repeated_allow_origin_flags():
    args = playground.build_parser().parse_args([
        "--mock",
        "--allow-origin", "http://100.68.5.104:4031",
        "--allow-origin", "http://jam.example:4031",
    ])
    assert args.allow_origin == ["http://100.68.5.104:4031", "http://jam.example:4031"]


def test_an_extra_origin_is_readable_once_allowed(serve, validator_ok):
    """End to end: a server built with the tailnet origin answers it with CORS
    headers, the local defaults keep working beside it, and everything else
    still gets refused — extending the list must never mean opening it."""
    tailnet = "http://100.68.5.104:4031"
    url = serve(
        _factory(StrudelCode(code="stack()", reason="r", stats={})),
        allowed_origins=playground.resolve_allowed_origins([tailnet]),
    )

    status, _, headers = post(url, {"code": "", "intent": "x"}, origin=tailnet)
    assert status == 200
    assert headers.get("Access-Control-Allow-Origin") == tailnet

    _, _, headers = post(url, {"code": "", "intent": "x"}, origin=ORIGIN)
    assert headers.get("Access-Control-Allow-Origin") == ORIGIN

    _, _, headers = post(url, {"code": "", "intent": "x"}, origin=OTHER_ORIGIN)
    assert "Access-Control-Allow-Origin" not in headers


# ─── the mock mutation ─────────────────────────────────────────────────

def test_the_mock_pulls_the_first_numeric_gain_down():
    out = playground.mock_mutate('stack(s("bd*4").gain(0.92), s("hh*8").gain(0.4))', "darker")
    assert ".gain(0.782)" in out
    assert ".gain(0.4)" in out  # only the FIRST one moves


def test_the_mock_states_what_it_changed_in_a_reason_line():
    out = playground.mock_mutate('s("bd*4").gain(0.92)', "darker")
    first = out.splitlines()[0]
    assert first.startswith("// reason: mock —")
    assert "0.92" in first and "0.782" in first and "darker" in first


def test_the_mock_replaces_the_previous_reason_instead_of_stacking_them():
    once = playground.mock_mutate('// reason: seed\ns("bd*4").gain(0.9)', "darker")
    twice = playground.mock_mutate(once, "darker")
    assert twice.count("// reason:") == 1


def test_the_mock_is_deterministic():
    code = 'stack(s("bd*4").gain(0.92))'
    assert playground.mock_mutate(code, "darker") == playground.mock_mutate(code, "darker")


def test_an_empty_buffer_opens_with_the_seed_groove():
    out = playground.mock_mutate("", "open the set")
    assert "bd*4" in out and "opened with the seed groove" in out.splitlines()[0]


def test_code_with_no_numeric_gain_gets_a_master_trim_that_is_still_one_expression():
    """`.mul(gain(x))` scales each layer's own gain; a bare .gain() would
    overwrite them — the idiom the system prompt teaches."""
    out = playground.mock_mutate('s("bd*4").gain("[0.4 0.3]*2")', "darker")
    body = "\n".join(out.splitlines()[1:])
    assert body.startswith("(") and body.endswith(".mul(gain(0.85))")
    assert "no numeric gain" in out.splitlines()[0]


def test_the_mock_transport_ignores_the_prompt_it_is_handed():
    """It is bound to the request, not scraping the prompt — a mock that parsed
    the prompt would break every time the prompt is reworded."""
    llm = playground.mock_llm('s("bd*4").gain(0.9)', "darker")
    assert llm("SYSTEM", "USER") == llm("something", "else")
    assert ".gain(0.765)" in llm("", "")


def test_strip_leading_reason_only_touches_the_first_line():
    code = "// reason: a\nstack()\n// reason: not a leading one"
    assert playground.strip_leading_reason(code) == "stack()\n// reason: not a leading one"


# ─── HTTP: the happy path ──────────────────────────────────────────────

def test_a_valid_post_returns_code_reason_and_stats(serve, validator_ok):
    stats = {"events": 172, "cycles_checked": 4, "sounds": ["bd", "oh"],
             "kick_four_on_floor": True, "out_of_key": []}
    url = serve(_factory(StrudelCode(code="stack(s(\"bd*4\"))",
                                     reason="pulled the master down", stats=stats)))
    status, body, _ = post(url, {"code": "stack()", "intent": "darker"})

    assert status == 200
    assert body == {"code": 'stack(s("bd*4"))', "reason": "pulled the master down",
                    "stats": stats}


def test_the_editor_buffer_reaches_the_mind_as_current_code(serve, validator_ok):
    factory = _factory(StrudelCode(code="stack()"))
    url = serve(factory)
    post(url, {"code": 'stack(s("bd*4"))', "intent": "more swing",
               "bars_elapsed": 12, "recent_reasons": ["opened the filter"]})

    assert factory.mind.states == [{
        "current_code": 'stack(s("bd*4"))',
        "bars_elapsed": 12,
        "recent_reasons": ["opened the filter"],
    }]
    assert factory.mind.intents == ["more swing"]


def test_a_b2b_post_reaches_the_mind_as_state_b2b(serve, validator_ok):
    """The §9.2 wire claim, end to end: the page says `b2b: true`, the mind's
    state says `b2b: True`, and nothing else about the request moved."""
    factory = _factory(StrudelCode(code="stack()"))
    url = serve(factory)
    status, _, _ = post(url, {"code": 'stack(s("bd*4"))', "intent": "answer them",
                              "bars_elapsed": 16, "recent_reasons": ["human: +1 line"],
                              "b2b": True})

    assert status == 200
    assert factory.mind.states == [{
        "current_code": 'stack(s("bd*4"))',
        "bars_elapsed": 16,
        "recent_reasons": ["human: +1 line"],
        "b2b": True,
    }]


@pytest.mark.parametrize("payload", [
    {"code": "stack()", "intent": "d"},
    {"code": "stack()", "intent": "d", "b2b": False},
])
def test_a_free_mode_post_hands_the_mind_the_iteration_2_state(serve, validator_ok, payload):
    factory = _factory(StrudelCode(code="stack()"))
    url = serve(factory)
    post(url, payload)
    assert factory.mind.states == [{
        "current_code": "stack()", "bars_elapsed": 0, "recent_reasons": [],
    }]


def test_a_non_boolean_b2b_on_the_wire_is_400_and_never_reaches_the_mind(serve, validator_ok):
    factory = _factory(StrudelCode(code="stack()"))
    url = serve(factory)
    status, body, headers = post(url, {"code": "stack()", "intent": "d", "b2b": "yes"})

    assert status == 400
    assert "b2b" in body["detail"] and "boolean" in body["detail"]
    assert factory.calls == []
    assert headers["Access-Control-Allow-Origin"] == ORIGIN  # the page must read it


def test_genre_and_key_from_the_request_reach_the_factory(serve, validator_ok):
    factory = _factory(StrudelCode(code="stack()"))
    url = serve(factory, default_genre="deep", default_key="A:minor")
    post(url, {"code": "", "intent": "darker", "genre": "lofi", "key": "F:minor"})
    assert factory.calls[0]["genre"] == "lofi" and factory.calls[0]["key"] == "F:minor"


def test_a_missing_reason_is_null_rather_than_invented(serve, validator_ok):
    url = serve(_factory(StrudelCode(code="stack()", reason=None)))
    _, body, _ = post(url, {"code": "", "intent": "d"})
    assert body["reason"] is None and body["stats"] == {}


# ─── HTTP: the failure codes ───────────────────────────────────────────

def test_malformed_json_is_400_and_never_reaches_the_mind(serve, validator_ok):
    factory = _factory(StrudelCode(code="stack()"))
    url = serve(factory)
    status, body, _ = post(url, raw=b'{"code": "stack()", "intent"')

    assert status == 400
    assert body["error"] == "malformed request" and "valid JSON" in body["detail"]
    assert factory.calls == []


def test_a_request_without_an_intent_is_400(serve, validator_ok):
    url = serve(_factory(StrudelCode(code="stack()")))
    status, body, _ = post(url, {"code": "stack()"})
    assert status == 400 and "intent" in body["detail"]


def test_a_mind_that_failed_twice_is_502_carrying_both_validator_errors(serve, validator_ok):
    """Which two ways it failed IS the diagnosis — the whole message goes out."""
    exc = StrudelMindError(
        "slow plane failed twice — holding current code "
        "(1st: syntax error: Unexpected end of input; 2nd: zero events in 4 cycles)"
    )
    url = serve(_factory(exc))
    status, body, _ = post(url, {"code": "stack()", "intent": "darker"})

    assert status == 502
    assert "1st: syntax error: Unexpected end of input" in body["detail"]
    assert "2nd: zero events in 4 cycles" in body["detail"]
    assert "keep playing" in body["error"]


def test_a_missing_validator_is_503_with_the_npm_install_fix(serve, monkeypatch):
    """503, not 502: one is fixed with a command, the other by asking again."""
    def missing():
        raise StrudelMindError(
            "scripts/algorave-spike/node_modules is missing — run `npm install` in "
            "scripts/algorave-spike before the mind can validate Strudel code."
        )

    monkeypatch.setattr(strudel_mind, "require_validator", missing)
    factory = _factory(StrudelCode(code="stack()"))
    url = serve(factory)
    status, body, _ = post(url, {"code": "stack()", "intent": "darker"})

    assert status == 503
    assert "npm install" in body["detail"] and "node_modules" in body["detail"]
    assert factory.calls == [], "nothing should be asked of the mind without a validator"


def test_an_unexpected_failure_is_reported_as_500_not_swallowed(serve, validator_ok):
    """A dead LLM endpoint arrives as a transport exception, not a mind error."""
    url = serve(_factory(ConnectionError("no route to 100.68.5.104")))
    status, body, _ = post(url, {"code": "", "intent": "darker"})
    assert status == 500
    assert "ConnectionError: no route to 100.68.5.104" in body["detail"]


def test_an_unknown_path_is_404_naming_the_only_endpoint(serve, validator_ok):
    url = serve(_factory(StrudelCode(code="stack()")))
    status, body, _ = post(url, {"intent": "d"}, path="/mutate")
    assert status == 404 and "/mind" in body["detail"]


def test_getting_the_endpoint_says_it_is_post_only(serve, validator_ok):
    url = serve(_factory(StrudelCode(code="stack()")))
    status, body, _ = _request(url, method="GET", path="/mind")
    assert status == 405 and "POST" in body["error"]


# ─── HTTP: CORS on the wire ────────────────────────────────────────────

def test_the_spike_origin_can_read_a_200(serve, validator_ok):
    url = serve(_factory(StrudelCode(code="stack()")))
    _, _, headers = post(url, {"code": "", "intent": "d"}, origin=ORIGIN)
    assert headers["Access-Control-Allow-Origin"] == ORIGIN
    assert headers["Vary"] == "Origin"


@pytest.mark.parametrize("outcome,expected", [
    (StrudelMindError("failed twice (1st: a; 2nd: b)"), 502),
    (ConnectionError("boom"), 500),
])
def test_errors_carry_cors_too_or_the_page_cannot_read_them(serve, validator_ok,
                                                            outcome, expected):
    """A 502 the browser refuses to expose is a swallowed error."""
    url = serve(_factory(outcome))
    status, _, headers = post(url, {"code": "", "intent": "d"})
    assert status == expected
    assert headers["Access-Control-Allow-Origin"] == ORIGIN


def test_a_400_carries_cors_as_well(serve, validator_ok):
    url = serve(_factory(StrudelCode(code="stack()")))
    status, _, headers = post(url, raw=b"not json")
    assert status == 400 and headers["Access-Control-Allow-Origin"] == ORIGIN


def test_an_unlisted_origin_gets_no_cors_header(serve, validator_ok):
    url = serve(_factory(StrudelCode(code="stack()")))
    status, _, headers = post(url, {"code": "", "intent": "d"}, origin=OTHER_ORIGIN)
    assert status == 200  # the request still runs; the BROWSER is what refuses the read
    assert "Access-Control-Allow-Origin" not in headers


def test_the_options_preflight_advertises_post_and_content_type(serve, validator_ok):
    url = serve(_factory(StrudelCode(code="stack()")))
    status, _, headers = _request(url, method="OPTIONS", origin=ORIGIN)
    assert status == 204
    assert headers["Access-Control-Allow-Origin"] == ORIGIN
    assert "POST" in headers["Access-Control-Allow-Methods"]
    assert "content-type" in headers["Access-Control-Allow-Headers"].lower()
    assert headers["Access-Control-Max-Age"] == "600"


def test_the_preflight_refuses_an_unlisted_origin(serve, validator_ok):
    url = serve(_factory(StrudelCode(code="stack()")))
    status, _, headers = _request(url, method="OPTIONS", origin=OTHER_ORIGIN)
    assert status == 204 and "Access-Control-Allow-Origin" not in headers


# ─── the factories ─────────────────────────────────────────────────────

def test_mock_mode_never_builds_an_llm_client(monkeypatch):
    """The whole point of --mock: zero network, so a demo needs no tunnel."""
    sabotage = types.ModuleType("openai")

    def _explode(*args, **kwargs):
        raise AssertionError("--mock built an LLM client")

    sabotage.OpenAI = _explode
    monkeypatch.setitem(sys.modules, "openai", sabotage)

    factory = playground.build_mind_factory(playground.build_parser().parse_args(["--mock"]))
    mind = factory({"code": 'stack(s("bd*4").gain(0.9))', "intent": "darker",
                    "genre": "deep", "key": "A:minor"})
    assert isinstance(mind, StrudelMind)


def test_mock_mode_hands_the_request_genre_and_key_to_the_mind(monkeypatch):
    seen = {}

    def _record(llm=None, genre=None, key=None, **kwargs):
        seen.update(genre=genre, key=key, llm=llm)
        return SimpleNamespace()

    monkeypatch.setattr(playground, "StrudelMind", _record)
    playground.mock_mind_factory()({"code": "", "intent": "d", "genre": "lofi",
                                    "key": "F:minor"})
    assert seen["genre"] == "lofi" and seen["key"] == "F:minor"
    assert callable(seen["llm"])


def test_live_mode_builds_an_explicit_client_rather_than_detecting_the_env(monkeypatch):
    """The 2026-08-14 lesson: a stale env var silently redirects a whole run."""
    built = {}
    sent = {}

    def _create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="stack()"))])

    fake = types.ModuleType("openai")
    fake.OpenAI = lambda **kwargs: (
        built.update(kwargs),
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create))),
    )[1]
    monkeypatch.setitem(sys.modules, "openai", fake)

    args = playground.build_parser().parse_args(
        ["--model", "qwen/qwen3.6-27b", "--base-url", "http://host:1234/v1",
         "--api-key", "k", "--max-tokens", "2048"]
    )
    mind = playground.build_mind_factory(args)(
        {"code": "", "intent": "d", "genre": "deep", "key": "A:minor"}
    )

    assert built["base_url"] == "http://host:1234/v1" and built["api_key"] == "k"
    assert isinstance(mind, StrudelMind)
    mind._llm("SYS", "USR")
    assert sent["model"] == "qwen/qwen3.6-27b" and sent["max_tokens"] == 2048
    assert sent["messages"][0] == {"role": "system", "content": "SYS"}


def test_the_bench_helper_is_reused_so_both_send_the_same_request_shape():
    from scripts.bench_strudel_mind import make_llm

    assert playground._make_llm_helper() is make_llm


# ─── CLI ───────────────────────────────────────────────────────────────

def test_default_arguments_match_the_documented_contract():
    args = playground.build_parser().parse_args([])
    assert args.port == 4032, "4010/4020 are prod, 4011/4021 dev, 4031 the spike page"
    assert args.host == "127.0.0.1"
    assert args.base_url == "http://100.68.5.104:1234/v1"
    assert args.model == "google/gemma-4-e4b"
    assert args.genre == "deep" and args.key == "A:minor"
    assert args.mock is False


def test_the_module_does_not_load_dotenv_at_import_time():
    """A worktree .env must never quietly redirect the endpoint.

    Checked as the call and the import, not the bare word — the module
    docstring says why it does not do this, and that sentence is not a call.
    """
    source = _SCRIPT.read_text(encoding="utf-8")
    assert "load_dotenv(" not in source
    assert "import load_dotenv" not in source and "import dotenv" not in source


# ─── the seed the page ships ───────────────────────────────────────────

def test_the_seed_file_is_the_few_shot_verbatim():
    """The page cannot import Python, so the seed is duplicated — this is the
    guard that the copy has not drifted from the constant it was copied from."""
    text = SEED_FILE.read_text(encoding="utf-8")
    assert FEW_SHOT_DEEPHOUSE in text


def test_the_seed_file_names_its_source_of_truth():
    head = SEED_FILE.read_text(encoding="utf-8").splitlines()[0:10]
    assert any("strudel_mind.py" in line and "FEW_SHOT_DEEPHOUSE" in line for line in head)


def test_the_seed_obeys_the_validator_contract_comments_included():
    """The WHOLE file is what the page POSTs, so the screen covers the header.

    Found the hard way on 2026-08-29: a provenance comment reading "cannot
    import Python at run time" put a bare `import` in the buffer, and every mind
    click on a freshly loaded page came back 502 — `validate.mjs`'s
    BANNED_TOKEN_RE screens the comments too. Same regex as the validator, so a
    reworded header cannot quietly reintroduce it.
    """
    text = SEED_FILE.read_text(encoding="utf-8")
    found = sorted(set(re.findall(r"\b(import|require|fetch|eval|process)\b", text)))
    assert found == [], f"seed.repl.js carries screened words: {found}"
    assert "setcps" not in text, "the page owns tempo (§8.1 code contract)"


def test_the_page_talks_to_this_server_and_loads_that_seed():
    html = PAGE_FILE.read_text(encoding="utf-8")
    assert ":4032/mind" in html.replace("${location.hostname || '127.0.0.1'}", "")
    assert "./seed.repl.js" in html
    assert "@strudel/web" in html and "evaluate" in html


# ─── integration: --mock end to end, through the REAL validator ────────
#
# Same guard as tests/test_strudel_mind.py: backend CI has neither node nor the
# spike's node_modules, and a validator that exists but does not yet speak the
# §8.1 verdict contract counts as absent. The skip reason names what was seen,
# so a broken validator is a loud skip rather than silence.

def _real_validator_ready() -> tuple[bool, str]:
    if shutil.which("node") is None:
        return False, "node is not on PATH"
    if not (SPIKE / "validate.mjs").exists():
        return False, "scripts/algorave-spike/validate.mjs does not exist"
    if not (SPIKE / "node_modules").is_dir():
        return False, "scripts/algorave-spike/node_modules is absent (npm install)"
    try:
        verdict = strudel_mind.validate_code('stack(s("bd*4"))', cycles=1)
    except StrudelMindError as exc:
        return False, f"validate.mjs does not speak the 8.1 verdict contract yet: {exc}"
    if not verdict.get("valid"):
        return False, f"validate.mjs rejects a bare four-on-floor kick: {verdict.get('error')}"
    return True, ""


_READY, _WHY_NOT = _real_validator_ready()
_needs_validator = pytest.mark.skipif(not _READY, reason=f"real validator unavailable: {_WHY_NOT}")

SEED_CODE = FEW_SHOT_DEEPHOUSE


@pytest.fixture
def mock_server(serve):
    """The exact factory `main --mock` serves with. No stubs below this line."""
    return serve(playground.mock_mind_factory())


@_needs_validator
def test_mock_mode_answers_a_real_request_with_validated_code(mock_server):
    status, body, headers = post(mock_server, {"code": SEED_CODE, "intent": "darker"})

    assert status == 200, body
    assert body["code"] != SEED_CODE, "the proposal must differ or there is nothing to diff"
    assert body["reason"].startswith("mock —")
    assert body["stats"]["events"] >= 1
    assert body["stats"]["cycles_checked"] == strudel_mind.VALIDATE_CYCLES
    assert body["stats"]["kick_four_on_floor"] is True
    assert "bd" in body["stats"]["sounds"]
    assert headers["Access-Control-Allow-Origin"] == ORIGIN


@_needs_validator
def test_the_mutation_is_the_seed_with_one_gain_pulled_down(mock_server):
    _, body, _ = post(mock_server, {"code": SEED_CODE, "intent": "darker"})
    before = [ln for ln in SEED_CODE.splitlines() if not ln.startswith("// reason:")]
    after = [ln for ln in body["code"].splitlines() if not ln.startswith("// reason:")]
    changed = [(a, b) for a, b in zip(before, after) if a != b]

    assert len(before) == len(after)
    assert len(changed) == 1, f"expected one changed line, got {changed}"
    assert ".gain(0.782)" in changed[0][1]


@_needs_validator
def test_the_seed_file_round_trips_exactly_as_the_page_sends_it(mock_server):
    """The page POSTs the file, not the constant — header comments and all.

    The unit tests above scan that file; this one proves the claim end to end,
    because a first mind click on a freshly loaded page is the single most
    likely thing anyone does with this server, and it answered 502 until the
    seed's own header was fixed (2026-08-29).
    """
    status, body, _ = post(mock_server, {
        "code": SEED_FILE.read_text(encoding="utf-8"), "intent": "darker",
    })
    assert status == 200, body
    assert body["stats"]["events"] >= 1


@_needs_validator
def test_an_empty_editor_opens_the_set_through_the_real_validator(mock_server):
    _, body, _ = post(mock_server, {"code": "", "intent": "open the set"})
    assert body["stats"]["events"] >= 1
    assert "opened with the seed groove" in body["reason"]


@_needs_validator
def test_code_the_real_validator_rejects_twice_comes_back_as_502(serve):
    """The page must be told BOTH ways it failed — this is the reject-and-hold
    contract seen from the browser's side, with a real Node verdict."""
    broken = serve(lambda request: StrudelMind(llm=lambda system, user: 'stack(s("bd*4"'))
    status, body, headers = post(broken, {"code": SEED_CODE, "intent": "break it"})

    assert status == 502
    assert "failed twice" in body["detail"]
    assert body["detail"].count("syntax error") >= 2 or (
        "1st:" in body["detail"] and "2nd:" in body["detail"]
    )
    assert headers["Access-Control-Allow-Origin"] == ORIGIN
