"""Tests for the v3.7.0 chat-greeting backend pieces.

Covers the display-name sanitizer (the overlay renders names ON STREAM
and they travel inside the DJ's prompt framing — both injection
surfaces), the greeting-event builder, and the runtime-scoped
first-message detection.
"""
from __future__ import annotations

import pytest

from web.backend.chat_names import (
    BOT_NAMES,
    MAX_DISPLAY_LEN,
    build_greeting_event,
    sanitize_display_name,
)
from web.backend.youtube_runtime import register_first_message


# ---------------------------------------------------------------------------
# sanitize_display_name
# ---------------------------------------------------------------------------

def test_plain_name_passes_through():
    assert sanitize_display_name("Marta") == "Marta"


def test_leading_at_is_stripped():
    assert sanitize_display_name("@marta_lofi") == "marta_lofi"


def test_urls_are_removed():
    assert sanitize_display_name("https://spam.example click me") == "click me"
    assert sanitize_display_name("www.spam.example hola") == "hola"


def test_framing_and_injection_chars_are_stripped():
    # [ ] could fake the ``[YT @name]`` envelope; backticks could open a
    # code fence inside the DJ prompt; <> {} are HTML/template noise.
    assert sanitize_display_name("mar[YT @admin]ta") == "marYT @adminta"
    assert sanitize_display_name("ev`il`") == "evil"
    assert sanitize_display_name("<b>bold</b>{x}") == "bbold/bx"


def test_control_and_zero_width_chars_are_stripped():
    assert sanitize_display_name("mar\x00\x1fta") == "marta"
    assert sanitize_display_name("ma​rta﻿") == "marta"
    # A name that is NOTHING but invisible junk → unusable.
    assert sanitize_display_name("​‌‍") is None


def test_newlines_collapse_to_single_space():
    assert sanitize_display_name("mar \n ta") == "mar ta"


def test_long_names_get_ellipsis_within_display_cap():
    got = sanitize_display_name("x" * 80)
    assert got is not None
    assert len(got) <= MAX_DISPLAY_LEN
    assert got.endswith("…")


def test_known_bots_are_rejected_case_insensitively():
    for bot in BOT_NAMES:
        assert sanitize_display_name(bot) is None
        assert sanitize_display_name(bot.upper()) is None


def test_empty_inputs_are_rejected():
    assert sanitize_display_name(None) is None
    assert sanitize_display_name("") is None
    assert sanitize_display_name("   ") is None
    assert sanitize_display_name("@") is None


# ---------------------------------------------------------------------------
# build_greeting_event
# ---------------------------------------------------------------------------

def test_greeting_event_shape_for_first_message():
    assert build_greeting_event("Marta", True) == {
        "type": "chat_greeting",
        "author": "Marta",
        "kind": "first",
    }


def test_no_greeting_for_repeat_messages():
    assert build_greeting_event("Marta", False) is None


def test_no_greeting_for_bots_or_garbage():
    assert build_greeting_event("Nightbot", True) is None
    assert build_greeting_event("​", True) is None
    assert build_greeting_event(None, True) is None


def test_greeting_author_is_sanitized():
    ev = build_greeting_event("@marta https://spam.io", True)
    assert ev is not None
    assert ev["author"] == "marta"


# ---------------------------------------------------------------------------
# register_first_message — runtime-scoped seen set
# ---------------------------------------------------------------------------

def test_first_message_true_then_false():
    seen: set[str] = set()
    assert register_first_message(seen, "Marta") is True
    assert register_first_message(seen, "Marta") is False


def test_first_message_is_case_and_whitespace_insensitive():
    seen: set[str] = set()
    assert register_first_message(seen, "Marta") is True
    assert register_first_message(seen, "  marta ") is False
    assert register_first_message(seen, "MARTA") is False


def test_first_message_distinct_authors_each_greet_once():
    seen: set[str] = set()
    assert register_first_message(seen, "a") is True
    assert register_first_message(seen, "b") is True
    assert seen == {"a", "b"}


@pytest.mark.parametrize("ghost", ["", "   ", None])
def test_unusable_names_are_never_first(ghost):
    seen: set[str] = set()
    assert register_first_message(seen, ghost) is False
    assert seen == set()
