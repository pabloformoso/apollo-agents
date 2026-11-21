import json
import time

import pytest
import respx
from mcp.server.mcpserver.exceptions import ToolError

from apollo_mcp.auth import Tokens
from apollo_mcp.client import decoded_take_path
from apollo_mcp.server import build_server

from .conftest import BASE, REALM, fake_jwt

FILE = "/v1/audio?path=%2Fhome%2Fp%2Fapi_audio%2Fa%2Bb.wav"
TASK_DONE = {
    "task_id": "t1", "status": "done", "eta_seconds": None, "degraded": False,
    "result_parse_error": None,
    "takes": [{"index": 0, "file": FILE, "prompt": "deep house", "lyrics": "[Instrumental]",
               "metas": {"bpm": 124, "keyscale": "A minor", "duration": 150}, "seed_value": "7"}],
}


def service(blocked=False):
    return {"state": "running", "ready": True, "loaded": True, "blocked_by_live": blocked,
            "can_manage": True, "pending_results": 0, "reason": None}


async def call(server, name, args=None):
    # SDK v2 raises a tool's ToolError out of call_tool; the protocol layer is
    # what turns it into an is_error result for the client. Same message.
    try:
        result = await server.call_tool(name, args or {})
    except ToolError as exc:
        raise RuntimeError(str(exc)) from exc
    text = "".join(getattr(c, "text", "") for c in result.content)
    if result.is_error if hasattr(result, "is_error") else result.isError:
        raise RuntimeError(text)
    structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if structured is not None:
        return structured.get("result", structured)
    return json.loads(text)


@pytest.fixture
def server(config, http, signed_in):
    return build_server(config, http)


async def test_only_the_intended_tools_exist(server):
    names = {t.name for t in await server.list_tools()}
    assert names == {
        "login_status", "apollo_status", "list_genres", "ace_service", "generate", "get_task",
        "wait_for_task", "download_take", "list_generations", "mark_take", "critique_take",
        "search_catalog", "list_sessions",
    }
    # The operator's token can do these; the MCP must have no path to them.
    for forbidden in ("publish", "edit", "live", "delete", "youtube"):
        assert not any(forbidden in n for n in names)


@respx.mock
async def test_generate_is_refused_on_air_before_reaching_ace(server):
    respx.get(BASE + "/api/generator/service").respond(200, json=service(blocked=True))
    tasks = respx.post(BASE + "/api/generator/tasks")
    with pytest.raises(RuntimeError, match="live set is on air"):
        await call(server, "generate", {"prompt": "x", "genre_folder": "techno"})
    assert not tasks.called


@respx.mock
async def test_generate_sends_only_what_was_given(server):
    respx.get(BASE + "/api/generator/service").respond(200, json=service())
    tasks = respx.post(BASE + "/api/generator/tasks").respond(
        200, json={"task_id": "t1", "queue_position": 1, "eta_seconds": 40})
    out = await call(server, "generate", {"prompt": "warm pads", "genre_folder": "deep house", "bpm": 124})
    assert out["task_id"] == "t1"
    assert json.loads(tasks.calls.last.request.content) == {
        "prompt": "warm pads", "genre_folder": "deep house", "lyrics": "[Instrumental]",
        "batch_size": 1, "bpm": 124,
    }


@respx.mock
async def test_backend_refusals_come_back_verbatim(server):
    respx.get(BASE + "/api/generator/service").respond(200, json=service())
    respx.post(BASE + "/api/generator/tasks").respond(422, json={"detail": "unknown genre_folder 'jazzz'"})
    with pytest.raises(RuntimeError, match="422: unknown genre_folder 'jazzz'"):
        await call(server, "generate", {"prompt": "x", "genre_folder": "jazzz"})


@respx.mock
async def test_ace_start_refused_on_air(server):
    respx.get(BASE + "/api/generator/service").respond(200, json=service(blocked=True))
    start = respx.post(BASE + "/api/generator/service/start")
    with pytest.raises(RuntimeError, match="live set is on air"):
        await call(server, "ace_service", {"action": "start"})
    assert not start.called


@respx.mock
async def test_get_task_decodes_the_take_path_once(server):
    respx.get(BASE + "/api/generator/tasks/t1").respond(200, json=TASK_DONE)
    out = await call(server, "get_task", {"task_id": "t1"})
    assert out["takes"][0]["path"] == "/home/p/api_audio/a+b.wav"
    assert out["takes"][0]["metas"]["keyscale"] == "A minor"


def test_decoded_take_path_keeps_plus_and_bare_paths():
    assert decoded_take_path(FILE) == "/home/p/api_audio/a+b.wav"
    assert decoded_take_path("/abs/take.wav") == "/abs/take.wav"


@respx.mock
async def test_download_take_streams_the_file_unrewritten(server, config):
    respx.get(BASE + "/api/generator/tasks/t1").respond(200, json=TASK_DONE)
    audio = respx.get(BASE + "/api/generator/audio").respond(
        200, content=b"RIFF....WAVE", headers={"content-type": "audio/wav"})
    out = await call(server, "download_take", {"task_id": "t1", "take_index": 0})
    assert audio.calls.last.request.url.params["path"] == FILE
    assert out["path"].endswith("t1__0.wav") and out["bytes"] == 12
    assert (config.download_dir / "t1__0.wav").read_bytes() == b"RIFF....WAVE"
    assert not list(config.download_dir.glob("*.part"))


@respx.mock
async def test_critique_sends_the_decoded_path_and_metas(server):
    respx.get(BASE + "/api/generator/service").respond(200, json={**service(), "state": "stopped"})
    respx.get(BASE + "/api/generator/tasks/t1").respond(200, json=TASK_DONE)
    crit = respx.post(BASE + "/api/generator/critique").respond(200, json={"passed": True})
    await call(server, "critique_take", {"task_id": "t1", "take_index": 0, "genre_folder": "deep house"})
    assert json.loads(crit.calls.last.request.content) == {
        "file": "/home/p/api_audio/a+b.wav",
        "metas": {"bpm": 124, "keyscale": "A minor", "duration": 150},
        "prompt": "deep house", "genre_folder": "deep house",
    }


@respx.mock
async def test_a_401_renews_the_token_once_and_retries(config, http, store):
    store.save(Tokens(apollo_token="revoked", apollo_exp=time.time() + 600,
                      refresh_token="r", refresh_exp=time.time() + 600))
    fresh = fake_jwt(sub="1", exp=time.time() + 604800)
    respx.post(REALM + "/token").respond(200, json={"access_token": "realm-at"})
    respx.post(BASE + "/api/auth/keycloak").respond(200, json={"access_token": fresh})
    genres = respx.get(BASE + "/api/generator/genres").mock(side_effect=[
        respx.MockResponse(401, json={"detail": "Invalid token"}),
        respx.MockResponse(200, json={"genres": [{"id": "techno"}]}),
    ])
    out = await call(build_server(config, http), "list_genres")
    assert out == [{"id": "techno"}]
    assert genres.calls[1].request.headers["authorization"] == f"Bearer {fresh}"


async def test_login_status_never_returns_the_token(server, signed_in):
    out = await call(server, "login_status")
    assert out["signed_in"] is True
    assert signed_in not in json.dumps(out)


async def test_unauthenticated_tool_says_how_to_sign_in(config, http):
    with pytest.raises(RuntimeError, match="apollo-mcp login"):
        await call(build_server(config, http), "list_genres")


@respx.mock
async def test_validation_errors_name_the_argument(server):
    respx.get(BASE + "/api/generator/service").respond(200, json=service())
    respx.post(BASE + "/api/generator/tasks").respond(422, json={"detail": [
        {"type": "greater_than_equal", "loc": ["body", "audio_duration"],
         "msg": "Input should be greater than or equal to 120", "input": 60.0}]})
    with pytest.raises(RuntimeError, match=r"422: audio_duration: Input should be greater than or equal to 120$"):
        await call(server, "generate", {"prompt": "x", "genre_folder": "deep house", "audio_duration": 60})


@respx.mock
async def test_critique_refused_while_ace_runs(server):
    # The critique's LLM read JIT-loads the main model beside ACE (seen on
    # prod 2026-11-21: gemma 4.7 GB next to ACE, next generate 409'd).
    respx.get(BASE + "/api/generator/service").respond(200, json=service())
    crit = respx.post(BASE + "/api/generator/critique")
    with pytest.raises(RuntimeError, match="ACE is running"):
        await call(server, "critique_take", {"task_id": "t1", "take_index": 0, "genre_folder": "deep house"})
    assert not crit.called
