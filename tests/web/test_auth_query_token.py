"""Unit tests for ``web.backend.auth.user_from_query_token`` — the v2.6.0
helper that decodes a JWT carried as a query-string parameter (used by
WebSocket handlers, SSE streams, and download endpoints that can't set
the ``Authorization`` header from the browser)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from web.backend import auth


def _register_and_get_token(client: TestClient, username: str = "qtu") -> tuple[str, int]:
    """Register a fresh user and return ``(token, user_id)``."""
    client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@t.io", "password": "pw12345"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": "pw12345"},
    ).json()
    return resp["access_token"], resp["user"]["id"]


def test_returns_user_dict_for_valid_token(client):
    token, uid = _register_and_get_token(client)
    user = auth.user_from_query_token(token)
    assert user is not None
    assert user["id"] == uid
    assert user["username"] == "qtu"


def test_returns_none_for_empty_token(client):
    assert auth.user_from_query_token("") is None


def test_returns_none_for_garbage_token(client):
    assert auth.user_from_query_token("not-a-jwt-at-all") is None


def test_returns_none_for_token_signed_by_other_secret(client, monkeypatch):
    token, _ = _register_and_get_token(client)
    # Rotate the secret AFTER issuing — the previously valid token now
    # fails signature verification and should return None.
    monkeypatch.setattr(auth, "SECRET_KEY", "different-secret-entirely")
    assert auth.user_from_query_token(token) is None


def test_returns_none_when_user_no_longer_exists(client, monkeypatch):
    """JWT decodes cleanly but the user has since been deleted."""
    token, uid = _register_and_get_token(client)
    # Patch the user lookup to behave as if the user was removed.
    from web.backend import db
    monkeypatch.setattr(db, "get_user_by_id", lambda _id: None)
    assert auth.user_from_query_token(token) is None


def test_returns_none_when_sub_is_not_integer(client):
    """A hand-rolled JWT with a non-integer subject claim must not crash."""
    from datetime import datetime, timedelta, timezone
    from jose import jwt as jose_jwt

    payload = {
        "sub": "not-an-int",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    bad = jose_jwt.encode(payload, auth.SECRET_KEY, algorithm=auth.ALGORITHM)
    assert auth.user_from_query_token(bad) is None


def test_returns_none_when_sub_missing(client):
    from datetime import datetime, timedelta, timezone
    from jose import jwt as jose_jwt

    payload = {"exp": datetime.now(timezone.utc) + timedelta(hours=1)}
    bad = jose_jwt.encode(payload, auth.SECRET_KEY, algorithm=auth.ALGORITHM)
    assert auth.user_from_query_token(bad) is None
