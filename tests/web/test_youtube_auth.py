"""Unit tests for ``web.backend.youtube_auth`` (v2.7).

The module wraps three concerns: env-driven enable/disable, Fernet
encryption of refresh tokens, and HMAC-signed state tokens. Tests
cover each in isolation; the full OAuth code-exchange path is
exercised indirectly by ``test_live_ws_youtube.py`` via fakes (no
real Google round-trip in CI).
"""
from __future__ import annotations

import os
import time

import pytest


# ---------------------------------------------------------------------------
# enabled() — gated on three env vars
# ---------------------------------------------------------------------------


@pytest.fixture
def yt_env(monkeypatch):
    """Configure the three Google OAuth env vars for the duration of the test."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:4080/api/youtube/oauth/callback")


def test_enabled_returns_false_when_any_env_missing(monkeypatch):
    from web.backend import youtube_auth

    for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"):
        monkeypatch.delenv(k, raising=False)
    assert youtube_auth.enabled() is False


def test_enabled_returns_true_when_all_present(yt_env):
    from web.backend import youtube_auth

    assert youtube_auth.enabled() is True


# ---------------------------------------------------------------------------
# Fernet round-trip
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_round_trip(monkeypatch):
    """A round-trip through Fernet must yield the original plaintext."""
    monkeypatch.setenv("JWT_SECRET", "deterministic-secret")
    from web.backend import youtube_auth

    plain = "1//0ggSiSf-test-refresh-token"
    ct = youtube_auth._encrypt(plain)
    assert ct != plain
    assert youtube_auth._decrypt(ct) == plain


def test_decrypt_returns_none_on_bogus_ciphertext(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "any")
    from web.backend import youtube_auth

    assert youtube_auth._decrypt("definitely-not-a-fernet-token") is None


def test_decrypt_returns_none_when_jwt_secret_rotated(monkeypatch):
    """Rotating ``JWT_SECRET`` must invalidate existing ciphertexts cleanly
    — graceful re-auth, not a silent crash. We encrypt under one secret,
    flip the env, and confirm decrypt returns None."""
    from web.backend import youtube_auth

    monkeypatch.setenv("JWT_SECRET", "secret-A")
    ct = youtube_auth._encrypt("plain")

    monkeypatch.setenv("JWT_SECRET", "secret-B")
    assert youtube_auth._decrypt(ct) is None


# ---------------------------------------------------------------------------
# State token HMAC + TTL
# ---------------------------------------------------------------------------


def test_mint_and_verify_state_round_trip(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "any")
    from web.backend import youtube_auth

    state = youtube_auth.mint_state(user_id=42)
    assert youtube_auth.verify_state(state) == 42


def test_verify_state_rejects_tampered_user_id(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "any")
    from web.backend import youtube_auth

    state = youtube_auth.mint_state(7)
    parts = state.split(":")
    parts[0] = "99"  # flip user_id
    tampered = ":".join(parts)
    assert youtube_auth.verify_state(tampered) is None


def test_verify_state_rejects_tampered_signature(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "any")
    from web.backend import youtube_auth

    state = youtube_auth.mint_state(7)
    # Flip the trailing hex sig byte. ASCII trick: bump '0'→'1', otherwise '0'.
    bad = state[:-1] + ("1" if state[-1] == "0" else "0")
    assert youtube_auth.verify_state(bad) is None


def test_verify_state_rejects_expired_token(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "any")
    from web.backend import youtube_auth

    # Roll the clock forward past the TTL by patching time.time inside the
    # module under test.
    state = youtube_auth.mint_state(7)
    future = time.time() + youtube_auth._STATE_TTL_SEC + 60
    monkeypatch.setattr(youtube_auth.time, "time", lambda: future)
    assert youtube_auth.verify_state(state) is None


def test_verify_state_rejects_malformed_input(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "any")
    from web.backend import youtube_auth

    assert youtube_auth.verify_state("not-a-state-token") is None
    assert youtube_auth.verify_state("") is None


# ---------------------------------------------------------------------------
# start_oauth_flow() builds a sane URL
# ---------------------------------------------------------------------------


def test_start_oauth_flow_builds_url_with_state_and_scope(yt_env):
    from web.backend import youtube_auth

    url = youtube_auth.start_oauth_flow(user_id=42)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    # Scope hard-coded to readonly; the URL-encoded form contains the literal.
    assert "youtube.readonly" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=" in url
    # The state token in the URL must verify back to the original user_id.
    from urllib.parse import urlparse, parse_qs

    state = parse_qs(urlparse(url).query)["state"][0]
    assert youtube_auth.verify_state(state) == 42


def test_start_oauth_flow_raises_when_disabled(monkeypatch):
    from web.backend import youtube_auth

    for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError, match="not configured"):
        youtube_auth.start_oauth_flow(user_id=1)


# ---------------------------------------------------------------------------
# get_credentials() — disconnect path + ciphertext rotation
# ---------------------------------------------------------------------------


def test_get_credentials_returns_none_when_not_connected(tmp_db, yt_env):
    from web.backend import youtube_auth

    assert youtube_auth.get_credentials(user_id=1) is None


def test_get_credentials_returns_none_after_jwt_rotation(tmp_db, monkeypatch):
    """If JWT_SECRET rotates, the encrypted refresh token can't be
    decrypted — we must return None (treat as disconnected), not raise."""
    from web.backend import db, youtube_auth

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:4080/cb")
    monkeypatch.setenv("JWT_SECRET", "secret-A")
    db.save_oauth_token(
        user_id=1, provider="youtube",
        refresh_token_encrypted=youtube_auth._encrypt("real-refresh"),
        access_token="ya29.foo",
        scope=youtube_auth.SCOPE,
    )
    # Rotate the secret — the stored ciphertext now won't decrypt.
    monkeypatch.setenv("JWT_SECRET", "secret-B")
    assert youtube_auth.get_credentials(user_id=1) is None


def test_disconnect_drops_row(tmp_db, yt_env):
    from web.backend import db, youtube_auth

    db.save_oauth_token(
        user_id=1, provider="youtube",
        refresh_token_encrypted=youtube_auth._encrypt("rt"),
    )
    assert youtube_auth.disconnect(1) is True
    assert db.get_oauth_token(1, "youtube") is None


def test_channel_summary(tmp_db, yt_env):
    from web.backend import db, youtube_auth

    assert youtube_auth.channel_summary(1) is None
    db.save_oauth_token(
        user_id=1, provider="youtube",
        refresh_token_encrypted=youtube_auth._encrypt("rt"),
        channel_id="UCxyz", channel_title="My Channel",
    )
    s = youtube_auth.channel_summary(1)
    assert s == {"channel_id": "UCxyz", "channel_title": "My Channel"}
