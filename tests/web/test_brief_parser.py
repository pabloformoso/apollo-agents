"""Unit tests for ``web.backend.brief_parser``.

The LLM call inside ``parse`` is exercised only via monkeypatched stubs
so the suite stays deterministic and free of network calls. The pure
``_normalize`` helper is the bulk of the coverage — it's where the
type-coercion + clamp + enum-validation logic lives.

Since v3.11 ``parse`` dispatches on the CONFIGURED provider, so every
test that reaches it must pin the environment: the ``_clean_env``
fixture below strips the provider vars so an ambient ``.env`` (the dev
box exports ``AGENT_PROVIDER=ollama``) can never send a unit test at a
real endpoint.
"""
from __future__ import annotations

import pytest

from web.backend import brief_parser
from web.backend.brief_parser import (
    _empty,
    _normalize,
    detect_provider,
    extract_json_object,
    parse,
)

_PROVIDER_ENV = (
    "AGENT_PROVIDER",
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT",
    "LITELLM_BASE_URL",
    "LITELLM_API_KEY",
    "OLLAMA_BASE_URL",
    "AGENT_MODEL",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in _PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


# ─── _normalize ──────────────────────────────────────────────────────


def test_normalize_empty_input_returns_all_nulls():
    out = _normalize({})
    assert out == _empty()


def test_normalize_strips_and_lowercases_genre():
    out = _normalize({"genre": "  Deep House  "})
    assert out["genre"] == "deep house"


def test_normalize_rejects_blank_genre():
    out = _normalize({"genre": "   "})
    assert out["genre"] is None


def test_normalize_clamps_duration_range():
    assert _normalize({"duration_min": 0})["duration_min"] is None
    assert _normalize({"duration_min": -5})["duration_min"] is None
    assert _normalize({"duration_min": 1})["duration_min"] == 1
    assert _normalize({"duration_min": 600})["duration_min"] == 600
    assert _normalize({"duration_min": 601})["duration_min"] is None


def test_normalize_floors_float_duration():
    assert _normalize({"duration_min": 45.7})["duration_min"] == 45


def test_normalize_accepts_known_venues_only():
    assert _normalize({"venue": "garden"})["venue"] == "garden"
    assert _normalize({"venue": "  Bar "})["venue"] == "bar"
    # Unknown venue is stripped to None rather than passed through.
    assert _normalize({"venue": "stadium"})["venue"] is None


def test_normalize_accepts_known_energy_values_only():
    for v in ("plateau", "with peak", "building", "descending"):
        assert _normalize({"energy": v})["energy"] == v
    assert _normalize({"energy": "explosive"})["energy"] is None


def test_normalize_preserves_mood_and_tempo_strings():
    out = _normalize({"mood": " chill ", "tempo": "120–128 BPM"})
    assert out["mood"] == "chill"
    assert out["tempo"] == "120–128 BPM"


def test_normalize_handles_wrong_types_gracefully():
    out = _normalize({
        "genre": 42,             # non-string → null
        "duration_min": "thirty",  # non-numeric → null
        "mood": None,            # explicit null → null
        "venue": ["garden"],     # wrong shape → null
        "energy": "loud",        # not in enum → null
        "tempo": False,          # non-string → null
    })
    assert out == _empty()


# ─── parse (LLM seam monkeypatched) ──────────────────────────────────


def test_parse_empty_brief_short_circuits(monkeypatch):
    """No API call when the brief is empty / whitespace."""
    import anthropic

    called = {"n": 0}

    class _Boom:
        def __init__(self):
            called["n"] += 1
            raise AssertionError("Anthropic should not have been called")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(anthropic, "Anthropic", _Boom, raising=False)
    assert parse("") == _empty()
    assert parse("   \n\t") == _empty()
    assert called["n"] == 0


def test_parse_missing_api_key_returns_empty(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert parse("30 min of lofi") == _empty()


def test_parse_returns_normalized_payload(monkeypatch):
    """Stub the SDK so the parser receives a tool_use block and the
    output is run through ``_normalize``.

    The parser does ``from anthropic import Anthropic`` inside the
    function body so we patch the attribute on the ``anthropic``
    module itself rather than on ``brief_parser``.
    """
    import anthropic

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    class _Block:
        def __init__(self):
            self.type = "tool_use"
            self.name = "report_brief"
            self.input = {
                "genre": "LoFi",
                "duration_min": 30,
                "mood": "chill",
                "venue": "garden",
                "energy": "plateau",
                "tempo": "60–66 BPM",
            }

    class _Response:
        content = [_Block()]

    class _Messages:
        def create(self, **_):
            return _Response()

    class _Client:
        def __init__(self):
            self.messages = _Messages()

    monkeypatch.setattr(anthropic, "Anthropic", _Client, raising=False)
    out = parse("30 minute lofi set in a garden")
    assert out == {
        "genre": "lofi",       # lowercased by _normalize
        "duration_min": 30,
        "mood": "chill",
        "venue": "garden",
        "energy": "plateau",
        "tempo": "60–66 BPM",
    }


def test_parse_handles_sdk_exception(monkeypatch):
    """Any failure inside the LLM call must degrade to all-null rather
    than crash the calling endpoint."""
    import anthropic

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    class _ExplodingClient:
        def __init__(self):
            raise RuntimeError("simulated SDK failure")

    monkeypatch.setattr(anthropic, "Anthropic", _ExplodingClient, raising=False)
    assert parse("90 minute techno set") == _empty()


# ─── detect_provider ─────────────────────────────────────────────────


def test_explicit_provider_wins_over_present_keys(monkeypatch):
    """An operator who pins AGENT_PROVIDER means it — a stale Anthropic
    key left in .env must not silently reroute the parser."""
    monkeypatch.setenv("AGENT_PROVIDER", "ollama")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "leftover")
    assert detect_provider() == "ollama"


def test_provider_name_is_normalized(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "  Ollama  ")
    assert detect_provider() == "ollama"


def test_falls_back_to_anthropic_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert detect_provider() == "anthropic"


def test_falls_back_to_azure_key(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    assert detect_provider() == "azure"


def test_anthropic_key_outranks_azure_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    assert detect_provider() == "anthropic"


def test_falls_back_to_local_endpoint(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://100.68.5.104:1234/v1")
    assert detect_provider() == "ollama"


def test_falls_back_to_litellm_endpoint(monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "https://litellm.example.org/v1")
    assert detect_provider() == "litellm"


def test_litellm_endpoint_outranks_ollama_endpoint(monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "https://litellm.example.org/v1")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    assert detect_provider() == "litellm"


def test_litellm_client_uses_proxy_url_and_key(monkeypatch):
    from web.backend.brief_parser import _build_openai_client

    monkeypatch.setenv("LITELLM_BASE_URL", "https://litellm.example.org/v1")
    monkeypatch.setenv("LITELLM_API_KEY", "sk-team")
    client, model = _build_openai_client("litellm")
    assert str(client.base_url).startswith("https://litellm.example.org/v1")
    assert client.api_key == "sk-team"
    assert model == "qwen3.6-27b"


def test_litellm_client_agent_model_override(monkeypatch):
    from web.backend.brief_parser import _build_openai_client

    monkeypatch.setenv("LITELLM_BASE_URL", "https://litellm.example.org/v1")
    monkeypatch.setenv("AGENT_MODEL", "qwen-next")
    _client, model = _build_openai_client("litellm")
    assert model == "qwen-next"


def test_nothing_configured_defaults_to_anthropic():
    """Preserves the old behaviour: fail with a clear missing-key path."""
    assert detect_provider() == "anthropic"


# ─── extract_json_object ─────────────────────────────────────────────


def test_extracts_a_bare_object():
    assert extract_json_object('{"genre": "lofi"}') == {"genre": "lofi"}


def test_extracts_from_a_fenced_block():
    text = 'Sure!\n```json\n{"genre": "techno"}\n```\nHope that helps.'
    assert extract_json_object(text) == {"genre": "techno"}


def test_extracts_object_wrapped_in_prose():
    text = 'Here is what I understood: {"genre": "aural", "duration_min": 60} — enjoy!'
    assert extract_json_object(text) == {"genre": "aural", "duration_min": 60}


def test_handles_nested_objects():
    assert extract_json_object('{"a": {"b": 1}}') == {"a": {"b": 1}}


def test_braces_inside_strings_do_not_close_the_object():
    """A ``}`` inside a value must not truncate the scan."""
    assert extract_json_object('{"mood": "warm }not the end{"}') == {
        "mood": "warm }not the end{"
    }


def test_escaped_quote_inside_a_string_is_survived():
    assert extract_json_object('{"mood": "he said \\"hi\\""}') == {
        "mood": 'he said "hi"'
    }


def test_no_object_returns_none():
    assert extract_json_object("I could not parse that, sorry.") is None


def test_empty_text_returns_none():
    assert extract_json_object("") is None


def test_unbalanced_object_returns_none():
    assert extract_json_object('{"genre": "lofi"') is None


def test_malformed_json_returns_none():
    assert extract_json_object("{genre: lofi,,}") is None


def test_object_wrapped_in_a_list_is_still_recovered():
    """The scan starts at the first ``{``, so a list wrapper is harmless."""
    assert extract_json_object('[{"genre": "lofi"}]') == {"genre": "lofi"}


def test_top_level_json_scalar_returns_none():
    assert extract_json_object("42") is None


# ─── _normalize additions for the schema-less path ───────────────────


def test_normalize_recovers_a_quoted_duration():
    """No tool schema on the local path — models quote the number."""
    assert _normalize({"duration_min": "60"})["duration_min"] == 60
    assert _normalize({"duration_min": "90 min"})["duration_min"] == 90


def test_normalize_rejects_out_of_range_quoted_duration():
    assert _normalize({"duration_min": "900"})["duration_min"] is None


def test_normalize_rejects_boolean_duration():
    """``True`` is an int subclass — it must not become 1 minute."""
    assert _normalize({"duration_min": True})["duration_min"] is None


def test_normalize_treats_the_string_null_as_null():
    """Small models write the word instead of the JSON literal."""
    out = _normalize({"mood": "null", "tempo": "NULL"})
    assert out["mood"] is None
    assert out["tempo"] is None


# ─── parse: provider dispatch ────────────────────────────────────────


def test_mock_provider_never_calls_an_llm(monkeypatch):
    """E2E runs set AGENT_PROVIDER=mock precisely to stay offline."""
    monkeypatch.setenv("AGENT_PROVIDER", "mock")

    def _boom(*_a, **_k):
        raise AssertionError("no LLM call may happen under mock")

    monkeypatch.setattr(brief_parser, "_parse_anthropic", _boom)
    monkeypatch.setattr(brief_parser, "_parse_openai_compatible", _boom)
    assert parse("30 min of lofi") == _empty()


def test_local_provider_is_used_without_any_anthropic_key(monkeypatch):
    """The regression this change exists for: a box with no Anthropic key
    used to throw every free-text brief away."""
    monkeypatch.setenv("AGENT_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://x/v1")
    monkeypatch.setenv("AGENT_MODEL", "google/gemma-4-e4b")

    seen = {}

    class _Completions:
        def create(self, **kwargs):
            seen.update(kwargs)
            return _reply('{"genre": "Aural", "duration_min": "60", '
                          '"mood": "calm", "venue": "home", '
                          '"energy": "plateau", "tempo": "50–56 BPM"}')

    monkeypatch.setattr(
        brief_parser, "_build_openai_client",
        lambda _p: (_client(_Completions()), "google/gemma-4-e4b"),
    )

    assert parse("an hour of calm aural at home") == {
        "genre": "aural",
        "duration_min": 60,
        "mood": "calm",
        "venue": "home",
        "energy": "plateau",
        "tempo": "50–56 BPM",
    }
    assert seen["model"] == "google/gemma-4-e4b"
    assert seen["temperature"] == 0.0


def test_local_provider_unparseable_reply_degrades_to_null(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "ollama")

    class _Completions:
        def create(self, **_):
            return _reply("I think you want something chill!")

    monkeypatch.setattr(
        brief_parser, "_build_openai_client",
        lambda _p: (_client(_Completions()), "m"),
    )
    assert parse("30 min of lofi") == _empty()


def test_local_provider_empty_content_degrades_to_null(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "ollama")

    class _Completions:
        def create(self, **_):
            return _reply(None)

    monkeypatch.setattr(
        brief_parser, "_build_openai_client",
        lambda _p: (_client(_Completions()), "m"),
    )
    assert parse("30 min of lofi") == _empty()


def test_local_provider_network_error_degrades_to_null(monkeypatch):
    """A dead tunnel must not 500 the session POST."""
    monkeypatch.setenv("AGENT_PROVIDER", "ollama")

    class _Completions:
        def create(self, **_):
            raise ConnectionError("tunnel is down")

    monkeypatch.setattr(
        brief_parser, "_build_openai_client",
        lambda _p: (_client(_Completions()), "m"),
    )
    assert parse("30 min of lofi") == _empty()


def test_missing_model_for_provider_returns_empty(monkeypatch):
    """Azure with no deployment name configured: bail, don't call."""
    monkeypatch.setenv("AGENT_PROVIDER", "azure")

    class _Completions:
        def create(self, **_):
            raise AssertionError("must not call without a model")

    monkeypatch.setattr(
        brief_parser, "_build_openai_client",
        lambda _p: (_client(_Completions()), ""),
    )
    assert parse("30 min of lofi") == _empty()


def test_empty_brief_short_circuits_before_provider_detection(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "ollama")

    def _boom(*_a, **_k):
        raise AssertionError("empty brief must not reach a provider")

    monkeypatch.setattr(brief_parser, "_parse_openai_compatible", _boom)
    assert parse("  \n ") == _empty()


def test_azure_client_is_built_from_azure_env(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    client, model = brief_parser._build_openai_client("azure")
    assert model == "gpt-4o"
    assert "example.openai.azure.com" in str(client.base_url)


def test_local_client_points_at_the_configured_endpoint(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://100.68.5.104:1234/v1")
    monkeypatch.setenv("AGENT_MODEL", "google/gemma-4-e4b")
    client, model = brief_parser._build_openai_client("ollama")
    assert model == "google/gemma-4-e4b"
    assert "100.68.5.104:1234" in str(client.base_url)


# ─── stub helpers for the OpenAI-compatible shape ────────────────────


def _reply(content):
    message = type("M", (), {"content": content})()
    choice = type("C", (), {"message": message})()
    return type("R", (), {"choices": [choice]})()


def _client(completions):
    return type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()


def test_parse_handles_response_without_tool_use(monkeypatch):
    """If the LLM somehow returns plain text instead of a tool_use block,
    fall through to all-null defensively."""
    import anthropic

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    class _TextBlock:
        type = "text"
        text = "no tool use here"

    class _Response:
        content = [_TextBlock()]

    class _Messages:
        def create(self, **_):
            return _Response()

    class _Client:
        def __init__(self):
            self.messages = _Messages()

    monkeypatch.setattr(anthropic, "Anthropic", _Client, raising=False)
    assert parse("anything") == _empty()


# ─── OpenAI-compatible token budget ──────────────────────────────────
#
# Regression guard for 2026-08-17: swapping the local endpoint to
# gemma4:12b-it-qat on Ollama broke free-text briefs in production. The
# model reasons before emitting content, so the old 512-token ceiling was
# spent thinking and the JSON object came back truncated mid-key. The
# parser degraded to all-null exactly as designed — which is why nothing
# crashed and nothing alerted.


def _stub_openai(monkeypatch, reply: str, captured: dict):
    """Point the ollama provider at a stub that records its call kwargs."""
    import openai

    monkeypatch.setenv("AGENT_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://stub:11434/v1")
    monkeypatch.setenv("AGENT_MODEL", "stub-model")

    class _Message:
        content = reply

    class _Choice:
        message = _Message()

    class _Response:
        choices = [_Choice()]

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _Response()

    class _Chat:
        completions = _Completions()

    class _Client:
        def __init__(self, **_):
            self.chat = _Chat()

    monkeypatch.setattr(openai, "OpenAI", _Client, raising=False)


def test_openai_path_requests_room_for_reasoning_preamble(monkeypatch):
    """A reasoning model needed 502-523 tokens for this prompt; 512 truncated it."""
    captured: dict = {}
    _stub_openai(monkeypatch, '{"genre": "healing", "duration_min": 60}', captured)
    parse("60 minutes of healing music")
    assert captured["max_tokens"] >= 1024, (
        "budget must clear the observed reasoning preamble with headroom"
    )
    assert captured["max_tokens"] == brief_parser._OPENAI_MAX_TOKENS


def test_openai_path_parses_a_complete_object(monkeypatch):
    captured: dict = {}
    _stub_openai(
        monkeypatch,
        '{"genre": "Healing", "duration_min": 60, "mood": "tranquila", '
        '"venue": null, "energy": null, "tempo": "auto"}',
        captured,
    )
    assert parse("Sesion de 60 minutos de musica healing") == {
        "genre": "healing",  # lowercased by _normalize
        "duration_min": 60,
        "mood": "tranquila",
        "venue": None,
        "energy": None,
        "tempo": "auto",
    }


def test_openai_path_truncated_object_degrades_to_null(monkeypatch):
    """The exact production symptom: a JSON object cut off mid-key.

    It must stay a graceful all-null rather than raise — the endpoint
    falls through to the genre guard, which asks the user directly.
    """
    captured: dict = {}
    _stub_openai(
        monkeypatch,
        '{"genre": "healing", "duration_min": 90, "mood": "deep meditation", "venue": null',
        captured,
    )
    assert parse("90-minute healing set") == _empty()


def test_openai_path_empty_reply_degrades_to_null(monkeypatch):
    """All budget spent on reasoning, zero characters of content."""
    captured: dict = {}
    _stub_openai(monkeypatch, "", captured)
    assert parse("60 minutes of healing music") == _empty()


# ─── token budget and timeout, calibrated per model ──────────────────
#
# Two calibrations, two failures, same file:
#   2026-08-17  gemma4:12b-it-qat needed 502-523 tokens; the ceiling was
#               512, so the JSON came back truncated mid-key.
#   2026-08-18  qwen3.6-27b behind LiteLLM needs ~2010 — four times that
#               — and at 1536 returned finish_reason="length" with an
#               EMPTY body, so there was not even a partial object to
#               salvage. It also took 29.5 s against a 30 s timeout.
#
# Both failures are silent by design: parse() degrades to all-null and
# the endpoint falls through to the genre guard. These tests are the only
# thing that makes the budget visible.


def test_token_budget_covers_the_measured_reasoning_preamble():
    """3072 clears qwen3.6's ~2010 with headroom for a slower model."""
    assert brief_parser._OPENAI_MAX_TOKENS >= 2560


def test_timeout_clears_the_measured_worst_case():
    """qwen3.6 measured 29.5s; a 30s bound made the parse a coin flip."""
    assert brief_parser.TIMEOUT_SEC >= 40.0


def test_timeout_stays_bounded():
    """The call blocks a session POST — it must not become unbounded.

    Past ~a minute the user is better served by the conversational genre
    guard than by a spinner, so a model needing more is the wrong model
    for this path rather than a reason to raise the bound again.
    """
    assert brief_parser.TIMEOUT_SEC <= 60.0


def test_openai_path_uses_the_configured_budget(monkeypatch):
    captured: dict = {}
    _stub_openai(monkeypatch, '{"genre": "healing", "duration_min": 60}', captured)
    parse("60 minutes of healing music")
    assert captured["max_tokens"] == brief_parser._OPENAI_MAX_TOKENS
