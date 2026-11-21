"""Where Apollo and its realm are, read from the environment at call time."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "https://apollo.pabloformoso.com"
DEFAULT_ISSUER = "https://keycloak.pabloformoso.com/realms/apollo"
#: A client of its own rather than `apollo-web`: the device grant is enabled
#: on it alone, and its sessions can be listed and revoked apart from the
#: browser's in the Keycloak console.
DEFAULT_CLIENT_ID = "apollo-mcp"


@dataclass(frozen=True)
class Config:
    base_url: str
    issuer: str
    client_id: str
    token_file: Path
    download_dir: Path

    @classmethod
    def from_env(cls) -> Config:
        config_home = Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config")
        data_home = Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        return cls(
            base_url=(os.getenv("APOLLO_MCP_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            issuer=(os.getenv("APOLLO_MCP_ISSUER") or DEFAULT_ISSUER).rstrip("/"),
            client_id=os.getenv("APOLLO_MCP_CLIENT_ID") or DEFAULT_CLIENT_ID,
            token_file=Path(
                os.getenv("APOLLO_MCP_TOKEN_FILE") or config_home / "apollo-mcp" / "token.json"
            ).expanduser(),
            download_dir=Path(
                os.getenv("APOLLO_MCP_DOWNLOAD_DIR") or data_home / "apollo-mcp" / "takes"
            ).expanduser(),
        )
