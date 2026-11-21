import stat
import time

import httpx
import pytest
import respx

from apollo_mcp import auth
from apollo_mcp.auth import AuthError, Session, Tokens, jwt_claims

from .conftest import BASE, REALM, fake_jwt


def test_jwt_claims_reads_exp_without_verifying():
    assert jwt_claims(fake_jwt(exp=123, sub="1")) == {"exp": 123, "sub": "1"}
    assert jwt_claims("not-a-jwt") == {}


def test_token_file_is_private(store, config):
    store.save(Tokens(apollo_token="t", apollo_exp=time.time() + 60))
    assert stat.S_IMODE(config.token_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(config.token_file.parent.stat().st_mode) == 0o700


def test_token_file_stays_private_when_it_already_existed(store, config):
    config.token_file.parent.mkdir(parents=True)
    config.token_file.write_text("{}")
    config.token_file.chmod(0o644)
    store.save(Tokens(apollo_token="t", apollo_exp=time.time() + 60))
    assert stat.S_IMODE(config.token_file.stat().st_mode) == 0o600


async def test_not_signed_in_says_how(config, http):
    with pytest.raises(AuthError, match="apollo-mcp login"):
        await Session(config, http).token()


async def test_valid_token_is_used_without_any_call(config, http, signed_in):
    with respx.mock(assert_all_called=False) as mock:
        assert await Session(config, http).token() == signed_in
        assert not mock.calls


@respx.mock
async def test_expired_token_is_renewed_from_the_realm(config, http, store):
    store.save(Tokens(apollo_token="old", apollo_exp=time.time() - 10,
                      refresh_token="r1", refresh_exp=time.time() + 600))
    respx.post(REALM + "/token").respond(200, json={
        "access_token": "realm-at", "refresh_token": "r2", "refresh_expires_in": 1800})
    new = fake_jwt(sub="1", exp=time.time() + 604800)
    exchange = respx.post(BASE + "/api/auth/keycloak").respond(200, json={"access_token": new})

    assert await Session(config, http).token() == new
    assert exchange.calls.last.request.content == b'{"token":"realm-at"}'
    saved = store.load()
    assert saved.refresh_token == "r2" and saved.apollo_token == new


async def test_expired_token_without_refresh_asks_for_login(config, http, store):
    store.save(Tokens(apollo_token="old", apollo_exp=time.time() - 10))
    with pytest.raises(AuthError, match="expired"):
        await Session(config, http).token()


@respx.mock
async def test_device_login_polls_until_approved(config, http, store, monkeypatch):
    sleeps = []

    async def no_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(auth.asyncio, "sleep", no_sleep)
    respx.post(REALM + "/auth/device").respond(200, json={
        "device_code": "dc", "user_code": "ABCD-EFGH", "expires_in": 600, "interval": 5,
        "verification_uri_complete": "https://kc.test/device?user_code=ABCD-EFGH"})
    respx.post(REALM + "/token").mock(side_effect=[
        httpx.Response(400, json={"error": "authorization_pending"}),
        httpx.Response(400, json={"error": "slow_down"}),
        httpx.Response(200, json={"access_token": "realm-at", "refresh_token": "r",
                                  "refresh_expires_in": 1800}),
    ])
    apollo = fake_jwt(sub="1", exp=time.time() + 604800)
    respx.post(BASE + "/api/auth/keycloak").respond(200, json={"access_token": apollo})
    shown = []

    tokens = await Session(config, http).login(lambda url, code, exp: shown.append((url, code)))

    assert shown == [("https://kc.test/device?user_code=ABCD-EFGH", "ABCD-EFGH")]
    assert sleeps == [5, 5, 10]  # slow_down adds 5 s, per RFC 8628
    assert tokens.apollo_token == apollo and store.load().apollo_token == apollo


@respx.mock
async def test_device_login_disabled_on_the_client_names_the_cause(config, http):
    respx.post(REALM + "/auth/device").respond(400, json={
        "error": "unauthorized_client",
        "error_description": "Client is not allowed to initiate OAuth 2.0 Device Authorization Grant."})
    with pytest.raises(AuthError, match="unauthorized_client.*Device Authorization"):
        await Session(config, http).login(lambda *a: None)


@respx.mock
async def test_apollo_refusing_the_realm_token_is_reported(config, http, monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(auth.asyncio, "sleep", no_sleep)
    respx.post(REALM + "/auth/device").respond(200, json={"device_code": "dc", "interval": 1})
    respx.post(REALM + "/token").respond(200, json={"access_token": "realm-at"})
    respx.post(BASE + "/api/auth/keycloak").respond(401, json={"detail": "Invalid identity token"})
    with pytest.raises(AuthError, match="Invalid identity token"):
        await Session(config, http).login(lambda *a: None)
