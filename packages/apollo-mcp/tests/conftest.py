import base64
import json
import time
from pathlib import Path

import httpx
import pytest

from apollo_mcp.auth import Tokens, TokenStore
from apollo_mcp.config import Config

BASE = "https://apollo.test"
ISSUER = "https://kc.test/realms/apollo"
REALM = ISSUER + "/protocol/openid-connect"


def fake_jwt(**claims) -> str:
    def part(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'HS256'})}.{part(claims)}.sig"


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        base_url=BASE,
        issuer=ISSUER,
        client_id="apollo-mcp",
        token_file=tmp_path / "cfg" / "token.json",
        download_dir=tmp_path / "takes",
    )


@pytest.fixture
def store(config: Config) -> TokenStore:
    return TokenStore(config.token_file)


@pytest.fixture
def signed_in(store: TokenStore) -> str:
    token = fake_jwt(sub="1", exp=time.time() + 7 * 86400)
    store.save(Tokens(apollo_token=token, apollo_exp=time.time() + 7 * 86400))
    return token


@pytest.fixture
async def http():
    async with httpx.AsyncClient() as client:
        yield client
