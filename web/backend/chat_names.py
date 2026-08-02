"""Chat display-name sanitization + greeting-event construction (v3.7.0).

YouTube usernames go two dangerous places: ON STREAM (rendered by the
OBS Browser Source at 1080p) and INTO THE LLM PROMPT (as part of the
``[YT @name] text`` framing the live DJ reads). Both paths get the same
defensive cleaning here:

- display safety: control chars, URLs, zero-width spam and absurd
  lengths never reach the overlay;
- prompt safety: ``[`` / ``]`` / backticks / newlines are stripped so a
  crafted username can't fake the message framing or open a code fence
  inside the DJ's context (the DJ prompt additionally pins chat content
  as data, never instructions);
- known chat bots get no greeting at all.

Pure functions only — no I/O — so the whole matrix is unit-testable.
"""
from __future__ import annotations

import re

#: Well-known chat/moderation bots. Exact match on the normalized name.
BOT_NAMES = {
    "nightbot",
    "streamelements",
    "streamlabs",
    "moobot",
    "fossabot",
    "botrix",
    "wizebot",
}

#: Rendered names longer than this get an ellipsis — keeps the overlay
#: layout safe against 70-char unicode-art usernames.
MAX_DISPLAY_LEN = 24

_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
# Control chars, zero-width/format chars (ZWSP..RLM, line/para
# separators, word-joiner, BOM), and the framing/injection characters
# we never want inside `[YT @name]` or on the overlay: square brackets,
# backticks, angle brackets, braces. Escapes spelled out (\uXXXX) so
# the source file itself contains no invisible characters.
_STRIP_RE = re.compile(
    "[\\x00-\\x1f\\x7f"
    "\\u200b-\\u200f\\u2028\\u2029\\u2060\\ufeff"
    "\\[\\]`<>{}]"
)


def sanitize_display_name(raw: str | None) -> str | None:
    """Return a display-safe, prompt-safe version of ``raw``, or None.

    None means "do not greet / do not render": empty input, a name that
    is nothing but stripped garbage, or a known bot.
    """
    if not raw:
        return None
    name = _URL_RE.sub("", raw)
    name = _STRIP_RE.sub("", name)
    # Collapse runs of whitespace (including exotic unicode spaces).
    name = re.sub(r"\s+", " ", name).strip()
    # Leading @ is ours to add at render time, not the user's.
    name = name.lstrip("@").strip()
    if not name:
        return None
    if name.casefold() in BOT_NAMES:
        return None
    if len(name) > MAX_DISPLAY_LEN:
        name = name[: MAX_DISPLAY_LEN - 1].rstrip() + "…"
    return name


def build_greeting_event(author: str | None, is_first: bool) -> dict | None:
    """Build the ``chat_greeting`` WS event for a chat message, or None.

    None when no greeting should fire: not a first message, unusable
    name, or a bot. ``kind`` is an enum from day one ("first" now,
    "returning" reserved for channel-level regulars) so the frontend
    contract doesn't break when regulars land.
    """
    if not is_first:
        return None
    name = sanitize_display_name(author)
    if name is None:
        return None
    return {"type": "chat_greeting", "author": name, "kind": "first"}
