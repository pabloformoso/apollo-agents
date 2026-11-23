"""The backend imports the way uvicorn imports it, not the way pytest does.

Prod and the E2E job start ``uvicorn backend.app:app --app-dir web``: ``web/``
is on ``sys.path`` and the repo root is not. Every other test runs from the
repo root, where ``agent`` is importable anyway, so a module-level
``from agent import ...`` that loads before the root is on the path passes the
whole suite and kills the backend at startup (#234: ``covers`` imported
``agent.tracing`` ahead of ``pipeline``, which used to add the root). This runs
the import in a clean interpreter from ``web/`` with the root kept out of
``PYTHONPATH``.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def test_backend_app_imports_from_web_without_the_repo_root_on_the_path():
    probe = (
        "import sys; root = sys.argv[1]; "
        "assert root not in sys.path, 'repo root already on sys.path: the test proves nothing'; "
        "import backend.app"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe, str(_ROOT)],
        cwd=_ROOT / "web",
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
