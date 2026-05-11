"""Adapt v2.5 ``structured_problems`` into v2.6 ``CriticNote`` payloads.

The legacy critic emits ``{pos_from, pos_to, key_pair, bpm_diff, text}``
records with no stable identity and no apply/ignore mechanism. The
redesign Curate screen needs ``{id, severity, target, headline, body,
suggestion, status}`` so users can act on each note individually.

Until the critic prompt is rewritten to emit notes natively, this module
is the single source of truth for the mapping.
"""
from __future__ import annotations

import hashlib
import re

# Severity heuristic — the v2.5 critic never emits positive ("ok") notes,
# so the mapper only distinguishes "fix" (a real transition issue) from
# "tip" (smaller jitter). Mirrors the threshold the deprecated client-side
# `adaptProblem` in `app/curate/page.tsx` used.
_FIX_BPM_DIFF = 5

_SUGGESTION_RE = re.compile(
    # Require whitespace or a colon after the keyword so substrings like
    # "try-line" or "consider-this" don't match. Captures the action
    # clause through the next sentence terminator.
    r"(?:Try|Consider|Suggest)(?:[ \t]+|:[ \t]*)(.+?)(?:\.|$)",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def note_id(problem: dict) -> str:
    """Deterministic 8-char id derived from positions + text.

    Stable across restarts so the frontend's optimistic ``handled`` set
    keeps pointing at the same note after a re-fetch.
    """
    raw = f"{problem.get('pos_from')}|{problem.get('pos_to')}|{problem.get('text', '')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


def _target(problem: dict) -> str:
    pf, pt = problem.get("pos_from"), problem.get("pos_to")
    if pf is None:
        return "—"
    if pt is None or pf == pt:
        return str(pf)
    return f"{pf}–{pt}"


def _split_headline_body(text: str) -> tuple[str, str]:
    sentences = _SENTENCE_SPLIT.split(text or "")
    headline = sentences[0].strip() if sentences and sentences[0] else (text or "").strip()
    body = " ".join(sentences[1:]).strip()
    return headline or "Unnamed note", body


def adapt(problem: dict, handled_status: dict[str, str]) -> dict:
    """Map one ``structured_problem`` → CriticNote dict."""
    nid = note_id(problem)
    headline, body = _split_headline_body(problem.get("text", ""))
    sug = _SUGGESTION_RE.search(problem.get("text", "") or "")
    bpm_diff = problem.get("bpm_diff") or 0
    severity = "fix" if bpm_diff >= _FIX_BPM_DIFF else "tip"
    status = handled_status.get(nid, "pending")
    return {
        "id": nid,
        "severity": severity,
        "target": _target(problem),
        "headline": headline,
        "body": body,
        "suggestion": sug.group(1).strip() if sug else None,
        "status": status,
    }


def to_critic_notes(
    problems: list[dict] | None,
    handled_status: dict[str, str] | None = None,
) -> list[dict]:
    """Adapt the full ``structured_problems`` list to CriticNote dicts."""
    if not problems:
        return []
    handled_status = handled_status or {}
    return [adapt(p, handled_status) for p in problems]
