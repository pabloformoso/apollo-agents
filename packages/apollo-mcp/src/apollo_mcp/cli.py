"""``apollo-mcp`` — run the server (default), or ``login`` / ``logout`` / ``status``.

Login happens in a TERMINAL, not through a tool: the device code has to be
approved by the operator in a browser, and an agent relaying a sign-in URL
it was handed is the shape of a phishing flow worth not normalising.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

import httpx

from .auth import AuthError, Session, TokenStore
from .config import Config


def _print_prompt(url: str, code: str, expires_in: int) -> None:
    print(f"Approve this sign-in in a browser (expires in {expires_in // 60} min):\n", file=sys.stderr)
    print(f"  {url}\n", file=sys.stderr)
    if code:
        print(f"Code: {code}  — check it matches the one the page shows.\n", file=sys.stderr)
    print("Waiting for approval…", file=sys.stderr)


async def _login(config: Config) -> int:
    async with httpx.AsyncClient(timeout=30) as http:
        try:
            tokens = await Session(config, http).login(_print_prompt)
        except AuthError as exc:
            print(f"Login failed: {exc}", file=sys.stderr)
            return 1
    until = datetime.fromtimestamp(tokens.apollo_exp, timezone.utc).astimezone()
    print(f"Signed in to {config.base_url} until {until:%Y-%m-%d %H:%M}.", file=sys.stderr)
    print(f"Token stored at {config.token_file} (0600).", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apollo-mcp")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "login", "logout", "status"])
    args = parser.parse_args(argv)
    config = Config.from_env()

    if args.command == "login":
        return asyncio.run(_login(config))
    if args.command == "logout":
        removed = TokenStore(config.token_file).clear()
        print("Signed out." if removed else "Was not signed in.", file=sys.stderr)
        return 0
    if args.command == "status":
        tokens = TokenStore(config.token_file).load()
        if tokens is None:
            print("Not signed in.", file=sys.stderr)
            return 1
        until = datetime.fromtimestamp(tokens.apollo_exp, timezone.utc).astimezone()
        state = "valid" if tokens.apollo_valid() else "EXPIRED"
        print(f"{config.base_url}: token {state} until {until:%Y-%m-%d %H:%M}", file=sys.stderr)
        return 0 if tokens.apollo_valid() else 1

    from .server import build_server

    build_server(config).run()  # stdio
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
