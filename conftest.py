"""Test-suite-wide isolation from the ambient environment.

This file exists because of a failure that looked like flakiness and was
not. Running the backend suite in a fresh worktree produced **357 errors**
at fixture setup (`KeyError: 'access_token'`) and 9 failures, the first of
them `assert 403 == 200` on `POST /api/auth/login`. The same numbers
appeared on a clean `origin/main`, so it read as pre-existing rot.

It was the environment. `agent/run.py:67` calls `load_dotenv()` at module
scope, and `web/backend/pipeline.py` imports `agent.run` — so importing the
pipeline loads a `.env`. With no `.env` beside the tests, `find_dotenv`
walks UP the directory tree; a git worktree lives at
`<repo>/.claude/worktrees/<name>`, so the walk reaches the MAIN CHECKOUT
and loads production's `.env`. The suite then ran against the real
Keycloak realm: `AUTH_MODE` derived to `keycloak`, local login started
answering 403, and every fixture that registers a user died.

The reason it had ever passed is worse than the bug: earlier worktrees
happened to contain an EMPTY `.env`, which `find_dotenv` found first and
which loaded nothing. The suite was green by accident of file layout.

So: pin what the suite depends on, before anything imports the app.
`load_dotenv()` does not override variables that are already set, which is
what makes setting them here sufficient — a later `.env` load cannot win.

It lives at the REPO ROOT, not under `tests/`, because pytest only applies
a `conftest.py` to directories beneath it and there are two test trees:
`tests/` (what CI runs) and `web/tests/`, which has its own conftest and
was showing 33 errors from the same cause. A copy in each would be two
places to forget.

This is the same discipline `tests/web/conftest.py:9` already applies to
`JWT_SECRET`, and the same rule two modules already enforce with tests of
their own (`tests/web/test_acestep_client.py:108`,
`tests/test_algorave_playground.py:686`, both asserting their module does
not call `load_dotenv` at import time). `agent/run.py` is the module that
does not follow it; fixing that is a separate change with real blast
radius, since the backend's provider selection reads the environment at
import.
"""
from __future__ import annotations

import os

#: Authentication must be deterministic and LOCAL for the suite.
#:
#: `APOLLO_AUTH_MODE` is read first by `web/backend/auth.py` and wins over
#: the derived default, so pinning it here neutralises any `KEYCLOAK_*`
#: that a stray `.env` brings in — without having to guess every variable
#: that might leak.
os.environ["APOLLO_AUTH_MODE"] = "local"

#: Deterministic secret, matching `tests/web/conftest.py`. Set here too so
#: suites outside `tests/web/` get it as well.
os.environ.setdefault("JWT_SECRET", "test-secret")

#: Never let a real provider be reachable from a test run. An ambient
#: `ACESTEP_BASE_URL` would point the generator suite at the actual
#: ACE-Step box; an ambient `OLLAMA_BASE_URL` would point agent tests at
#: a real LM Studio. Both are read at CALL time by design, so clearing
#: them here is enough and does not need an import-order argument.
for _leaky in ("ACESTEP_BASE_URL", "ACESTEP_API_KEY", "ACESTEP_AUDIO_ROOT"):
    os.environ.pop(_leaky, None)
