"""deus_obs — OpenTelemetry traces for LLM apps, and nothing until you ask.

    import deus_obs

    cfg = deus_obs.install()          # reads the environment; returns what it did
    print(cfg.status_line())          # one honest line, disabled or not

    @deus_obs.tool
    def pick_track(genre: str, context_variables: dict) -> str:
        ...

    with deus_obs.session_scope(session_id, user_id=user):
        with deus_obs.span("build_playlist", genre=genre):
            ...

    deus_obs.shutdown()               # flush, then stop

Importing this module costs stdlib only, and ``install()`` without a configured
endpoint adds nothing to that: the ``opentelemetry`` import lives inside
``install()``, BELOW the endpoint check. Measured here over 7 fresh
interpreters — 9.7 ms bare, 25 ms with this package imported and installed
unconfigured, 107 ms with the SDK. Every helper below is safe to call, and
every decorator safe to apply, in the unconfigured state.

The public surface is these ten names and no more. Anything else in the
package is an implementation detail that will move.
"""

from .api import agent, chain, current_trace_id, session_scope, span, tool, tracer
from .runtime import flush, install, shutdown

__all__ = [
    "install",
    "shutdown",
    "flush",
    "tracer",
    "span",
    "tool",
    "chain",
    "agent",
    "session_scope",
    "current_trace_id",
]

__version__ = "0.1.0"
