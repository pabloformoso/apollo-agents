"""G5a phase A: one REAL deep house release against ACE-Step, poll to done, persist.

The first rung of docs/acestep-wizard-plan.md's G5 runbook. Run from the
worktree root with the ACE server up (the ACE session's phase-A go):

    uv run python scripts/g5a_phase_a.py

Persists every take's URL-DECODED path + metas + prompt/lyrics to
output/g5a/takes.json THE MOMENT the poll returns done — the persistence
rule: ACE's job records are mortal, its files are not, and phase C runs
after their server stops.

Expect the FIRST poll stretch to take minutes: lazy-load pays the DiT +
5 Hz LM load on the first release after server start (ACE session,
2026-08-29). A slow first poll is the load, not a failure.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit, parse_qs

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

os.environ.setdefault("ACESTEP_BASE_URL", "http://100.68.5.104:8001")

from web.backend import acestep_client  # noqa: E402

OUT = REPO / "output" / "g5a"
POLL_SEC = 5.0
FIRST_POLL_BUDGET_SEC = 15 * 60   # lazy-load headroom
DONE_BUDGET_SEC = 30 * 60

RELEASE = {
    "prompt": ("deep house, warm rolling bassline, offbeat open hats, dusty "
               "rhodes stabs, hypnotic late-night groove, analog warmth"),
    "lyrics": "",
    "audio_duration": 180.0,
    "vocal_language": "en",
    "thinking": True,
    "bpm": 125,               # 'deep house' window center ((115+135)/2, agent/tools.py:99)
    "key_scale": "A Minor",   # 8A — catalog vocabulary
    "batch_size": 2,
    "audio_format": "wav",
}


def _decoded_path(file_field: str | None) -> str | None:
    """The take's `file` is `/v1/audio?path=<quote(p, safe='')>` — decode ONCE."""
    if not file_field:
        return None
    if file_field.startswith("/v1/audio"):
        qs = parse_qs(urlsplit(file_field).query)
        raw = qs.get("path", [None])[0]
        # parse_qs already unquotes once; ACE quotes once. Done.
        return raw
    return unquote(file_field)


async def main() -> int:
    client = acestep_client.AceStepClient()
    if not await client.health():
        print("ACE /health not answering — is the server up? (phase-A go required)")
        return 2
    try:
        stats = await client.stats()
        print(f"stats: {stats}")
    except Exception as exc:  # stats are a nicety, not a gate
        print(f"stats unavailable ({exc}) — continuing")

    rel = await client.release_task(dict(RELEASE))
    print(f"released: task_id={rel.task_id} queue_position={rel.queue_position}")
    t0 = time.monotonic()
    last_status = None
    while True:
        elapsed = time.monotonic() - t0
        if elapsed > DONE_BUDGET_SEC:
            print(f"[{elapsed:.0f}s] budget exhausted — aborting (task may still finish server-side)")
            return 3
        await asyncio.sleep(POLL_SEC)
        try:
            results = await client.query_result([rel.task_id])
        except acestep_client.AceStepError as exc:
            print(f"[{elapsed:.0f}s] poll blip: {exc}")
            continue
        if not results:
            print(f"[{elapsed:.0f}s] empty result list")
            continue
        task = results[0]
        if task.status != last_status:
            print(f"[{elapsed:.0f}s] status={task.status}")
            last_status = task.status
        if task.status == 2:
            print(f"FAILED server-side; result_parse_error={task.result_parse_error}")
            return 4
        if task.status == 1:
            takes = []
            for i, take in enumerate(task.takes):
                decoded = _decoded_path(take.file)
                takes.append({
                    "index": i,
                    "file_field": take.file,
                    "decoded_path": decoded,
                    "status": take.status,
                    "prompt": take.prompt,
                    "lyrics": take.lyrics,
                    "metas": take.metas,
                    "seed_value": take.seed_value,
                })
                print(f"take {i}: metas={take.metas} path={decoded}")
            OUT.mkdir(parents=True, exist_ok=True)
            payload = {
                "task_id": rel.task_id,
                "release": RELEASE,
                "completed_after_sec": round(elapsed, 1),
                "takes": takes,
            }
            out_file = OUT / "takes.json"
            out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"PERSISTED -> {out_file}  ({len(takes)} takes, {elapsed:.0f}s total)")
            return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
