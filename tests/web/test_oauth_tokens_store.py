"""SQL-layer tests for the v2.7 ``oauth_tokens`` table.

Crypto-agnostic on purpose: the DB module treats refresh_token as an
opaque string. Fernet round-trip is exercised by
``test_youtube_auth.py``; here we only verify the schema + CRUD.
"""
from __future__ import annotations


def test_save_and_get_oauth_token_round_trip(tmp_db):
    from web.backend import db

    db.save_oauth_token(
        user_id=1,
        provider="youtube",
        refresh_token_encrypted="opaque-blob",
        access_token="ya29.foo",
        expires_at="2026-12-31T00:00:00+00:00",
        scope="youtube.readonly",
        channel_id="UCabc",
        channel_title="My Channel",
    )
    row = db.get_oauth_token(1, "youtube")
    assert row is not None
    assert row["refresh_token"] == "opaque-blob"
    assert row["access_token"] == "ya29.foo"
    assert row["channel_id"] == "UCabc"
    assert row["channel_title"] == "My Channel"
    assert row["scope"] == "youtube.readonly"
    assert row["connected_at"]  # default-populated


def test_save_oauth_token_is_upsert(tmp_db):
    from web.backend import db

    db.save_oauth_token(
        user_id=1, provider="youtube",
        refresh_token_encrypted="first", access_token="t1",
    )
    db.save_oauth_token(
        user_id=1, provider="youtube",
        refresh_token_encrypted="second", access_token="t2",
        channel_title="renamed",
    )
    row = db.get_oauth_token(1, "youtube")
    assert row is not None
    assert row["refresh_token"] == "second"
    assert row["access_token"] == "t2"
    assert row["channel_title"] == "renamed"


def test_update_oauth_access_token_preserves_refresh_token(tmp_db):
    """The refresh round-trip helper must NOT touch the refresh_token —
    that's our long-lived secret and rotating it would force re-auth."""
    from web.backend import db

    db.save_oauth_token(
        user_id=1, provider="youtube",
        refresh_token_encrypted="opaque-blob",
        access_token="stale",
        expires_at="2020-01-01T00:00:00+00:00",
    )
    db.update_oauth_access_token(
        user_id=1, provider="youtube",
        access_token="fresh", expires_at="2030-01-01T00:00:00+00:00",
    )
    row = db.get_oauth_token(1, "youtube")
    assert row is not None
    assert row["refresh_token"] == "opaque-blob"
    assert row["access_token"] == "fresh"
    assert row["expires_at"].startswith("2030")


def test_delete_oauth_token_returns_true_when_removed(tmp_db):
    from web.backend import db

    db.save_oauth_token(user_id=1, provider="youtube", refresh_token_encrypted="x")
    assert db.delete_oauth_token(1, "youtube") is True
    assert db.get_oauth_token(1, "youtube") is None


def test_delete_oauth_token_returns_false_when_absent(tmp_db):
    from web.backend import db

    assert db.delete_oauth_token(999, "youtube") is False


def test_per_user_isolation(tmp_db):
    """Two users with tokens for the same provider don't see each other's."""
    from web.backend import db

    db.save_oauth_token(1, "youtube", "blob-1", channel_title="alice")
    db.save_oauth_token(2, "youtube", "blob-2", channel_title="bob")
    assert db.get_oauth_token(1, "youtube")["refresh_token"] == "blob-1"
    assert db.get_oauth_token(2, "youtube")["refresh_token"] == "blob-2"
    db.delete_oauth_token(1, "youtube")
    assert db.get_oauth_token(1, "youtube") is None
    # Bob's row is untouched.
    assert db.get_oauth_token(2, "youtube")["refresh_token"] == "blob-2"
