"""Azure OpenAI smoke test — run after switching from direct OpenAI.

Verifies all three call sites in the codebase still work end-to-end against
the live Azure resource described in .env:

  1. agent/run.py chat path        → AzureOpenAI().chat.completions.create
  2. main.py disambiguation path   → AzureOpenAI().chat.completions.create (JSON)
  3. main.py artwork path          → AzureOpenAI().images.generate

Usage (from the main checkout, since worktrees lack tracks/.env/venv):
    uv run python scripts/smoke_azure.py

The script never prints API keys — only OK/FAIL per component and a short
preview of the model's response.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running from a worktree by loading the main checkout's .env explicitly
# (no-op when the main .env already lives next to this script).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
_MAIN_ENV = Path(r"C:\Users\pablo\Documents\GitHub\apollo-agents\.env")
if _MAIN_ENV.exists():
    load_dotenv(_MAIN_ENV)
else:
    load_dotenv()


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def _ok(msg: str) -> None:
    print(f"  OK  {msg}")


def _fail(msg: str, exc: Exception | None = None) -> None:
    print(f"  FAIL  {msg}")
    if exc is not None:
        print(f"        {type(exc).__name__}: {exc}")


def smoke_chat() -> bool:
    _section("Chat — AzureOpenAI().chat.completions.create")
    try:
        from main import _build_azure_chat_client
        client = _build_azure_chat_client()
        deploy = os.environ["AZURE_OPENAI_DEPLOYMENT"]
        resp = client.chat.completions.create(
            model=deploy,
            messages=[
                {"role": "system", "content": "Reply with one word."},
                {"role": "user", "content": "Say 'pong'."},
            ],
            max_tokens=5,
        )
        text = (resp.choices[0].message.content or "").strip()
        _ok(f"deployment='{deploy}' replied: {text!r}")
        return True
    except Exception as e:
        _fail("chat call raised", e)
        return False


def smoke_disambiguation_json() -> bool:
    _section("Disambiguation — JSON-mode chat")
    try:
        from main import _build_azure_chat_client
        client = _build_azure_chat_client()
        deploy = os.environ["AZURE_OPENAI_DEPLOYMENT"]
        resp = client.chat.completions.create(
            model=deploy,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": 'Return {"status":"ok"}.'},
            ],
            max_tokens=20,
        )
        text = (resp.choices[0].message.content or "").strip()
        _ok(f"JSON reply: {text}")
        return True
    except Exception as e:
        _fail("json-mode call raised", e)
        return False


def smoke_image() -> bool:
    _section("Image — AzureOpenAI().images.generate")
    if not os.getenv("AZURE_OPENAI_IMAGE_DEPLOYMENT"):
        print("  SKIP  AZURE_OPENAI_IMAGE_DEPLOYMENT not set")
        return True
    try:
        from main import _build_azure_image_client, _decode_image_response, ARTWORK_API_SIZE
        client = _build_azure_image_client()
        deploy = os.environ["AZURE_OPENAI_IMAGE_DEPLOYMENT"]
        resp = client.images.generate(
            model=deploy,
            prompt="A tiny abstract square of muted teal — smoke test artwork.",
            size=ARTWORK_API_SIZE,
            n=1,
        )
        image_bytes = _decode_image_response(resp)
        out_path = _PROJECT_ROOT / "artwork" / "_smoke_azure.png"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(image_bytes)
        _ok(f"image deployment='{deploy}' → {len(image_bytes)} bytes saved to {out_path}")
        return True
    except Exception as e:
        _fail("image call raised", e)
        return False


def main() -> int:
    results = {
        "chat": smoke_chat(),
        "json": smoke_disambiguation_json(),
        "image": smoke_image(),
    }
    _section("Summary")
    for name, ok in results.items():
        print(f"  {name:8s} {'OK' if ok else 'FAIL'}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
