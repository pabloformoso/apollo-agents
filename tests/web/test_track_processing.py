import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent.eligibility import is_session_eligible, ineligibility_reason
from web.backend import auth, permissions, track_processing as jobs


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    path = tmp_path / "tracks.json"
    path.write_text(json.dumps({"extra": "preserved", "tracks": [
        {"id": "new", "file": "tracks/new.wav", "processing_status": "queued"},
        {"id": "legacy", "file": "tracks/old.wav"},
    ]}))
    monkeypatch.setattr(jobs, "CATALOG_PATH", path)
    return path


def test_claim_finish_preserves_other_publications(catalog):
    assert jobs.claim()["id"] == "new"
    assert jobs.claim() is None
    current = json.loads(catalog.read_text())
    current["tracks"].append({"id": "another-publication"})
    catalog.write_text(json.dumps(current))
    jobs.finish("new", {"processing_status": "ready", "duration_sec": 180})
    result = json.loads(catalog.read_text())
    assert result["extra"] == "preserved"
    assert result["tracks"][-1]["id"] == "another-publication"
    assert jobs.snapshot("new")["status"] == "ready"


def test_restart_recovers_running_not_failed(catalog):
    jobs.claim()
    jobs.recover()
    assert jobs.snapshot("new")["status"] == "queued"
    jobs.finish("new", {"processing_status": "failed", "processing_error": "bad audio"})
    jobs.recover()
    assert jobs.snapshot("new")["status"] == "failed"
    assert jobs.enqueue("new")["status"] == "queued"
    assert jobs.snapshot("new")["error"] is None


def test_legacy_requires_explicit_prepare_and_enqueue_is_idempotent(catalog):
    assert jobs.snapshot("legacy")["status"] == "unprepared"
    assert jobs.enqueue("legacy")["status"] == "queued"
    assert jobs.enqueue("legacy")["status"] == "queued"
    jobs.finish("new", {"processing_status": "ready"})
    assert jobs.enqueue("new")["status"] == "ready"


@pytest.mark.parametrize("state", ["queued", "running", "failed", "unexpected"])
def test_unprepared_track_cannot_enter_session(state):
    track = {"duration_sec": 180, "processing_status": state}
    assert not is_session_eligible(track)
    assert "preparation" in ineligibility_reason(track)


def test_legacy_eligibility_unchanged():
    assert is_session_eligible({})
    assert is_session_eligible({"duration_sec": 180, "processing_status": "ready"})


def test_routes_permissions_and_not_found(auth_client, catalog):
    assert auth_client.get("/api/generator/tracks/new/processing").json()["status"] == "queued"
    assert auth_client.get("/api/generator/tracks/missing/processing").status_code == 404
    assert auth_client.post("/api/generator/tracks/legacy/processing").status_code == 200
    token = auth.create_access_token({"sub": "1", "caps": list(permissions.BASE_CAPABILITIES)})
    assert auth_client.post("/api/generator/tracks/legacy/processing", headers={"Authorization": "Bearer " + token}).status_code == 403
    assert auth_client.get("/api/generator/tracks/new/processing", headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_ingest_marks_queue_before_catalog_write():
    def fake(*args, **kwargs):
        assert kwargs["prepare_for_sessions"] is True
        return {"id": "new"}
    assert jobs.ingest(fake)["id"] == "new"


@pytest.mark.asyncio
async def test_worker_success_failure_and_live_guard(catalog, monkeypatch):
    from web.backend import generator
    monkeypatch.setattr(generator, "live_session_active", lambda: True)
    analyse = AsyncMock(return_value={"duration_sec": 180})
    monkeypatch.setattr(jobs, "analyse", analyse)
    assert not await jobs.process_one()
    analyse.assert_not_called()
    monkeypatch.setattr(generator, "live_session_active", lambda: False)
    assert await jobs.process_one()
    assert jobs.snapshot("new")["status"] == "ready"
    jobs.enqueue("legacy")
    analyse.side_effect = RuntimeError("missing madmom")
    assert await jobs.process_one()
    assert jobs.snapshot("legacy") == {"track_id": "legacy", "status": "failed", "error": "missing madmom"}


@pytest.mark.asyncio
async def test_cancel_requeues(catalog, monkeypatch):
    monkeypatch.setattr(jobs, "analyse", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await jobs.process_one()
    assert jobs.snapshot("new")["status"] == "queued"


@pytest.mark.asyncio
async def test_source_must_be_local_catalog_audio():
    with pytest.raises(RuntimeError, match="outside tracks"):
        await jobs.analyse({"file": "/etc/passwd"})


@pytest.mark.asyncio
async def test_worker_lifecycle_recovers_and_stops(catalog, monkeypatch):
    jobs.claim()
    called = asyncio.Event()
    async def idle():
        called.set()
        return False
    monkeypatch.setattr(jobs, "process_one", idle)
    async with jobs.worker():
        await asyncio.wait_for(called.wait(), 2)
        assert jobs.snapshot("new")["status"] == "queued"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["success", "failure", "timeout"])
async def test_analysis_subprocess_is_bounded(tmp_path, monkeypatch, mode):
    monkeypatch.chdir(tmp_path)
    Path("tracks").mkdir()
    Path("tracks/test.wav").touch()
    real_spawn = asyncio.create_subprocess_exec
    children = []
    async def spawn(*args, **kwargs):
        assert args[:3] == (sys.executable, "-m", "web.backend.track_analysis")
        script = "import time; time.sleep(30)" if mode == "timeout" else (
            "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(" +
            repr(json.dumps({"error": "analysis failed"} if mode == "failure" else {"duration_sec": 180})) + ")"
        )
        child = await real_spawn(sys.executable, "-c", script, args[-1], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(jobs, "ANALYSIS_TIMEOUT_SECONDS", 0.1 if mode == "timeout" else 3)
    if mode == "success":
        assert await jobs.analyse({"file": "tracks/test.wav", "bpm": 120}) == {"duration_sec": 180}
    else:
        with pytest.raises(TimeoutError if mode == "timeout" else RuntimeError):
            await jobs.analyse({"file": "tracks/test.wav", "bpm": 120})
    assert children[0].returncode is not None
