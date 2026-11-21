"""Signing in AS the operator: device-code login, then Apollo's own token.

The flow mirrors the browser's, with the device grant in place of the
redirect:

1. ``apollo-mcp login`` asks the realm for a device code and prints the
   URL to approve it at. The operator approves in any browser.
2. The realm access token is traded at ``POST /api/auth/keycloak`` for an
   Apollo token, exactly as the web app does. That token carries the
   operator's capabilities and lives a WEEK, while a realm refresh token
   dies with the SSO session (30 min idle by default) — so the Apollo
   token is what makes one login last, and the refresh token is only a
   bonus used when it is still alive.
3. Both are written to one file, created 0600 inside a 0700 directory.

The Apollo token has every power the operator has — publishing and going
live included. The MCP never exposes those (see ``server.py``), but the
FILE is the operator's key for a week: it is never printed, never returned
by a tool, and ``apollo-mcp logout`` deletes it.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .config import Config

DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
#: Renew this long before expiry, so a request never races the deadline.
EXPIRY_MARGIN_SEC = 60


class AuthError(RuntimeError):
    """Signing in failed, or there is no usable sign-in. The message says what to do."""


NOT_LOGGED_IN = "Not signed in to Apollo. Run `apollo-mcp login` in a terminal, then retry."


def jwt_claims(token: str) -> dict[str, Any]:
    """The payload of a JWT, NOT verified — read only to learn its own ``exp``.

    Apollo verifies every token it is sent; this side only needs to know
    when to stop sending one.
    """
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError):
        return {}
    return claims if isinstance(claims, dict) else {}


@dataclass
class Tokens:
    apollo_token: str
    apollo_exp: float
    refresh_token: str | None = None
    refresh_exp: float | None = None

    def apollo_valid(self, now: float | None = None) -> bool:
        return self.apollo_exp - EXPIRY_MARGIN_SEC > (now if now is not None else time.time())

    def refresh_valid(self, now: float | None = None) -> bool:
        if not self.refresh_token:
            return False
        if self.refresh_exp is None:
            return True  # an offline token, or a realm that does not say: just try it
        return self.refresh_exp - EXPIRY_MARGIN_SEC > (now if now is not None else time.time())


class TokenStore:
    """One JSON file, private to the user. Writes are atomic."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> Tokens | None:
        try:
            data = json.loads(self.path.read_text())
            return Tokens(
                apollo_token=str(data["apollo_token"]),
                apollo_exp=float(data["apollo_exp"]),
                refresh_token=data.get("refresh_token"),
                refresh_exp=data.get("refresh_exp"),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save(self, tokens: Tokens) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(tokens.__dict__, fh)
        os.chmod(tmp, 0o600)  # O_CREAT's mode does not apply to a file that already existed
        os.replace(tmp, self.path)

    def clear(self) -> bool:
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False


class Session:
    """Hands out a valid Apollo token, renewing it from the realm when it can."""

    def __init__(self, config: Config, http: httpx.AsyncClient, store: TokenStore | None = None):
        self.config = config
        self.http = http
        self.store = store or TokenStore(config.token_file)
        self._lock = asyncio.Lock()

    @property
    def _realm(self) -> str:
        return self.config.issuer + "/protocol/openid-connect"

    async def token(self, *, force_refresh: bool = False) -> str:
        async with self._lock:
            tokens = self.store.load()
            if tokens is None:
                raise AuthError(NOT_LOGGED_IN)
            if tokens.apollo_valid() and not force_refresh:
                return tokens.apollo_token
            if tokens.refresh_valid():
                try:
                    tokens = await self._refresh(tokens.refresh_token or "")
                    self.store.save(tokens)
                    return tokens.apollo_token
                except AuthError:
                    pass
            raise AuthError(
                "The Apollo sign-in has expired. Run `apollo-mcp login` in a terminal, then retry."
            )

    async def login(self, prompt: Callable[[str, str, int], Awaitable[None] | None]) -> Tokens:
        """Device-code login. ``prompt(url, user_code, expires_in)`` shows the operator where to approve."""
        resp = await self.http.post(
            self._realm + "/auth/device",
            data={"client_id": self.config.client_id, "scope": "openid"},
        )
        body = _json(resp)
        if resp.status_code != 200 or "device_code" not in body:
            raise AuthError(_realm_error("Could not start the device login", resp, body))
        url = body.get("verification_uri_complete") or body.get("verification_uri") or ""
        expires_in = int(body.get("expires_in") or 600)
        interval = int(body.get("interval") or 5)
        shown = prompt(url, str(body.get("user_code") or ""), expires_in)
        if asyncio.iscoroutine(shown):
            await shown

        deadline = time.monotonic() + expires_in
        while time.monotonic() < deadline:
            await asyncio.sleep(interval)
            resp = await self.http.post(
                self._realm + "/token",
                data={
                    "grant_type": DEVICE_GRANT,
                    "device_code": body["device_code"],
                    "client_id": self.config.client_id,
                },
            )
            grant = _json(resp)
            error = grant.get("error")
            if resp.status_code == 200 and "access_token" in grant:
                tokens = await self._from_grant(grant)
                self.store.save(tokens)
                return tokens
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            raise AuthError(_realm_error("Device login was not approved", resp, grant))
        raise AuthError("Device login expired before it was approved. Run `apollo-mcp login` again.")

    async def _refresh(self, refresh_token: str) -> Tokens:
        resp = await self.http.post(
            self._realm + "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.config.client_id,
            },
        )
        grant = _json(resp)
        if resp.status_code != 200 or "access_token" not in grant:
            raise AuthError(_realm_error("Refreshing the realm session failed", resp, grant))
        return await self._from_grant(grant)

    async def _from_grant(self, grant: dict[str, Any]) -> Tokens:
        """Trade a realm grant for Apollo's token, the web app's own exchange."""
        resp = await self.http.post(
            self.config.base_url + "/api/auth/keycloak", json={"token": grant["access_token"]}
        )
        body = _json(resp)
        apollo = body.get("access_token")
        if resp.status_code != 200 or not apollo:
            detail = body.get("detail") or f"HTTP {resp.status_code}"
            raise AuthError(f"Apollo refused the realm token: {detail}")
        now = time.time()
        refresh_expires_in = grant.get("refresh_expires_in")
        return Tokens(
            apollo_token=apollo,
            apollo_exp=float(jwt_claims(apollo).get("exp") or now + 3600),
            refresh_token=grant.get("refresh_token"),
            # Keycloak reports 0 for an offline token, which has no fixed end.
            refresh_exp=(now + float(refresh_expires_in)) if refresh_expires_in else None,
        )


def _json(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _realm_error(what: str, resp: httpx.Response, body: dict[str, Any]) -> str:
    """The realm's own words — ``unauthorized_client`` names the misconfiguration."""
    code = body.get("error") or f"HTTP {resp.status_code}"
    detail = body.get("error_description")
    return f"{what}: {code}" + (f" — {detail}" if detail else "")
