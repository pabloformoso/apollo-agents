"""ApolloAgents web backend.

The repo root goes on ``sys.path`` HERE, before any submodule loads, because
the backend imports the top-level ``agent`` package and uvicorn does not put
the root there: prod and the E2E job run ``uvicorn backend.app:app --app-dir
web``, which only adds ``web/``. Until #234 this was done halfway down
``pipeline.py`` and worked by import order alone — ``app.py`` happened to
import nothing that needed ``agent`` before ``pipeline``. A module-level
``from agent import ...`` in ``covers`` (imported first) then crashed the
backend at startup while every pytest run, launched from the repo root,
passed. A package ``__init__`` runs before any of its submodules, so no
import order can undo this. ``tests/web/test_backend_import.py`` imports the
app the way uvicorn does.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_DIR = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)
