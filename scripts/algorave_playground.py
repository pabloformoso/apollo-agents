"""The playground's mind button, one endpoint deep (plan §9 stage 1).

The spike page can already play Strudel and `agent/generative/strudel_mind.py`
can already write it; what was missing is the wire between them. This is that
wire and nothing else: a local HTTP server whose single endpoint takes the code
currently in the editor plus an intent, hands both to `StrudelMind`, and returns
the validated mutation for the page to diff, audition and apply.

Deliberately small, and deliberately NOT part of the web backend:

* **Stdlib only.** `http.server` costs no dependency and the whole surface is
  one route; FastAPI would buy schema validation we can write in twenty lines
  and cost a `uv sync --group web` in a spike that is meant to run anywhere.
* **Port 4032.** 4010/4020 are the running prod stack, 4011/4021 the dev pair,
  4031 the spike's static server (`scripts/algorave-spike/serve.mjs`). Nothing
  here may collide with a live session.
* **The page is a different origin** (it is served by serve.mjs on 4031), so
  CORS is load-bearing rather than decorative — and the headers go on the ERROR
  responses too, because a 502 the browser refuses to let the page read is a
  swallowed error, which is the one thing this endpoint must never do.
* **No `load_dotenv`, anywhere.** `--base-url` and `--model` are explicit
  arguments for the reason `bench_extend_set.py` learned the hard way on
  2026-08-14: a stale worktree `.env` silently redirected a whole run to a dead
  host, and a dead endpoint looks exactly like a mute model in the results.

`--mock` is the mode that makes this testable and demoable with no model at all:
it never builds an LLM client, substituting a canned deterministic mutation for
the completion call. Everything downstream is real — the mutation still goes
through `StrudelMind`, which still shells out to `node validate.mjs`, so a mock
request exercises the entire request -> validate -> respond path, including the
verdict stats the page displays. What it does not exercise is the model.

Usage:
    uv run python scripts/algorave_playground.py --mock
    uv run python scripts/algorave_playground.py --model qwen/qwen3.6-27b

Endpoint:
    POST /mind  {"code": str, "intent": str, "genre"?: str, "key"?: str,
                 "bars_elapsed"?: int, "recent_reasons"?: [str], "b2b"?: bool}
      200 {"code", "reason", "stats"}      a validated pattern
      400 {"error", "detail"}              malformed request
      502 {"error", "detail"}              StrudelMindError — detail carries
                                           BOTH validator errors; hold the code
      503 {"error", "detail"}              validator missing (npm install)
      500 {"error", "detail"}              anything else, never swallowed
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.generative import strudel_mind  # noqa: E402
from agent.generative.strudel_mind import (  # noqa: E402
    DEFAULT_KEY,
    FEW_SHOT_DEEPHOUSE,
    StrudelMind,
    StrudelMindError,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4032

# The spike page's origin, both spellings — a browser sends whichever the user
# typed, and they are different origins to the same server.
SPIKE_ORIGINS = ("http://127.0.0.1:4031", "http://localhost:4031")

# Same defaults as scripts/bench_strudel_mind.py: the tunnel, explicit.
DEFAULT_BASE_URL = "http://100.68.5.104:1234/v1"
# The bench picks the final answer; this is the current live-DJ default, which
# is the fastest thing on the tunnel and therefore the right thing to jam on.
DEFAULT_MODEL = "google/gemma-4-e4b"
DEFAULT_GENRE = "deep"

# A pattern is a few hundred bytes. Anything past this is not an editor buffer.
MAX_BODY_BYTES = 256 * 1024


class BadRequest(ValueError):
    """The request never reached the mind — 400, with what was wrong."""


# ---------------------------------------------------------------------------
# Request parsing (pure — unit-tested without a socket)
# ---------------------------------------------------------------------------

def parse_request(
    body: bytes,
    *,
    default_genre: str = DEFAULT_GENRE,
    default_key: str = DEFAULT_KEY,
) -> dict:
    """Normalise a /mind body, or raise `BadRequest` naming the offending field.

    `code` may be empty or absent — that is the "nothing is playing, open the
    set" case the mind already handles. `intent` may not: without it there is no
    decision to make, and defaulting it would silently turn a page bug into a
    random mutation.
    """
    if len(body) > MAX_BODY_BYTES:
        raise BadRequest(f"body is larger than {MAX_BODY_BYTES} bytes")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BadRequest(f"body is not valid UTF-8: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BadRequest(f"body is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise BadRequest(
            f"body must be a JSON object with code+intent, got {type(payload).__name__}"
        )

    code = payload.get("code", "")
    if not isinstance(code, str):
        raise BadRequest(f"'code' must be a string, got {type(code).__name__}")

    intent = payload.get("intent")
    if not isinstance(intent, str):
        raise BadRequest(
            "'intent' must be a string — it is the whole request"
            if intent is None
            else f"'intent' must be a string, got {type(intent).__name__}"
        )

    genre = payload.get("genre", default_genre)
    if not isinstance(genre, str):
        raise BadRequest(f"'genre' must be a string, got {type(genre).__name__}")

    key = payload.get("key", default_key)
    if not isinstance(key, str):
        raise BadRequest(f"'key' must be a string, got {type(key).__name__}")

    bars = payload.get("bars_elapsed", 0)
    # bool is an int in Python; a JSON `true` here is a page bug, not a bar count.
    if isinstance(bars, bool) or not isinstance(bars, int) or bars < 0:
        raise BadRequest(f"'bars_elapsed' must be a non-negative integer, got {bars!r}")

    reasons = payload.get("recent_reasons", [])
    if not isinstance(reasons, list) or any(not isinstance(r, str) for r in reasons):
        raise BadRequest("'recent_reasons' must be a list of strings")

    # §9.2: the page sends `b2b: true` while the pen is alternating. Optional
    # (a free-mode body is iteration 2's, unchanged) and strictly boolean — a
    # truthy "yes" or 1 here would be the page telling the mind it is in a duet
    # by accident, which is a prompt change, so it is a 400 rather than a coerce.
    b2b = payload.get("b2b", False)
    if not isinstance(b2b, bool):
        raise BadRequest(f"'b2b' must be a boolean, got {type(b2b).__name__}")

    return {
        "code": code,
        "intent": intent,
        "genre": genre,
        "key": key,
        "bars_elapsed": bars,
        "recent_reasons": reasons,
        "b2b": b2b,
    }


def state_for(request: dict) -> dict:
    """The `state` dict `StrudelMind.next_code` expects (§8.2).

    A non-empty `current_code` is what turns the call into a MUTATION of the
    code on screen instead of a fresh pattern — the whole point of a playground.

    `b2b` is forwarded ONLY when true. `strudel_mind` reads it as truthy, and a
    state carrying `b2b: false` would put the flag in the serialized state of
    every free-mode call — a different prompt for a request that is not a duet,
    for no gain. Absent means free, which is what free-mode pages already send.
    """
    state = {
        "current_code": request["code"],
        "bars_elapsed": request["bars_elapsed"],
        "recent_reasons": request["recent_reasons"],
    }
    if request.get("b2b"):
        state["b2b"] = True
    return state


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

def cors_headers(origin: str | None, allowed=SPIKE_ORIGINS) -> dict[str, str]:
    """Headers that let the 4031 page read a 4032 response — errors included.

    An unlisted origin gets `Vary: Origin` and nothing else: the browser then
    refuses the read, which is the correct answer for a page we did not ship.
    """
    headers = {"Vary": "Origin"}
    if origin and origin in allowed:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        headers["Access-Control-Allow-Headers"] = "content-type"
        headers["Access-Control-Max-Age"] = "600"
    return headers


# ---------------------------------------------------------------------------
# The mock mind (--mock): a deterministic mutation, no network, real validator
# ---------------------------------------------------------------------------

# Numeric `.gain(0.92)` only — `.gain("[0.44 0.38]*4")` is a mini-notation
# string, and rewriting one of those needs a parser rather than a nudge.
_GAIN_RE = re.compile(r"\.gain\(\s*(\d*\.?\d+)\s*\)")
_LEADING_REASON_RE = re.compile(r"\A[ \t]*//[ \t]*reason[ \t]*:[^\n]*\n?", re.IGNORECASE)

MOCK_GAIN_FACTOR = 0.85
MOCK_MIN_GAIN = 0.05


def strip_leading_reason(code: str) -> str:
    """Drop a leading `// reason:` line so reasons replace rather than stack."""
    return _LEADING_REASON_RE.sub("", code or "", count=1)


def mock_mutate(code: str, intent: str) -> str:
    """The canned mutation: one visible, deterministic, still-valid change.

    Visible so the page's diff has something to mark, deterministic so a test
    can assert on it, and small enough that the result is still valid Strudel —
    the point of --mock is to exercise the real validator, which it only does if
    the mutation survives it.
    """
    opened_from_nothing = not (code or "").strip()
    base = strip_leading_reason(code).strip()
    if not base:
        base = strip_leading_reason(FEW_SHOT_DEEPHOUSE).strip()

    match = _GAIN_RE.search(base)
    if match:
        old = float(match.group(1))
        new = max(MOCK_MIN_GAIN, round(old * MOCK_GAIN_FACTOR, 3))
        mutated = f"{base[:match.start()]}.gain({new:g}){base[match.end():]}"
        what = f"pulled the first gain {old:g} -> {new:g}"
    else:
        # No numeric gain to nudge: trim the master instead. `.mul(gain(x))`
        # scales every layer's own gain rather than overwriting it (the idiom
        # the system prompt teaches), and wrapping keeps it one expression.
        mutated = f"({base}).mul(gain({MOCK_GAIN_FACTOR:g}))"
        what = f"no numeric gain to pull, so trimmed the master with .mul(gain({MOCK_GAIN_FACTOR:g}))"

    if opened_from_nothing:
        what = f"opened with the seed groove and {what}"
    return f"// reason: mock — {what} (intent: {intent.strip() or 'none'})\n{mutated}"


def mock_llm(code: str, intent: str):
    """A `StrudelMind`-shaped transport that answers from `mock_mutate`.

    Bound to this request's code and intent rather than parsing them back out
    of the rendered prompt: the prompt is the mind's business, and a mock that
    scrapes it would break every time the prompt is reworded.
    """

    def llm(system: str, user: str) -> str:  # noqa: ARG001 — same signature as the real one
        return mock_mutate(code, intent)

    return llm


# ---------------------------------------------------------------------------
# Mind factories: one `StrudelMind` per request, since genre/key are per request
# ---------------------------------------------------------------------------

def mock_mind_factory():
    """`request -> StrudelMind` that never touches the network."""

    def factory(request: dict) -> StrudelMind:
        return StrudelMind(
            llm=mock_llm(request["code"], request["intent"]),
            genre=request["genre"],
            key=request["key"],
        )

    return factory


def _make_llm_helper():
    """`scripts/bench_strudel_mind.py`'s `make_llm`, reused if it imports.

    Same request shape as the bench means what the playground jams on is what
    the bench measured. `scripts/` carries an `__init__.py`, so the import
    normally works; the mirror below keeps the playground runnable if it ever
    stops working (a renamed script, a partial checkout) instead of failing at
    the first mind click.
    """
    try:
        from scripts.bench_strudel_mind import make_llm  # noqa: PLC0415

        return make_llm
    except Exception:  # noqa: BLE001 — a missing bench must not ground the playground

        def make_llm(client, model: str, max_tokens: int):
            def llm(system: str, user: str) -> str:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    max_tokens=max_tokens,
                )
                return resp.choices[0].message.content or ""

            return llm

        return make_llm


def llm_mind_factory(base_url: str, model: str, api_key: str, max_tokens: int, timeout: float):
    """`request -> StrudelMind` on an EXPLICIT client (never env detection).

    The client is built once, here, so a missing `openai` or a bad base URL
    fails at startup with a traceback the operator sees, rather than as a 500
    on the first click.
    """
    from openai import OpenAI  # noqa: PLC0415 — keeps import cost off --help

    client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    make_llm = _make_llm_helper()

    def factory(request: dict) -> StrudelMind:
        return StrudelMind(
            llm=make_llm(client, model, max_tokens),
            genre=request["genre"],
            key=request["key"],
        )

    return factory


def build_mind_factory(args) -> object:
    """Pick the factory `main` will serve with. `--mock` builds NO client."""
    if args.mock:
        return mock_mind_factory()
    return llm_mind_factory(
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
    )


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def make_handler(
    mind_factory,
    *,
    default_genre: str = DEFAULT_GENRE,
    default_key: str = DEFAULT_KEY,
    allowed_origins=SPIKE_ORIGINS,
    quiet: bool = False,
):
    """A handler class bound to one mind factory (the tests inject their own)."""

    class PlaygroundHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "ApolloAlgoravePlayground/1.0"

        # -- plumbing ------------------------------------------------------

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "no-store")
            for name, value in cors_headers(self.headers.get("Origin"), allowed_origins).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> bytes:
            """Always drain the body — an undrained one desyncs keep-alive."""
            try:
                length = int(self.headers.get("content-length") or 0)
            except ValueError:
                return b""
            return self.rfile.read(max(0, min(length, MAX_BODY_BYTES + 1)))

        def log_message(self, fmt: str, *args) -> None:  # noqa: A002
            if not quiet:
                sys.stderr.write(f"[playground] {self.address_string()} {fmt % args}\n")

        # -- routes --------------------------------------------------------

        def do_OPTIONS(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's naming
            """Preflight. 204 + the CORS headers, even for an unknown path."""
            self.send_response(204)
            self.send_header("content-length", "0")
            for name, value in cors_headers(self.headers.get("Origin"), allowed_origins).items():
                self.send_header(name, value)
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?")[0] == "/mind":
                self._send_json(405, {
                    "error": "/mind is POST only",
                    "detail": 'POST {"code": "...", "intent": "..."} as JSON.',
                })
                return
            self._send_json(404, {
                "error": f"no route {self.path}",
                "detail": "This server has one endpoint: POST /mind. The PAGE is "
                          "served by scripts/algorave-spike/serve.mjs on 4031.",
            })

        def do_POST(self) -> None:  # noqa: N802
            raw = self._read_body()
            if self.path.split("?")[0] != "/mind":
                self._send_json(404, {
                    "error": f"no route {self.path}",
                    "detail": "This server has one endpoint: POST /mind.",
                })
                return

            try:
                request = parse_request(raw, default_genre=default_genre, default_key=default_key)
            except BadRequest as exc:
                self._send_json(400, {"error": "malformed request", "detail": str(exc)})
                return

            # Environment (503) is a different failure from the model (502): one
            # is fixed with `npm install`, the other by asking again. Checking
            # up front is what keeps them apart — `next_code` would raise the
            # same exception type for both.
            try:
                strudel_mind.require_validator()
            except StrudelMindError as exc:
                self._send_json(503, {
                    "error": "the Strudel validator is unavailable — nothing was asked of the mind",
                    "detail": str(exc),
                })
                return

            try:
                out = mind_factory(request).next_code(state_for(request), request["intent"])
            except StrudelMindError as exc:
                # The message from a double failure carries BOTH validator
                # errors; it goes out whole, because which two ways it failed is
                # the entire diagnosis.
                self._send_json(502, {
                    "error": "the mind could not produce valid Strudel — keep playing what you have",
                    "detail": str(exc),
                })
                return
            except Exception as exc:  # noqa: BLE001 — a swallowed error is the one unacceptable outcome
                self._send_json(500, {
                    "error": "the mind call failed",
                    "detail": f"{type(exc).__name__}: {exc}",
                })
                return

            self._send_json(200, {
                "code": out.code,
                "reason": out.reason,
                "stats": out.stats or {},
            })

    return PlaygroundHandler


def make_server(
    mind_factory,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    **handler_kwargs,
) -> ThreadingHTTPServer:
    """An unstarted server. Threaded so a slow model does not wedge the page."""
    return ThreadingHTTPServer((host, port), make_handler(mind_factory, **handler_kwargs))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind address (loopback by default).")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="4032: 4010/4020 are prod, 4011/4021 dev, 4031 the spike page.")
    parser.add_argument("--mock", action="store_true",
                        help="No LLM client at all: a canned deterministic mutation through "
                             "the REAL validator. The whole path, zero network.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help="OpenAI-compatible endpoint. Explicit on purpose — a stale env "
                             "var once redirected a whole bench to a dead host (2026-08-14).")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="Model id. The bench picks the final default; this is the current one.")
    parser.add_argument(
        "--api-key",
        default=os.getenv("LITELLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "lm-studio",
        help="Local servers ignore it; a LiteLLM proxy 401s on anything but its key.",
    )
    parser.add_argument("--max-tokens", type=int,
                        default=int(os.getenv("GENERATIVE_MAX_TOKENS", "4096")),
                        help="Completion budget — reasoners think before they code.")
    parser.add_argument("--timeout", type=float, default=120.0,
                        help="Per-call transport timeout in seconds.")
    parser.add_argument("--genre", default=DEFAULT_GENRE,
                        help="Default idiom brief; a request may override it.")
    parser.add_argument("--key", default=DEFAULT_KEY,
                        help="Default musical key; a request may override it.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    factory = build_mind_factory(args)

    server = make_server(
        factory, args.host, args.port,
        default_genre=args.genre, default_key=args.key,
    )
    host, port = server.server_address[0], server.server_address[1]

    banner = [
        f"playground: http://{host}:{port}/mind  (POST)",
        f"mode      : {'MOCK — canned mutation, no LLM client built' if args.mock else args.model}",
    ]
    if not args.mock:
        banner.append(f"endpoint  : {args.base_url}")
    banner += [
        f"genre     : {args.genre}   key {args.key}",
        f"validator : {strudel_mind.VALIDATOR}",
        f"page      : {SPIKE_ORIGINS[0]}/patterns/playground.html  (serve.mjs, separate process)",
    ]

    # A warning, not a refusal: the page renders the 503 with the fix in it, and
    # a server that refused to start would just move that message somewhere the
    # person clicking "mind" cannot see it.
    try:
        strudel_mind.require_validator()
    except StrudelMindError as exc:
        banner.append(f"WARNING   : {exc}")
        banner.append("            Every /mind request will answer 503 until that is fixed.")

    banner.append("Ctrl-C to stop.")
    # Flushed explicitly: stdout is block-buffered whenever this is piped or run
    # detached, and a server whose banner only appears after it dies is a server
    # you cannot tell has started.
    print("\n".join(banner), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
