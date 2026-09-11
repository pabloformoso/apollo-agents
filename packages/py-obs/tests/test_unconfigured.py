"""The load-bearing guarantee: unconfigured means the SDK was never imported.

Not "returned a no-op object" — never imported. OpenTelemetry's own no-op is
free only after ``import opentelemetry.sdk`` and protobuf have been paid for,
and that bill arrives on every pytest collection and every CLI run in a repo
where most processes will never emit a span. Everything else in this package is
a convenience; this is the reason it exists instead of six lines of bootstrap.

Every test here runs in a subprocess: ``sys.modules`` in THIS process is
already full of whatever the rest of the suite imported.
"""

from __future__ import annotations

import pytest

from conftest import HAS_OTEL, run_python

_NO_SDK = """
import sys
import deus_obs
cfg = deus_obs.install({endpoint})
assert not cfg.enabled, cfg
leaked = [m for m in sys.modules if m.startswith("opentelemetry")]
assert not leaked, leaked
print("OK")
"""


def test_import_alone_does_not_touch_opentelemetry():
    run = run_python(
        "import sys, deus_obs\n"
        "leaked = [m for m in sys.modules if m.startswith('opentelemetry')]\n"
        "assert not leaked, leaked\n"
        "print('OK')\n"
    )
    assert run.clean, run
    assert run.out == "OK\n"


def test_install_without_endpoint_does_not_touch_opentelemetry(monkeypatch):
    """The endpoint check happens BEFORE the import, not after."""
    run = run_python(_NO_SDK.format(endpoint="None"))
    assert run.clean, run
    assert run.out == "OK\n"


def test_helpers_work_and_import_nothing_when_unconfigured():
    run = run_python(
        """
import sys
import deus_obs

deus_obs.install()

@deus_obs.tool
def pick(genre: str) -> str:
    return genre.upper()

assert pick("techno") == "TECHNO"
with deus_obs.session_scope("s-1", user_id="pablo"):
    with deus_obs.span("build", genre="techno") as sp:
        sp.set_attribute("anything", 1)
        assert deus_obs.current_trace_id() is None
assert deus_obs.tracer() is not None
assert deus_obs.flush() is False
deus_obs.shutdown()

leaked = [m for m in sys.modules if m.startswith("opentelemetry")]
assert not leaked, leaked
print("OK")
"""
    )
    assert run.clean, run
    assert run.out == "OK\n"


def test_install_with_endpoint_is_silent():
    """DoD (a): install("x") succeeds and prints nothing.

    Without the [otel] extra that is the ImportError path degrading in silence;
    with it, it is a provider being built for an endpoint nobody will reach.
    Neither may write to stdout or stderr: a library that prints has taken the
    decision away from the application it was supposed to observe.
    """
    run = run_python("import deus_obs; deus_obs.install('x')\n")
    assert run.code == 0, run
    assert run.out == "", run.out
    assert run.err == "", run.err


@pytest.mark.skipif(HAS_OTEL, reason="needs an environment WITHOUT the [otel] extra")
def test_missing_extra_degrades_to_noop_with_a_reason():
    run = run_python(
        """
import deus_obs
cfg = deus_obs.install("http://localhost:6006")
assert not cfg.enabled, cfg
assert "opentelemetry" in cfg.reason, cfg.reason
assert cfg.status_line().startswith("deus_obs: tracing disabled"), cfg.status_line()
print("OK")
"""
    )
    assert run.clean, run


@pytest.mark.skipif(not HAS_OTEL, reason="needs the [otel] extra")
def test_configured_install_does_import_the_sdk():
    """The other half of the promise: when you DO ask, you get the real thing."""
    run = run_python(
        """
import sys
import deus_obs
cfg = deus_obs.install("http://127.0.0.1:9", project="probe", service="probe-svc")
assert cfg.enabled, cfg
assert cfg.endpoint == "http://127.0.0.1:9/v1/traces", cfg.endpoint
assert "opentelemetry.sdk.trace" in sys.modules
print("OK")
"""
    )
    assert run.clean, run
