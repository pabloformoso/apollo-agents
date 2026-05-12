"""YouTube OAuth 2.0 flow + per-user credential management (v2.7).

Scope: ``https://www.googleapis.com/auth/youtube.readonly`` — enough to
discover the operator's active live broadcast and read its live chat.
Write-back (posting replies into YouTube chat) is deliberately not
included; that's a v2.7.1 follow-up that needs the broader ``youtube``
scope and an explicit operator opt-in.

Configuration
-------------
The three env vars below activate the feature. If any is missing the
:func:`enabled` predicate returns ``False`` and the HTTP routes in
``app.py`` fall through to a 404. This keeps the feature genuinely
opt-in — running Apollo without Google credentials behaves exactly as
v2.6.x did.

- ``GOOGLE_CLIENT_ID``
- ``GOOGLE_CLIENT_SECRET``
- ``GOOGLE_REDIRECT_URI``  (must match what's registered in Google
  Cloud Console under the OAuth 2.0 Client ID)

Encryption at rest
------------------
Refresh tokens are persisted via :mod:`web.backend.db` but the bytes
written to disk are Fernet-encrypted with a key derived from
``JWT_SECRET``. Defence-in-depth: a stolen DB file alone can't be
turned into a usable Google credential without the env, and a rotated
``JWT_SECRET`` invalidates every stored token (graceful — the user
gets prompted to reconnect rather than seeing a silent auth failure).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from . import db


SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
PROVIDER = "youtube"
_STATE_TTL_SEC = 600  # 10 minutes — Google's flow takes ~30 s in practice


# ---------------------------------------------------------------------------
# Configuration probe
# ---------------------------------------------------------------------------


def _client_id() -> str | None:
    return os.environ.get("GOOGLE_CLIENT_ID") or None


def _client_secret() -> str | None:
    return os.environ.get("GOOGLE_CLIENT_SECRET") or None


def _redirect_uri() -> str | None:
    return os.environ.get("GOOGLE_REDIRECT_URI") or None


def enabled() -> bool:
    """``True`` only when all three Google OAuth env vars are present.

    The HTTP routes consult this at request time; missing config → 404,
    not a 500. Keeps the feature genuinely opt-in and the dev workflow
    quiet for anyone without a Google Cloud project.
    """
    return bool(_client_id() and _client_secret() and _redirect_uri())


# ---------------------------------------------------------------------------
# Fernet at-rest encryption for refresh tokens
# ---------------------------------------------------------------------------


def _fernet() -> Fernet:
    """Derive a Fernet key from ``JWT_SECRET``.

    SHA-256 of the secret yields 32 bytes → base64 → Fernet key. Same
    secret in, same key out, deterministically — so existing rows
    decrypt cleanly across uvicorn restarts. Rotating ``JWT_SECRET``
    invalidates every stored token (decryption raises and the caller
    treats it as "not connected").
    """
    secret = os.environ.get("JWT_SECRET", "apollo-agents-change-me")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def _encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def _decrypt(ciphertext: str) -> str | None:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


# ---------------------------------------------------------------------------
# HMAC-signed state token — binds the OAuth callback to the user who
# initiated the flow + a short TTL so a stale link can't be replayed.
# ---------------------------------------------------------------------------


def _state_secret() -> bytes:
    return os.environ.get("JWT_SECRET", "apollo-agents-change-me").encode("utf-8")


def mint_state(user_id: int) -> str:
    """Pack ``user_id`` + a random nonce + expiry into an HMAC'd token."""
    exp = int(time.time()) + _STATE_TTL_SEC
    nonce = secrets.token_urlsafe(12)
    payload = f"{user_id}:{nonce}:{exp}"
    sig = hmac.new(
        _state_secret(), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{payload}:{sig}"


def verify_state(state: str) -> int | None:
    """Return the embedded ``user_id`` iff the state is valid + unexpired."""
    try:
        user_id_str, nonce, exp_str, sig = state.rsplit(":", 3)
    except ValueError:
        return None
    payload = f"{user_id_str}:{nonce}:{exp_str}"
    expected = hmac.new(
        _state_secret(), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        if int(exp_str) < int(time.time()):
            return None
        return int(user_id_str)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# OAuth flow
# ---------------------------------------------------------------------------


def start_oauth_flow(user_id: int) -> str:
    """Return the Google authorisation URL the operator should hit.

    The caller (HTTP endpoint) typically issues a 302 to this URL. We
    use the explicit URL-build path rather than ``google_auth_oauthlib``'s
    ``Flow.from_client_config`` here because we only need the consent
    URL, not the full local-server callback; the callback hits our own
    FastAPI route.
    """
    if not enabled():
        raise RuntimeError("YouTube integration not configured")
    from urllib.parse import urlencode

    params = {
        "client_id": _client_id(),
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        # ``offline`` is required to receive a refresh token; ``consent``
        # forces the consent screen so Google always returns a refresh
        # token even on re-auth (otherwise it elides it on subsequent
        # consents and we can't refresh long-lived sessions).
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": mint_state(user_id),
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


async def handle_callback(code: str, state: str) -> dict[str, Any]:
    """Exchange the authorisation code for tokens, persist, return summary.

    Returns ``{"user_id": int, "channel_id": str, "channel_title": str}``
    on success. Raises ``RuntimeError`` on any failure with a short
    operator-friendly message; the HTTP endpoint maps these to 4xx.
    """
    if not enabled():
        raise RuntimeError("YouTube integration not configured")

    user_id = verify_state(state)
    if user_id is None:
        raise RuntimeError("state token invalid or expired")

    # google-auth's ``Flow`` is sync — push to a thread.
    creds = await asyncio.to_thread(_exchange_code, code)
    channel = await asyncio.to_thread(_fetch_own_channel, creds)

    db.save_oauth_token(
        user_id=user_id,
        provider=PROVIDER,
        refresh_token_encrypted=_encrypt(creds.refresh_token),
        access_token=creds.token,
        expires_at=_iso(creds.expiry) if creds.expiry else None,
        scope=SCOPE,
        channel_id=channel["id"],
        channel_title=channel["title"],
    )
    return {
        "user_id": user_id,
        "channel_id": channel["id"],
        "channel_title": channel["title"],
    }


def _exchange_code(code: str):
    """Synchronous code → Credentials exchange (run via to_thread)."""
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        client_config={
            "web": {
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "redirect_uris": [_redirect_uri()],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=[SCOPE],
        redirect_uri=_redirect_uri(),
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    if not creds.refresh_token:
        # Should never happen with prompt=consent + access_type=offline,
        # but we surface it clearly if Google's behaviour ever changes.
        raise RuntimeError("Google did not return a refresh token; re-consent required")
    return creds


def _fetch_own_channel(creds) -> dict[str, str]:
    """Resolve the authenticated channel id + title via ``channels.list?mine=true``."""
    from googleapiclient.discovery import build

    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    resp = yt.channels().list(part="snippet", mine=True).execute()
    items = resp.get("items") or []
    if not items:
        raise RuntimeError("Authenticated Google account has no YouTube channel")
    item = items[0]
    return {
        "id": item["id"],
        "title": item.get("snippet", {}).get("title") or item["id"],
    }


# ---------------------------------------------------------------------------
# Credentials retrieval (used by the live WS handler + status endpoint)
# ---------------------------------------------------------------------------


def get_credentials(user_id: int):
    """Return refreshed ``google.oauth2.credentials.Credentials`` or ``None``.

    - ``None`` if the user hasn't connected, the encrypted refresh
      token can't be decrypted (e.g. JWT_SECRET rotated), or the
      refresh round-trip fails (revoked, expired).
    - Otherwise: a ready-to-use ``Credentials`` instance. If the cached
      access token is stale we refresh inline and persist the new
      access_token + expiry.
    """
    if not enabled():
        return None

    row = db.get_oauth_token(user_id, PROVIDER)
    if not row:
        return None
    refresh_token = _decrypt(row["refresh_token"])
    if refresh_token is None:
        return None

    from google.oauth2.credentials import Credentials

    creds = Credentials(
        token=row.get("access_token"),
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=_client_id(),
        client_secret=_client_secret(),
        scopes=[row.get("scope") or SCOPE],
    )
    if creds.expired or not creds.token:
        try:
            from google.auth.transport.requests import Request

            creds.refresh(Request())
        except Exception:  # noqa: BLE001 — many possible failure modes; treat as "disconnected"
            return None
        db.update_oauth_access_token(
            user_id=user_id,
            provider=PROVIDER,
            access_token=creds.token,
            expires_at=_iso(creds.expiry) if creds.expiry else None,
        )
    return creds


def disconnect(user_id: int) -> bool:
    """Drop the user's stored YouTube credentials. Idempotent."""
    return db.delete_oauth_token(user_id, PROVIDER)


def channel_summary(user_id: int) -> dict[str, str] | None:
    """Lightweight: returns ``{channel_id, channel_title}`` if connected.

    Used by the /status endpoint so the frontend can render the pill
    without triggering a token refresh round-trip.
    """
    row = db.get_oauth_token(user_id, PROVIDER)
    if not row:
        return None
    return {
        "channel_id": row.get("channel_id") or "",
        "channel_title": row.get("channel_title") or "",
    }


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _iso(dt) -> str:
    """Convert a Google credentials ``expiry`` (naive UTC datetime) to ISO 8601."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
