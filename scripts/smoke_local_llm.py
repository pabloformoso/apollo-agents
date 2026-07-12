"""Smoke-test a local OpenAI-compatible LLM server (LM Studio / Ollama)
against the three workloads the live DJ actually runs.

Usage:
    uv run python scripts/smoke_local_llm.py
    uv run python scripts/smoke_local_llm.py --base-url http://192.168.1.72:1234/v1
    uv run python scripts/smoke_local_llm.py --models qwen/qwen3.5-9b

Workloads per model:
  1. greeting   — short Spanish on-stream greeting (pure text, the
                  chat_greeting overlay path).
  2. tool call  — PLAYLIST_RUNNING_LOW turn with the real ``extend_set``
                  schema shape; the model must answer with a syntactically
                  valid tool call naming an in-catalog track id.
  3. latency    — wall-clock per call, judged against the live budget:
                  the poke fires ~30 s before the crossfade point and the
                  deterministic fallback takes over after 5 s grace, so a
                  useful DJ must land tool calls well under ~20 s.

Prints a verdict table. Exit code 0 if at least one model passes the
tool-call test inside budget, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from openai import OpenAI

# Mirrors the extend_set schema the schema-builder derives from
# agent/tools.py (list params travel as JSON strings by convention).
EXTEND_SET_TOOL = {
    "type": "function",
    "function": {
        "name": "extend_set",
        "description": (
            "Append a track to the END of the live playlist. Use when the "
            "playlist is running low and the set should continue."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "track_id": {
                    "type": "string",
                    "description": "Catalog id of the track to append.",
                }
            },
            "required": ["track_id"],
        },
    },
}

# A miniature in-genre catalog so the tool test has real ids to pick from.
FAKE_CATALOG = [
    {"id": "lofi-a-calm-pages", "display_name": "Calm Pages", "bpm": 74, "camelot_key": "8A"},
    {"id": "lofi-b-dust-motes", "display_name": "Dust Motes", "bpm": 76, "camelot_key": "9A"},
    {"id": "lofi-c-slow-ink", "display_name": "Slow Ink", "bpm": 75, "camelot_key": "8B"},
]

GREETING_SYSTEM = (
    "Eres el DJ de un canal de lofi 24/7 en YouTube. Saludas con calidez, "
    "en una frase corta (max 20 palabras), en espanol, mencionando al "
    "usuario por su nombre. Sin hashtags, sin emojis repetidos."
)

TOOL_SYSTEM = (
    "You are a live DJ controlling a music engine via tools. The playlist "
    "is running low. You MUST call extend_set with the id of the best "
    "harmonic continuation from the candidate list. Current track: 75 BPM, "
    "key 8A. Candidates:\n"
    + "\n".join(
        f"- id={t['id']!r} name={t['display_name']!r} bpm={t['bpm']} key={t['camelot_key']}"
        for t in FAKE_CATALOG
    )
)

TOOL_BUDGET_SEC = 20.0


def run_greeting(client: OpenAI, model: str) -> tuple[bool, float, str]:
    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": GREETING_SYSTEM},
            {"role": "user", "content": "[YT @marta_lofi] hola!! primera vez por aqui"},
        ],
        max_tokens=2048,
        temperature=0.7,
    )
    dt = time.perf_counter() - t0
    text = (resp.choices[0].message.content or "").strip()
    ok = bool(text) and "marta" in text.lower()
    return ok, dt, text[:90]


def run_tool_call(client: OpenAI, model: str) -> tuple[bool, float, str]:
    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": TOOL_SYSTEM},
            {
                "role": "user",
                "content": (
                    "PLAYLIST_RUNNING_LOW: 29.9s to crossfade. Pick a "
                    "continuation NOW via extend_set."
                ),
            },
        ],
        tools=[EXTEND_SET_TOOL],
        max_tokens=2048,
        temperature=0.2,
    )
    dt = time.perf_counter() - t0
    calls = resp.choices[0].message.tool_calls or []
    if not calls:
        return False, dt, "no tool_calls in response"
    call = calls[0]
    if call.function.name != "extend_set":
        return False, dt, f"wrong tool: {call.function.name}"
    try:
        args = json.loads(call.function.arguments or "{}")
    except json.JSONDecodeError as exc:
        return False, dt, f"unparseable arguments: {exc}"
    tid = args.get("track_id")
    valid_ids = {t["id"] for t in FAKE_CATALOG}
    if tid not in valid_ids:
        return False, dt, f"hallucinated track_id: {tid!r}"
    return True, dt, f"extend_set({tid!r})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://localhost:1234/v1",
        help="OpenAI-compatible endpoint (LM Studio default port 1234).",
    )
    parser.add_argument(
        "--models",
        nargs="*",
        default=None,
        help="Model ids to test. Default: every non-embedding model served.",
    )
    args = parser.parse_args()

    client = OpenAI(base_url=args.base_url, api_key="lm-studio", timeout=120.0)

    models = args.models
    if not models:
        served = client.models.list()
        models = [m.id for m in served.data if "embed" not in m.id.lower()]
    if not models:
        print("No models served — load one in LM Studio first.")
        return 1

    print(f"endpoint: {args.base_url}")
    print(f"tool-call budget: {TOOL_BUDGET_SEC:.0f}s (poke-to-fallback window)\n")

    any_tool_pass = False
    for model in models:
        print(f"== {model} " + "=" * max(0, 58 - len(model)))
        try:
            g_ok, g_dt, g_out = run_greeting(client, model)
        except Exception as exc:  # noqa: BLE001 — smoke must report, not crash
            g_ok, g_dt, g_out = False, 0.0, f"ERROR: {type(exc).__name__}: {exc}"
        print(f"  greeting  {'PASS' if g_ok else 'FAIL'}  {g_dt:6.1f}s  {g_out}")

        try:
            t_ok, t_dt, t_out = run_tool_call(client, model)
        except Exception as exc:  # noqa: BLE001
            t_ok, t_dt, t_out = False, 0.0, f"ERROR: {type(exc).__name__}: {exc}"
        in_budget = t_ok and t_dt <= TOOL_BUDGET_SEC
        verdict = "PASS" if in_budget else ("SLOW" if t_ok else "FAIL")
        print(f"  tool call {verdict}  {t_dt:6.1f}s  {t_out}")
        if in_budget:
            any_tool_pass = True
        print()

    if any_tool_pass:
        print("VERDICT: at least one model is live-DJ capable (tools in budget).")
        return 0
    print("VERDICT: no model passed tool calling in budget — text-only roles only.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
