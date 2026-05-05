"""Tests for GET /api/tracks/{track_id}/stream — Range/206, content-types,
auth, path-traversal, unknown ids."""
from __future__ import annotations


def _stream_url(track_id: str, token: str) -> str:
    return f"/api/tracks/{track_id}/stream?token={token}"


def test_stream_returns_206_for_range_request(stream_env, auth_client, auth_token):
    track_id = stream_env["wav_track"]["id"]
    r = auth_client.get(
        _stream_url(track_id, auth_token),
        headers={"Range": "bytes=0-1023"},
    )
    assert r.status_code == 206
    assert "content-range" in {k.lower() for k in r.headers}
    # Content-Range looks like "bytes 0-1023/<total>"
    cr = r.headers.get("content-range") or r.headers.get("Content-Range")
    assert cr.startswith("bytes 0-")
    assert len(r.content) == 1024 or len(r.content) == stream_env["wav_size"]


def test_stream_returns_full_for_no_range(stream_env, auth_client, auth_token):
    track_id = stream_env["wav_track"]["id"]
    r = auth_client.get(_stream_url(track_id, auth_token))
    assert r.status_code == 200
    assert len(r.content) == stream_env["wav_size"]


def test_stream_rejects_invalid_token(stream_env, auth_client):
    track_id = stream_env["wav_track"]["id"]
    r = auth_client.get(_stream_url(track_id, "garbage-token"))
    assert r.status_code in (401, 403)


def test_stream_rejects_path_traversal(stream_env, auth_client, auth_token):
    # An invented track_id whose `file` would point outside tracks/ is the
    # only way to trigger the traversal guard via the public API. Since our
    # fake catalog only contains real ids, just verify the unknown id 404s
    # (path-traversal defence is documented; the regression tests for the
    # guard live as an inline assertion on the resolver).
    r = auth_client.get(_stream_url("nonexistent-id-../../../etc-passwd", auth_token))
    assert r.status_code == 404


def test_stream_path_traversal_outside_tracks(stream_env, auth_client, auth_token, monkeypatch):
    """Inject a malicious catalog entry whose `file` escapes tracks/ and
    confirm the resolver rejects it with 404 (not 200, not 500)."""
    from web.backend import pipeline

    bad_track = dict(stream_env["wav_track"])
    bad_track["id"] = "bad-traversal"
    bad_track["file"] = "../etc/passwd"

    def malicious_load(genre=None):
        return [bad_track], ["lofi"]

    monkeypatch.setattr(pipeline, "load_catalog", malicious_load)
    r = auth_client.get(_stream_url("bad-traversal", auth_token))
    assert r.status_code == 404


def test_stream_unknown_track_id(stream_env, auth_client, auth_token):
    r = auth_client.get(_stream_url("does-not-exist", auth_token))
    assert r.status_code == 404


def test_stream_wav_content_type(stream_env, auth_client, auth_token):
    track_id = stream_env["wav_track"]["id"]
    r = auth_client.get(_stream_url(track_id, auth_token))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/wav") or r.headers[
        "content-type"
    ].startswith("audio/x-wav")


def test_stream_mp3_content_type(stream_env, auth_client, auth_token):
    track_id = stream_env["mp3_track"]["id"]
    r = auth_client.get(_stream_url(track_id, auth_token))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/mpeg")


def test_stream_rejects_unsupported_extension(stream_env, auth_client, auth_token, monkeypatch):
    """A catalog entry that points at e.g. a .flac file must 415, not 500."""
    from web.backend import pipeline

    flac_path = stream_env["tmp_root"] / "tracks" / "lofi" / "silence.flac"
    flac_path.write_bytes(b"\x00\x00\x00\x00")
    bad = dict(stream_env["wav_track"])
    bad["id"] = "flac-track"
    bad["file"] = str(flac_path.relative_to(stream_env["tmp_root"])).replace("\\", "/")

    def lc(genre=None):
        return [bad], ["lofi"]

    monkeypatch.setattr(pipeline, "load_catalog", lc)
    r = auth_client.get(_stream_url("flac-track", auth_token))
    assert r.status_code == 415
