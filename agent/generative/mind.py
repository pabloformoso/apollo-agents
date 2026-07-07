"""Slow plane: musical state + intent -> next pattern-spec + reason (C-2).

One completion call per phrase boundary — no tool loop, no streaming.
Provider detection mirrors agent/run.py (anthropic / azure / ollama from
env) but is re-implemented here as a single-completion helper so importing
the generative package never drags in the full agent stack.

Reject-and-hold (FS3): if the LLM output fails validation we retry ONCE
with the validation error appended; if that fails too, MindError propagates
and the caller keeps looping the previous spec. Audio never stops for a
bad idea.
"""

from __future__ import annotations

import json
import os
import re

from .spec import (
    ALLOWED_ROLES,
    BARS_MAX,
    BPM_MAX,
    BPM_MIN,
    NAMED_PATTERNS,
    PatternSpec,
    SpecError,
)
from .state import to_prompt


class MindError(RuntimeError):
    """The slow plane failed to produce a valid spec. Caller must hold."""


SYSTEM_PROMPT = f"""You are the mind of a live generative MIDI engine performing electronic music.
At each phrase boundary you receive the current musical state and a standing human intent,
and you output the pattern-spec for the NEXT phrase.

Output ONLY a JSON object (no prose, no markdown fences) with this exact shape:
{{
  "for_bars": <int 1-{BARS_MAX}>,
  "bpm": <float {BPM_MIN:g}-{BPM_MAX:g}>,
  "key": "<Camelot key, e.g. 8A>",
  "roles": {{
    "kick":  {{"pattern": "<steps>", "vel": <1-127>, "density": <0.0-1.0, optional>, "fill": "none|auto"}},
    "snare": {{"pattern": "<steps>", "vel": <1-127>, "density": ..., "fill": ...}},
    "hats":  {{"pattern": "<steps>", "vel": <1-127>, "swing": <0.0-0.5>, "density": ..., "fill": ...}},
    "perc":  {{"pattern": "<steps>", "vel": <1-127>}},   // rimshot; also: "shaker", "clap"
    "bass":  {{"notes": [[<step 0-15>, "<note e.g. A1>", <beats>], ...], "vel": <1-127>}},
    "pad":   {{"progression": [[<bar, first must be 0>, "<chord e.g. Am9>"], [4, "Fmaj7"], ...],
               "voicing": "close|wide", "hold": <true = sustain until next change, false = retrigger each bar>,
               "vel": <1-127>}},
    "controls": {{"ramps": [{{"cc": <0-127>, "from": <0.0-1.0>, "to": <0.0-1.0>,
                              "start_bar": <0-based bar>, "over_bars": <int>}}, ...]}}
  }},
  "feel": {{"timing_slop": <0.0-1.0>, "ghost_notes": <0.0-1.0>}},
  "reason": "<one sentence: the musical WHY of this phrase>",
  "rethink_in_bars": <int, usually equal to for_bars>
}}

Rules:
- Allowed roles: {", ".join(ALLOWED_ROLES)}. Include only the roles you want playing; omitting a role silences it.
- Drum "pattern" is a step string over a 16th-note grid using x (hit), X (accent), . (rest);
  length 4, 8 or 16; or a named pattern: {", ".join(sorted(NAMED_PATTERNS))}.
- The pad progression is voice-led automatically (minimal movement between chords) — think in
  chord names, not voicings. Use "hold": true for sustained, breathing harmony (ambient/lofi);
  false for stabbed/retriggered chords. Change chords every 2-4 bars for movement.
- "density" scales a drum pattern up or down WITHOUT rewriting it: the written pattern is
  the skeleton; lower density thins it (weakest beats first), higher adds in-grid
  embellishments. Prefer moving density over rewriting patterns when the intent is
  more/less busy. "fill": "auto" adds a deterministic variation in the phrase's last bar
  — use it going into a section change.
- "feel" is optional performance imperfection: timing_slop drifts snare/hats off the grid
  (the kick never drifts), ghost_notes adds quiet extra hits. Lofi wants both high
  (0.4-0.7); precise genres (techno, deep house) want 0.
- "controls" is optional timbral automation over Surge macros: CC 41 = energy, CC 42 = brightness,
  CC 43 = space (reverb/send), CC 44 = motion (LFO depth). Use slow ramps (2-8 bars) for builds
  and breakdowns — e.g. open CC 42 from 0.3 to 0.9 over the phrase into a peak, or push CC 43
  up while thinning the drums for a washed-out breakdown. Values are normalized 0.0-1.0.
- Keep bpm and key stable unless the intent demands a change; evolve gradually, phrase by phrase.
- Respect the standing intent above all. "darker" -> lower velocities, sparser hats, minor colors.
  "build"/"lift" -> add density, open the hats, raise velocities toward a peak.
- If the state carries an "arc", you are inside that section: steer energy and density
  toward its targets (density dials and velocities before pattern rewrites), and prepare
  the transition when section_phrase approaches its end (a fill, a CC swell).
- Do not repeat the recent reasons — if the state shows a plateau, change something meaningful.
- The "reason" must state a concrete musical decision, not a vibe description.
- All bass notes and chord tones must belong to the Camelot key's scale (minor keys also
  allow the raised 7th). To go outside it deliberately, set "chromatic": true at the top
  level AND justify the color in "reason" — otherwise the spec is rejected.
"""


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM reply (tolerates fences/prose)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = text.find("{")
        if start == -1:
            raise MindError(f"no JSON object in LLM reply: {text[:200]!r}")
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    break
        else:
            raise MindError("unbalanced JSON object in LLM reply")
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise MindError(f"invalid JSON from LLM: {exc}") from exc


def _default_llm(system: str, user: str) -> str:
    """Single completion against whichever provider the env has wired.

    Mirrors agent/run.py's detection order: ANTHROPIC_API_KEY ->
    AZURE_OPENAI_API_KEY -> Ollama.
    """
    provider = os.getenv("AGENT_PROVIDER", "")
    if not provider:
        if os.getenv("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif os.getenv("AZURE_OPENAI_API_KEY"):
            provider = "azure"
        else:
            provider = "ollama"

    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic()
        model = os.getenv("AGENT_MODEL", "claude-opus-4-6")
        resp = client.messages.create(
            model=model, max_tokens=2048, system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if hasattr(b, "text"))

    if provider == "azure":
        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        )
        model = os.getenv("AGENT_MODEL", os.getenv("AZURE_OPENAI_DEPLOYMENT", ""))
    else:  # ollama
        from openai import OpenAI
        client = OpenAI(base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
                        api_key="ollama")
        model = os.getenv("AGENT_MODEL", "gemma4:4b")

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return resp.choices[0].message.content or ""


class Mind:
    """state + intent -> validated PatternSpec. llm is injectable for tests.

    genre: key into genres.GENRE_PACKS — appends the genre brief + few-shot
    example to the system prompt so every phrase stays in idiom (M-6).
    """

    def __init__(self, llm=None, genre: str | None = None):
        self._llm = llm or _default_llm
        self._system = SYSTEM_PROMPT
        if genre:
            from .genres import genre_prompt_section
            self._system = SYSTEM_PROMPT + genre_prompt_section(genre)

    def next_spec(self, state: dict, intent: str) -> PatternSpec:
        user = (
            f"Current musical state:\n{to_prompt(state)}\n\n"
            f"Standing intent: {intent.strip() or 'none'}\n\n"
            "Produce the pattern-spec for the next phrase."
        )
        raw = self._llm(self._system, user)
        try:
            return PatternSpec.from_dict(_extract_json(raw))
        except (SpecError, MindError) as first_err:
            retry = (
                f"{user}\n\nYour previous reply was rejected: {first_err}\n"
                "Reply again with ONLY a valid JSON pattern-spec."
            )
            raw = self._llm(self._system, retry)
            try:
                return PatternSpec.from_dict(_extract_json(raw))
            except (SpecError, MindError) as second_err:
                raise MindError(
                    f"slow plane failed twice — holding current spec ({second_err})"
                ) from second_err
