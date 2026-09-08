"""Keycloak as Apollo's identity provider.

The realm becomes the door; the local ``users`` row stays, because five
tables hold a foreign key to ``users(id)``. These tests cover the parts
where getting it wrong is not a bug but a breach: signature verification,
what a role grants, and the two actions that stay with the operator.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
from jose import jwt

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "web") not in sys.path:
    sys.path.insert(0, str(ROOT / "web"))

from backend import permissions  # noqa: E402


# --- an RSA keypair, so we can mint tokens the way a realm does --------

@pytest.fixture(scope="module")
def keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = key.public_key()
    nums = pub.public_numbers()

    def b64u(i: int) -> str:
        import base64

        raw = i.to_bytes((i.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    jwk = {
        "kty": "RSA",
        "kid": "test-key-1",
        "use": "sig",
        "alg": "RS256",
        "n": b64u(nums.n),
        "e": b64u(nums.e),
    }
    return priv, jwk


ISSUER = "https://id.test/realms/apollo"
CLIENT = "apollo-web"


@pytest.fixture
def kc(monkeypatch, keypair):
    """A configured keycloak module with the test key set already cached."""
    priv, jwk = keypair
    monkeypatch.setenv("KEYCLOAK_ISSUER", ISSUER)
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", CLIENT)
    monkeypatch.setenv("KEYCLOAK_JWKS_URL", f"{ISSUER}/protocol/openid-connect/certs")
    from backend import keycloak as mod

    importlib.reload(mod)
    # Never let a test reach the network: the key set is injected.
    monkeypatch.setattr(mod, "_fetch_jwks", lambda: [jwk])
    mod.reset_cache_for_tests()
    return mod


def mint(priv, claims, *, alg="RS256", kid="test-key-1"):
    import time

    body = {
        "iss": ISSUER,
        "aud": CLIENT,
        "sub": "kc-sub-abc",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        **claims,
    }
    return jwt.encode(body, priv, algorithm=alg, headers={"kid": kid})


# --- verification: the part where a mistake is a breach -----------------

def test_a_realm_signed_token_is_accepted(kc, keypair):
    priv, _ = keypair
    claims = kc.verify_token(mint(priv, {"preferred_username": "pablo"}))
    assert claims["sub"] == "kc-sub-abc"


def test_alg_none_is_refused_before_any_key_lookup(kc):
    """The classic forgery: an unsigned token claiming to need no key.

    Hand-rolled because python-jose refuses to MINT one — which is good
    of it, but says nothing about what our verifier accepts. An attacker
    has no such scruples, so the token is assembled the way they would.
    """
    import base64

    def seg(obj):
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    forged = (
        seg({"alg": "none", "typ": "JWT"})
        + "."
        + seg({"iss": ISSUER, "aud": CLIENT, "sub": "attacker", "exp": 9999999999})
        + "."
    )
    with pytest.raises(kc.KeycloakError, match="alg"):
        kc.verify_token(forged)


def test_hs256_signed_with_the_public_key_is_refused(kc, keypair):
    """JWT confusion: the public key is public, so it must never be a secret."""
    _, jwk = keypair
    forged = jwt.encode(
        {"iss": ISSUER, "aud": CLIENT, "sub": "attacker"},
        key=json.dumps(jwk),
        algorithm="HS256",
        headers={"kid": "test-key-1"},
    )
    with pytest.raises(kc.KeycloakError, match="alg"):
        kc.verify_token(forged)


def test_a_token_from_another_issuer_is_refused(kc, keypair):
    priv, _ = keypair
    other = jwt.encode(
        {"iss": "https://evil/realms/apollo", "aud": CLIENT, "sub": "x",
         "exp": 9999999999},
        priv, algorithm="RS256", headers={"kid": "test-key-1"},
    )
    with pytest.raises(kc.KeycloakError):
        kc.verify_token(other)


def test_a_token_for_another_client_is_refused(kc, keypair):
    priv, _ = keypair
    other = jwt.encode(
        {"iss": ISSUER, "aud": "some-other-app", "azp": "some-other-app",
         "sub": "x", "exp": 9999999999},
        priv, algorithm="RS256", headers={"kid": "test-key-1"},
    )
    with pytest.raises(kc.KeycloakError):
        kc.verify_token(other)


def test_an_expired_token_is_refused(kc, keypair):
    priv, _ = keypair
    old = jwt.encode(
        {"iss": ISSUER, "aud": CLIENT, "sub": "x", "exp": 1000, "iat": 900},
        priv, algorithm="RS256", headers={"kid": "test-key-1"},
    )
    with pytest.raises(kc.KeycloakError):
        kc.verify_token(old)


def test_an_unknown_kid_refetches_once_then_refuses(kc, keypair, monkeypatch):
    """A realm key rotation must recover without a restart."""
    priv, _ = keypair
    calls = {"n": 0}
    real = kc._fetch_jwks

    def counting():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(kc, "_fetch_jwks", counting)
    kc.reset_cache_for_tests()
    with pytest.raises(kc.KeycloakError, match="kid"):
        kc.verify_token(mint(priv, {}, kid="rotated-away"))
    assert calls["n"] == 2, "must refetch once before giving up"


def test_a_token_with_azp_but_no_aud_is_accepted(kc, keypair):
    """Keycloak omits aud when the client is the only audience."""
    priv, _ = keypair
    import time

    tok = jwt.encode(
        {"iss": ISSUER, "azp": CLIENT, "sub": "kc-sub-abc",
         "exp": int(time.time()) + 300},
        priv, algorithm="RS256", headers={"kid": "test-key-1"},
    )
    assert kc.verify_token(tok)["sub"] == "kc-sub-abc"


def test_an_unconfigured_deployment_refuses_every_token(monkeypatch, keypair):
    priv, _ = keypair
    monkeypatch.delenv("KEYCLOAK_ISSUER", raising=False)
    monkeypatch.delenv("KEYCLOAK_CLIENT_ID", raising=False)
    from backend import keycloak as mod

    importlib.reload(mod)
    assert mod.is_configured() is False
    with pytest.raises(mod.KeycloakError):
        mod.verify_token(mint(priv, {}))


# --- identity: never key on anything a realm admin can edit -------------

def test_identity_requires_sub(kc):
    with pytest.raises(kc.KeycloakError, match="sub"):
        kc.identity({"preferred_username": "pablo"})


def test_identity_survives_a_realm_with_no_email(kc):
    sub, username, email = kc.identity(
        {"sub": "abc123def456ghi", "preferred_username": "nina"}
    )
    assert (sub, username) == ("abc123def456ghi", "nina")
    assert email  # derived, not empty — the row needs one


def test_realm_roles_ignores_client_roles(kc):
    claims = {
        "realm_access": {"roles": ["apollo-admin"]},
        "resource_access": {"other-app": {"roles": ["should-be-ignored"]}},
    }
    assert kc.realm_roles(claims) == {"apollo-admin"}


def test_realm_roles_of_a_token_with_none(kc):
    assert kc.realm_roles({}) == set()


# --- capabilities: what the operator keeps ------------------------------

def test_a_plain_realm_account_listens_and_generates():
    caps = permissions.capabilities_for(set())
    assert permissions.GENERATE_MUSIC in caps
    assert permissions.LISTEN_AND_RATE in caps


def test_a_plain_realm_account_cannot_publish_or_broadcast():
    """The two shared, expensive actions."""
    caps = permissions.capabilities_for(set())
    assert permissions.PUBLISH_TO_CATALOG not in caps
    assert permissions.START_LIVE_SESSION not in caps


def test_roles_grant_exactly_their_capability():
    assert permissions.PUBLISH_TO_CATALOG in permissions.capabilities_for(
        {"apollo-publisher"}
    )
    assert permissions.START_LIVE_SESSION not in permissions.capabilities_for(
        {"apollo-publisher"}
    )


def test_the_admin_role_grants_everything():
    assert permissions.capabilities_for({permissions.ADMIN_ROLE}) == (
        permissions.ALL_CAPABILITIES
    )


def test_an_unknown_role_grants_nothing_extra():
    assert permissions.capabilities_for({"wat"}) == permissions.BASE_CAPABILITIES


def test_a_user_dict_with_no_capabilities_fails_closed():
    """An unauthenticated path reaching a check must not be all-powerful."""
    assert not permissions.has_capability({}, permissions.PUBLISH_TO_CATALOG)
    assert not permissions.has_capability(
        {"capabilities": None}, permissions.START_LIVE_SESSION
    )


def test_a_pre_realm_local_account_keeps_everything_it_had():
    """Adding roles must not be a breaking change.

    ``None`` is an account with no realm behind it — the operator's own
    local login, from before any of this existed. Handing it the base set
    would have silently taken away its ability to publish and to go on
    air, which is the same class of mistake as defaulting AUTH_MODE to
    keycloak before a realm exists.
    """
    assert permissions.capabilities_for(None) == permissions.ALL_CAPABILITIES


def test_an_empty_role_set_is_not_the_same_as_no_realm():
    """A realm account holding no roles listens and generates, no more."""
    assert permissions.capabilities_for(set()) == permissions.BASE_CAPABILITIES
    assert permissions.capabilities_for(set()) != permissions.capabilities_for(None)
