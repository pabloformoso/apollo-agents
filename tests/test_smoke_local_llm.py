"""Unit tests for the local-LLM smoke gate's response judging.

`scripts/smoke_local_llm.py` decides whether a local model is fit to drive
a live stream, so a false PASS is worse than no gate at all: it green-lights
a broken model onto the channel. These tests pin `check_greeting`, whose
naive predecessor (``"marta" in text``) passed meta/muse-glimmer when it
answered with template scaffolding plus the prompt echoed back
(smoke 2026-08-12).

`scripts/` is not an importable package, so the module is loaded from its
path rather than imported by name.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "smoke_local_llm.py"
_spec = importlib.util.spec_from_file_location("smoke_local_llm", _SCRIPT)
assert _spec is not None and _spec.loader is not None
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)


# --- happy path ------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "¡Bienvenida, Marta! Ponte cómoda y disfruta de este espacio de calma.",
        "Hola Marta, bienvenida al canal de lofi: que la música te acompañe.",
        "marta, un gusto tenerte por aquí.",  # lowercase name still counts
    ],
)
def test_valid_greeting_passes(text):
    ok, reason = smoke.check_greeting(text)
    assert ok is True
    assert reason == ""


def test_surrounding_whitespace_is_tolerated():
    ok, reason = smoke.check_greeting("\n\n  ¡Hola Marta, bienvenida!  \n")
    assert ok is True
    assert reason == ""


# --- emptiness -------------------------------------------------------------

@pytest.mark.parametrize("text", ["", "   ", "\n\n", "\t"])
def test_empty_or_blank_fails(text):
    ok, reason = smoke.check_greeting(text)
    assert ok is False
    assert reason == "empty response"


# --- template leakage ------------------------------------------------------

def test_muse_glimmer_regression_is_rejected():
    """The exact shape that used to score a false PASS."""
    observed = (
        "to=self<|message|>[YT @marta_lofi] hola!! primera vez por aqui\n\n"
        "We need to respond as DJ once"
    )
    ok, reason = smoke.check_greeting(observed)
    assert ok is False
    assert "template leak" in reason


@pytest.mark.parametrize("marker", list(smoke.TEMPLATE_LEAK_MARKERS))
def test_every_declared_marker_is_rejected(marker):
    ok, reason = smoke.check_greeting(f"Hola Marta {marker} bienvenida")
    assert ok is False
    assert "template leak" in reason


def test_leak_detection_is_case_insensitive():
    ok, reason = smoke.check_greeting("Hola Marta <START_OF_TURN> bienvenida")
    assert ok is False
    assert "template leak" in reason


def test_leak_is_reported_before_name_check():
    """A leaking response that also lacks the name reports the leak, which is
    the actionable diagnosis (fix the chat template, not the prompt)."""
    ok, reason = smoke.check_greeting("<|channel|>analysis")
    assert ok is False
    assert "template leak" in reason


# --- prompt echo -----------------------------------------------------------

def test_verbatim_prompt_echo_fails():
    ok, reason = smoke.check_greeting(smoke.GREETING_USER_MSG)
    assert ok is False
    assert reason == "echoed the prompt back"


def test_prompt_echo_inside_a_longer_answer_fails():
    ok, reason = smoke.check_greeting(
        f"Sure, here is the message: {smoke.GREETING_USER_MSG} — responding now"
    )
    assert ok is False
    assert reason == "echoed the prompt back"


def test_prompt_echo_is_case_insensitive():
    ok, reason = smoke.check_greeting(smoke.GREETING_USER_MSG.upper())
    assert ok is False
    assert reason == "echoed the prompt back"


def test_mentioning_the_handle_without_echoing_still_passes():
    """The guard targets the echoed line, not the handle itself — a greeting
    that addresses @marta_lofi by handle is legitimate."""
    ok, reason = smoke.check_greeting("¡Bienvenida @marta_lofi, ponte cómoda!")
    assert ok is True
    assert reason == ""


# --- missing name ----------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "¡Bienvenida al canal! Ponte cómoda y disfruta.",
        "Welcome to the stream, enjoy the vibes.",
    ],
)
def test_generic_greeting_without_the_name_fails(text):
    ok, reason = smoke.check_greeting(text)
    assert ok is False
    assert reason == "does not name the user"


# --- contract --------------------------------------------------------------

def test_returns_two_tuple_of_bool_and_str():
    ok, reason = smoke.check_greeting("Hola Marta")
    assert isinstance(ok, bool)
    assert isinstance(reason, str)
