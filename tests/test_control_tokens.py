"""Tests for the chat-template control-token filter.

Observed live on 2026-08-17 with gemma4:12b-it-qat on local Ollama: 6 of
the 7 non-empty live-DJ turns had the literal string ``<|tool_response>``
as their ENTIRE visible answer. The live loop streams that text straight
to the on-stream chat overlay, so viewers would read the control token.

The streaming case is the one that actually bites: deltas arrive in
arbitrary chunks, so a token can straddle two of them and per-chunk
stripping would let both halves through.
"""
from __future__ import annotations

import pytest

from agent.run import ControlTokenFilter, strip_control_tokens


class TestStripControlTokens:

    def test_strips_the_observed_leak(self):
        assert strip_control_tokens("<|tool_response>") == ""

    def test_strips_the_pipe_closed_spelling(self):
        """``to=self<|message|>`` — the muse-glimmer shape."""
        assert strip_control_tokens("to=self<|message|>") == "to=self"

    def test_strips_a_token_embedded_in_prose(self):
        assert strip_control_tokens(
            "Nice and steady<|tool_response> for now"
        ) == "Nice and steady for now"

    def test_leaves_ordinary_prose_untouched(self):
        text = "The set is moving with a nice, steady pulse."
        assert strip_control_tokens(text) == text

    def test_does_not_eat_comparisons(self):
        """Prose with < and > must survive — it is not a control token."""
        assert strip_control_tokens("BPM a < b and c > d") == "BPM a < b and c > d"

    @pytest.mark.parametrize("value", [None, ""])
    def test_empty_input_returns_empty_string(self, value):
        assert strip_control_tokens(value) == ""


class TestControlTokenFilterStreaming:

    def _run(self, chunks: list[str]) -> str:
        f = ControlTokenFilter()
        return "".join(f.feed(c) for c in chunks) + f.flush()

    def test_token_arriving_in_one_chunk(self):
        assert self._run(["<|tool_response>"]) == ""

    def test_token_split_across_two_chunks(self):
        """The case per-chunk stripping cannot catch."""
        assert self._run(["<|tool", "_response>"]) == ""

    def test_token_split_character_by_character(self):
        assert self._run(list("<|tool_response>")) == ""

    def test_token_split_with_prose_around_it(self):
        assert self._run(["Steady ", "<|tool", "_response>", " pulse"]) == "Steady  pulse"

    def test_prose_streams_through_unchanged(self):
        chunks = ["The set ", "is moving ", "nicely."]
        assert self._run(chunks) == "The set is moving nicely."

    def test_lone_angle_bracket_is_released_on_flush(self):
        """A ``<`` that never becomes a token must not be swallowed."""
        assert self._run(["a < b"]) == "a < b"

    def test_incomplete_token_at_end_of_stream_is_released(self):
        """Held-back text is emitted rather than lost if the stream ends."""
        assert self._run(["done ", "<|tool"]) == "done <|tool"

    def test_filter_holds_back_only_a_candidate_tail(self):
        """``a < b`` must not stall waiting for a ``>`` that never comes."""
        f = ControlTokenFilter()
        assert f.feed("a < b") == "a < b"

    def test_holds_back_a_real_candidate_tail(self):
        f = ControlTokenFilter()
        assert f.feed("hello <|too") == "hello "
        assert f.feed("l_response>") == ""
        assert f.flush() == ""

    def test_two_tokens_in_one_stream(self):
        assert self._run(["<|message|>", "ok", "<|tool_response>"]) == "ok"

    def test_flush_is_idempotent(self):
        f = ControlTokenFilter()
        f.feed("text")
        assert f.flush() == ""
        assert f.flush() == ""
