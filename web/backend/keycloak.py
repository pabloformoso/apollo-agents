"""Keycloak (OIDC) identity for Apollo.

Apollo's own auth is small — bcrypt plus an HS256 JWT it signs itself.
This module adds a second, federated way in: the browser authenticates
against a Keycloak realm, and the backend verifies the realm's RS256
token against the realm's published JWKS.

**Why not replace the local user table.** Five tables hold a foreign key
to ``users(id)`` — sessions, ratings, playlists, oauth tokens,
generations. Federating identity does not mean discarding that graph, it
means the row stops owning a password. Each Keycloak subject therefore
maps to exactly one local row, keyed by ``sub``.

**Why keyed on ``sub`` and never on email or username.** A realm admin
can change both at any time. Keying on either would let a rename
re-point Apollo's row at a different human — a whole-account takeover,
history included. ``sub`` is the one claim Keycloak guarantees immutable.

**Why Apollo still signs its own short token.** ``<audio>``, ``<img>``
and ``WebSocket`` cannot set an Authorization header, so those endpoints
take the token in the query string. Putting a realm access token — long
lived, broadly scoped, and the key to every other client in the realm —
into a URL that lands in browser history, proxy logs and nginx access
logs is not a trade worth making. The realm token is exchanged once, at
login, for an Apollo token that is useless anywhere else.

Verification is strict on purpose. A token is accepted only when the
signature checks against a key the realm currently publishes AND the
issuer and audience match what this deployment was configured with.
Skipping either turns "a valid token" into "a token signed by anyone".
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
from jose import jwt
from jose.exceptions import JWTError

#: Realm base, e.g. https://id.example.com/realms/apollo — the issuer
#: Keycloak stamps into every token it mints for that realm.
ISSUER = (os.getenv("KEYCLOAK_ISSUER") or "").rstrip("/")

#: The client id the frontend authenticates with. Tokens must name it in
#: ``aud`` (or in ``azp`` — Keycloak puts the client there when the token
#: has no other audience).
CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID") or ""

#: Where the realm publishes its signing keys. Derived from the issuer,
#: which is the only shape Keycloak uses, but overridable for a proxy.
JWKS_URL = os.getenv("KEYCLOAK_JWKS_URL") or (
    f"{ISSUER}/protocol/openid-connect/certs" if ISSUER else ""
)

#: How long a fetched key set is trusted before refetching. Keycloak
#: rotates realm keys, and a cache that never expires turns a routine
#: rotation into every user being logged out until someone restarts the
#: backend.
JWKS_TTL_SEC = int(os.getenv("KEYCLOAK_JWKS_TTL_SEC") or 3600)

#: Clock skew tolerated on exp/iat, in seconds.
LEEWAY_SEC = 30


def is_configured() -> bool:
    """True when this deployment has enough config to verify a token.

    Checked before every attempt so a half-configured deployment refuses
    tokens outright instead of failing open.
    """
    return bool(ISSUER and CLIENT_ID and JWKS_URL)


class KeycloakError(Exception):
    """Verification failed. The message is safe to log, not to return."""


@dataclass
class _JwksCache:
    keys: list[dict] | None = None
    fetched_at: float = 0.0


_cache = _JwksCache()
_cache_lock = threading.Lock()


def _fetch_jwks() -> list[dict]:
    resp = httpx.get(JWKS_URL, timeout=10.0)
    resp.raise_for_status()
    keys = resp.json().get("keys")
    if not isinstance(keys, list) or not keys:
        raise KeycloakError(f"JWKS at {JWKS_URL} returned no keys")
    return keys


def get_jwks(*, force: bool = False) -> list[dict]:
    """Realm signing keys, cached for ``JWKS_TTL_SEC``.

    ``force`` refetches immediately — used once per unknown ``kid``, so a
    key rotation recovers on the next request instead of after a restart.
    """
    with _cache_lock:
        fresh = (
            _cache.keys is not None
            and (time.monotonic() - _cache.fetched_at) < JWKS_TTL_SEC
        )
        if fresh and not force:
            return _cache.keys  # type: ignore[return-value]
    keys = _fetch_jwks()
    with _cache_lock:
        _cache.keys = keys
        _cache.fetched_at = time.monotonic()
    return keys


def _key_for(kid: str | None) -> dict:
    """The published key with this ``kid``, refetching once if unknown."""
    for attempt in (False, True):
        for key in get_jwks(force=attempt):
            if key.get("kid") == kid:
                return key
    raise KeycloakError(f"no published realm key for kid={kid!r}")


def verify_token(token: str) -> dict[str, Any]:
    """Verify a realm token and return its claims.

    Raises :class:`KeycloakError` for anything short of a token this
    realm signed, for this client, that has not expired. Every failure
    is the same from the caller's side — a 401 — so the reason stays in
    the log and never reaches the client.
    """
    if not is_configured():
        raise KeycloakError("Keycloak is not configured on this deployment")
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise KeycloakError(f"malformed token header: {exc}") from exc

    # Reject anything not signed with an asymmetric algorithm BEFORE
    # looking up a key. Without this an attacker can present alg=none, or
    # alg=HS256 signed with the public key as the HMAC secret — the
    # classic JWT confusion attack, and the public key is public.
    alg = header.get("alg")
    if alg not in {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}:
        raise KeycloakError(f"refusing token signed with alg={alg!r}")

    key = _key_for(header.get("kid"))
    try:
        return jwt.decode(
            token,
            key,
            algorithms=[alg],
            issuer=ISSUER,
            audience=CLIENT_ID,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": True,
                "leeway": LEEWAY_SEC,
            },
        )
    except JWTError as exc:
        # Keycloak omits `aud` when the token has no audience beyond the
        # requesting client, putting the client in `azp` instead. Retry
        # once WITHOUT audience verification and check `azp` by hand —
        # issuer and signature are still fully enforced.
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[alg],
                issuer=ISSUER,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iss": True,
                    "verify_aud": False,
                    "leeway": LEEWAY_SEC,
                },
            )
        except JWTError:
            raise KeycloakError(f"token rejected: {exc}") from exc
        if claims.get("azp") != CLIENT_ID:
            raise KeycloakError(
                f"token is for another client (azp={claims.get('azp')!r})"
            )
        return claims


def realm_roles(claims: dict[str, Any]) -> set[str]:
    """Realm roles from a verified token.

    Keycloak nests them under ``realm_access.roles``. Client roles live
    elsewhere (``resource_access``) and are deliberately ignored: Apollo
    grants on realm roles only, so one place decides what a person can do.
    """
    access = claims.get("realm_access")
    if not isinstance(access, dict):
        return set()
    roles = access.get("roles")
    if not isinstance(roles, list):
        return set()
    return {str(r) for r in roles}


def identity(claims: dict[str, Any]) -> tuple[str, str, str]:
    """``(sub, username, email)`` from verified claims.

    ``sub`` is required — it is the only stable handle on the person.
    The other two are conveniences for the local row and fall back to
    something derived from ``sub`` rather than failing the login, since
    a realm can be configured without an email.
    """
    sub = claims.get("sub")
    if not sub:
        raise KeycloakError("token has no 'sub' claim")
    sub = str(sub)
    username = str(
        claims.get("preferred_username") or claims.get("email") or f"kc-{sub[:12]}"
    )
    email = str(claims.get("email") or f"{username}@keycloak.local")
    return sub, username, email


def reset_cache_for_tests() -> None:
    with _cache_lock:
        _cache.keys = None
        _cache.fetched_at = 0.0
