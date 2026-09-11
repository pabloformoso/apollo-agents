"""Where the endpoint comes from, and what it is allowed to record.

Pure stdlib on purpose: resolving configuration is the step that decides
whether OpenTelemetry gets imported at all, so it cannot itself import it.

THE PRECEDENCE, AND WHY IT HAS FOUR RUNGS
    install(endpoint=...)                 an explicit argument beats the world
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT    verbatim — see below
    OTEL_EXPORTER_OTLP_ENDPOINT           + /v1/traces
    OBS_ENDPOINT                          + /v1/traces
    (nothing)                             no-op

The two OTEL_* names are not ours; they are the OpenTelemetry environment
specification, and the spec says the signal-specific variable carries the FULL
signal URL while the generic one carries a base to which the exporter appends
the signal path. Honouring that difference is what lets this package sit in a
process that already has an OTel-configured sidecar without fighting it.
OBS_ENDPOINT is the friendly alias for the common case, and takes the base
form because "the collector is at http://box:6006" is what an operator knows.

CAPTURE FAILS CLOSED
``OBS_CAPTURE`` defaults to ``metadata``: span names, argument NAMES, types,
timings, errors — no argument values, no return values. The instrumentation
libraries in this space default the other way and record whole prompts and
whole tool payloads, which for this project would mean API keys travelling
inside ``context_variables`` to a trace store shared with two other projects.
Recording values is a decision someone has to make on purpose (``preview``
truncates, ``full`` does not), and even then the redaction list in ``api.py``
still holds.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Mapping

#: Argument- and return-value capture levels, least to most revealing.
CAPTURE_LEVELS = ("off", "metadata", "preview", "full")

DEFAULT_CAPTURE = "metadata"
DEFAULT_SERVICE = "unknown-service"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def _env_flag(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    value = value.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    return default


def _with_signal_path(base: str) -> str:
    """Turn a collector base URL into the traces URL the exporter posts to.

    The base URL lives in the environment and ``/v1/traces`` is appended here,
    never the other way round: an operator setting a variable knows the address
    of the collector, not the shape of the OTLP path, and a half-remembered
    path in a ``.env`` is a silent 404 that looks exactly like a healthy app.
    """
    return f"{base.strip().rstrip('/')}/v1/traces"


def _first_endpoint(env: Mapping[str, str]) -> tuple[str | None, str]:
    """Resolve the traces URL and name the variable it came from."""
    verbatim = (env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or "").strip()
    if verbatim:
        return verbatim, "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
    for name in ("OTEL_EXPORTER_OTLP_ENDPOINT", "OBS_ENDPOINT"):
        base = (env.get(name) or "").strip()
        if base:
            return _with_signal_path(base), name
    return None, ""


def _ratio(value: str | None) -> float:
    if value is None or not value.strip():
        return 1.0
    try:
        parsed = float(value)
    except ValueError:
        # A typo in a sampling ratio must not turn tracing off (or on) by
        # accident. Full sampling is the safe reading of an unreadable value.
        return 1.0
    return min(1.0, max(0.0, parsed))


@dataclass(frozen=True)
class ObsConfig:
    """The resolved answer to "should this process emit, where, and how much".

    ``endpoint is None`` is the single meaning of "no-op". Every other field
    stays populated so a disabled config still prints usefully.
    """

    endpoint: str | None
    project: str
    service: str
    capture: str = DEFAULT_CAPTURE
    sample_ratio: float = 1.0
    console: bool = False
    #: Which variable supplied the endpoint, or why there is none. Diagnostic
    #: only — never branched on.
    source: str = ""
    reason: str = ""

    @property
    def enabled(self) -> bool:
        return self.endpoint is not None

    @classmethod
    def from_env(
        cls,
        endpoint: str | None = None,
        *,
        project: str | None = None,
        service: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ObsConfig:
        env = os.environ if env is None else env

        service_name = (service or env.get("OBS_SERVICE") or "").strip() or DEFAULT_SERVICE
        # The project defaults to the service because a trace store that groups
        # by project is unusable when everything lands in "default" — which is
        # what happens on a SHARED collector the moment one caller forgets.
        project_name = (project or env.get("OBS_PROJECT") or "").strip() or service_name

        capture = (env.get("OBS_CAPTURE") or "").strip().lower() or DEFAULT_CAPTURE
        if capture not in CAPTURE_LEVELS:
            capture = DEFAULT_CAPTURE

        resolved, source = (
            (_with_signal_path(endpoint), "install(endpoint=...)")
            if endpoint
            else _first_endpoint(env)
        )

        base = cls(
            endpoint=resolved,
            project=project_name,
            service=service_name,
            capture=capture,
            sample_ratio=_ratio(env.get("OBS_SAMPLE_RATIO")),
            console=_env_flag(env.get("OBS_CONSOLE"), False),
            source=source,
        )
        if not _env_flag(env.get("OBS_ENABLED"), True):
            # An explicit off beats a configured endpoint, and beats it here
            # rather than in install(), so that every caller — including a test
            # passing endpoint= directly — obeys the same kill switch.
            return base.disabled("OBS_ENABLED is off")
        if resolved is None:
            return base.disabled("no endpoint configured")
        return base

    def disabled(self, reason: str) -> ObsConfig:
        """The same config, demoted to no-op, remembering why."""
        return replace(self, endpoint=None, reason=reason)

    def status_line(self) -> str:
        """The one line a host application prints at startup.

        ASCII only. The main checkout runs on Windows, where a stray arrow
        glyph on a cp1252 console is a UnicodeEncodeError inside the startup
        path — a telemetry banner that takes the app down with it.
        """
        if self.enabled:
            line = f"deus_obs: tracing -> {self.endpoint} (project={self.project})"
            return f"{line} [{self.reason}]" if self.reason else line
        return f"deus_obs: tracing disabled ({self.reason or 'no endpoint configured'})"
