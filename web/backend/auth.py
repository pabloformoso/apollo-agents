"""JWT auth helpers and FastAPI dependency."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

SECRET_KEY = os.getenv("JWT_SECRET", "apollo-agents-change-me-in-production")

#: How this deployment lets people in.
#:
#: ``keycloak``  — the realm is the only door. Chosen by the operator on
#:                 2026-09-08; the local login form is refused.
#: ``local``     — pre-realm behaviour, username and password only.
#: ``both``      — accepts either. Not the configured default; it exists
#:                 so a broken realm does not lock the operator out of
#:                 their own Apollo, which is a real failure mode when
#:                 the realm lives on a machine that also runs the GPU.
#:
#: Whatever the mode, an ACCOUNT is only ever reachable one way: a row
#: carrying the Keycloak sentinel has no password anyone can type.
#: The DEFAULT is derived, not fixed, and that is deliberate. Defaulting
#: to "keycloak" outright would mean that merging this commit locks every
#: existing deployment out of itself the moment it restarts: the local
#: login form starts answering 403 while the realm it points at does not
#: exist yet. So an unconfigured deployment keeps behaving exactly as it
#: did, and the realm takes over the moment it is actually reachable.
#: An explicit APOLLO_AUTH_MODE always wins over both.
_MODE_ENV = (os.getenv("APOLLO_AUTH_MODE") or "").strip().lower()


def _keycloak_env_present() -> bool:
    """Whether this deployment has been pointed at a realm.

    Reads the environment directly rather than importing ``keycloak``,
    which would make an import cycle out of a two-variable check.
    """
    return bool(
        (os.getenv("KEYCLOAK_ISSUER") or "").strip()
        and (os.getenv("KEYCLOAK_CLIENT_ID") or "").strip()
    )


AUTH_MODE = _MODE_ENV or ("keycloak" if _keycloak_env_present() else "local")

LOCAL_LOGIN_ENABLED = AUTH_MODE in {"local", "both"}
KEYCLOAK_LOGIN_ENABLED = AUTH_MODE in {"keycloak", "both"}
ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week

# bcrypt enforces a 72-byte input limit; truncate to stay consistent with that.
_BCRYPT_MAX_BYTES = 72

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def _encode(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Check a password against a stored bcrypt hash.

    A Keycloak-backed row stores a sentinel here instead of a hash. It
    is not a hash and bcrypt would raise on it, but relying on that is
    relying on a library's error behaviour for an authentication
    decision — so the sentinel is rejected explicitly and first.
    """
    from . import db  # noqa: PLC0415 — avoids an import cycle at module load

    if not hashed or hashed == db.KEYCLOAK_PASSWORD_SENTINEL:
        return False
    try:
        return bcrypt.checkpw(_encode(plain), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def user_from_keycloak_token(token: str) -> dict | None:
    """Verify a realm token and return the local row it maps to.

    Creates the row on first login: a person who exists in the realm has
    an account here the moment they arrive, which is the whole point of
    delegating identity. Returns ``None`` for any verification failure —
    the caller decides whether that is a 401 or a socket close.
    """
    from . import db, keycloak, permissions  # noqa: PLC0415

    if not KEYCLOAK_LOGIN_ENABLED or not keycloak.is_configured():
        return None
    try:
        claims = keycloak.verify_token(token)
        sub, username, email = keycloak.identity(claims)
    except keycloak.KeycloakError as exc:
        # The reason stays here. The caller answers 401 either way, and
        # telling a client WHY its token failed helps only an attacker.
        print(f"[auth] keycloak token rejected: {exc}", flush=True)
        return None

    row = db.get_user_by_keycloak_sub(sub)
    if row is None:
        try:
            user_id = db.create_keycloak_user(sub, username, email)
        except Exception as exc:  # noqa: BLE001 — username/email collide
            print(
                f"[auth] cannot create local row for keycloak sub {sub}: {exc}",
                flush=True,
            )
            return None
        row = db.get_user_by_id(user_id)
        if row is None:
            return None

    user = dict(row)
    user["capabilities"] = permissions.capabilities_for(
        keycloak.realm_roles(claims)
    )
    return user


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    from . import db

    from . import permissions  # noqa: PLC0415

    # Apollo's own token first: it is what every browser request carries
    # after login, so the realm round-trip is the exception, not the rule.
    payload = decode_token(token)
    if payload and "sub" in payload:
        try:
            user_id = int(payload["sub"])
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
            )
        user = db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
            )
        user = dict(user)
        # Capabilities travel in the Apollo token, minted at login from
        # the realm roles of that moment. Re-reading them here would mean
        # a realm call on every request; the cost is that a role change
        # takes effect at next login, which the token's lifetime bounds.
        caps = payload.get("caps")
        user["capabilities"] = (
            frozenset(caps)
            if isinstance(caps, list)
            else permissions.capabilities_for(None)
        )
        return user

    # Otherwise a realm token, presented directly.
    kc_user = user_from_keycloak_token(token)
    if kc_user is not None:
        return kc_user
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
    )


def user_from_query_token(token: str) -> dict | None:
    """Decode a JWT carried as a query-string parameter and return the user.

    Returns ``None`` for any failure (invalid token, missing sub claim, unknown
    user). Used by transport-level handlers — WebSocket upgrades and SSE
    streams — that cannot set ``Authorization`` headers from the browser and
    must respond to failures with their own close/abort semantics rather than
    a 401 raise.
    """
    from . import db, permissions  # noqa: PLC0415

    payload = decode_token(token)
    if not payload or "sub" not in payload:
        # Not an Apollo token. It may still be a realm token presented
        # directly — the live page can hold one before it has exchanged.
        return user_from_keycloak_token(token)
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        return None
    row = db.get_user_by_id(user_id)
    if not row:
        return None
    user = dict(row)
    # Same capability source as get_current_user. Without this every
    # transport-level handler would see an account with no capabilities
    # and a capability check there would refuse everyone.
    caps = payload.get("caps")
    user["capabilities"] = (
        frozenset(caps)
        if isinstance(caps, list)
        else permissions.capabilities_for(None)
    )
    return user
