"""Shared fixtures for v2.0 web backend tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Deterministic JWT secret for all tests
os.environ.setdefault("JWT_SECRET", "test-secret")

# Make the project root importable so "from web.backend..." works
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolated_main_llm_settings(tmp_path, monkeypatch):
    """Never let the checkout's persisted main-LLM choice leak into a test.

    ``main_llm.persisted_model()`` sits in the model precedence of the brief
    parser, the planner and the critic, and it reads ``.tmp/`` under the repo
    root — which in the main checkout holds whatever an administrator last
    saved. Both the current and the legacy path are pointed at this test's
    own directory; a test that wants a saved choice writes one itself.
    """
    monkeypatch.setenv("APOLLO_MAIN_LLM_SETTINGS_PATH", str(tmp_path / "main-llm-settings.json"))
    monkeypatch.setenv("APOLLO_SESSION_MODEL_SETTINGS_PATH", str(tmp_path / "session-model-settings.json"))


@pytest.fixture(autouse=True)
def no_host_controller(monkeypatch):
    """Tests run as CI does: no ACE host controller configured.

    The backend loads ``.env`` at import, and ``find_dotenv`` walks UP from
    the source file — so a worktree under ``.claude/worktrees/`` inherits
    the main checkout's ``.env``, ``ACESTEP_CONTROL_URL`` included. With it
    set, every generation release calls a controller that is not there
    (503) and ``/api/generator/service`` reports itself configured: 163
    failures that CI never sees (2026-09-20). A test that wants the
    controller sets the variable itself, after this runs.
    """
    monkeypatch.delenv("ACESTEP_CONTROL_URL", raising=False)
    monkeypatch.delenv("ACESTEP_CONTROL_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def no_image_api(monkeypatch):
    """No test may buy a DALL·E image.

    Publishing a take and releasing a generation both schedule a cover in
    the background, and ``main._generate_artwork`` is gated on these two
    variables. A developer box that exports them would otherwise have the
    publish and library suites issuing real Azure image calls.
    """
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_IMAGE_DEPLOYMENT", raising=False)
    monkeypatch.delenv("APOLLO_COVER_PROMPT_DEPLOYMENT", raising=False)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Point the user DB at an isolated temp file and initialise schema."""
    from web.backend import db

    test_db = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_db()
    yield test_db


@pytest.fixture
def client(tmp_db):
    """FastAPI TestClient against an isolated DB and empty session store."""
    from web.backend.app import app
    from web.backend.session_store import store

    # Reset cache (and its "loaded from DB" flag) so the store re-reads from
    # the per-test tmp DB instead of whatever prior tests wrote.
    store._reset()
    return TestClient(app)


@pytest.fixture
def second_client(tmp_db):
    """Independent TestClient (so two-user tests don't share headers)."""
    from web.backend.app import app

    return TestClient(app)


@pytest.fixture
def auth_client(client):
    """TestClient with an already-registered user and bearer token set."""
    client.post(
        "/api/auth/register",
        json={"username": "u1", "email": "u1@test.io", "password": "pw12345"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"username": "u1", "password": "pw12345"},
    )
    token = resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    client.auth_token = token  # type: ignore[attr-defined]
    return client


@pytest.fixture
def auth_token(auth_client):
    """Raw bearer token (for WebSocket query-string auth)."""
    return auth_client.auth_token  # type: ignore[attr-defined]


@pytest.fixture
def mock_pipeline(monkeypatch):
    """Stub every async pipeline phase with the shared deterministic fakes."""
    from web.backend import mock_pipeline as fakes
    from web.backend import pipeline

    monkeypatch.setattr(pipeline, "phase_genre_guard", fakes.fake_genre)
    monkeypatch.setattr(pipeline, "phase_plan", fakes.fake_plan)
    monkeypatch.setattr(pipeline, "phase_critique", fakes.fake_critique)
    monkeypatch.setattr(pipeline, "phase_editor", fakes.fake_editor)
    monkeypatch.setattr(pipeline, "phase_validate", fakes.fake_validate)
    monkeypatch.setattr(pipeline, "phase_live", fakes.fake_phase_live)
    monkeypatch.setattr(pipeline, "load_memory", fakes.fake_memory)
    monkeypatch.setattr(pipeline, "write_session_record", fakes.fake_write)
    monkeypatch.setattr(pipeline, "check_catalog", fakes.fake_check_catalog)

    # v3.6.2 — the live WS handler validates the session playlist
    # against ``load_catalog`` before starting the engine. Tests seed
    # playlists with ids t1/t2 (see ``_seed_playlist``), so the fake
    # catalog must contain them; without this stub the handler would
    # read the developer's REAL tracks.json (or CatalogUnavailable in
    # CI) and the seeded tracks would be dropped as stale.
    def fake_load_catalog(genre=None):
        tracks = [
            {"id": "t1", "display_name": "Track One", "bpm": 124.0,
             "camelot_key": "8A", "duration_sec": 30.0, "hot_cues": [],
             "genre_folder": "techno"},
            {"id": "t2", "display_name": "Track Two", "bpm": 126.0,
             "camelot_key": "9A", "duration_sec": 30.0, "hot_cues": [],
             "genre_folder": "techno"},
            {"id": "t3", "display_name": "Track Three", "bpm": 125.0,
             "camelot_key": "8B", "duration_sec": 30.0, "hot_cues": [],
             "genre_folder": "techno"},
        ]
        return tracks, ["techno"]

    monkeypatch.setattr(pipeline, "load_catalog", fake_load_catalog)
    return pipeline
