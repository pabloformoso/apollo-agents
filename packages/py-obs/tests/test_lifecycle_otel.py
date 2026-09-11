"""install() twice, install() after shutdown(), and a collector that is not there.

All in subprocesses, because ``set_tracer_provider`` is set-once per process:
the interesting states are "a provider is already global" and "the global
provider has been drained", and a test process only gets to be in each of them
once.
"""

from __future__ import annotations

import pytest

from conftest import HAS_OTEL, run_python

pytestmark = pytest.mark.skipif(not HAS_OTEL, reason="needs the [otel] extra")

_COUNT = """
from opentelemetry.sdk.trace.export import BatchSpanProcessor
def batch_processors(provider):
    return [
        p for p in provider._active_span_processor._span_processors
        if isinstance(p, BatchSpanProcessor)
    ]
"""


def test_second_install_does_not_stack_a_second_exporter():
    """Rule 4. Two BatchSpanProcessors means every span exported twice, forever."""
    run = run_python(
        _COUNT
        + """
import deus_obs
from deus_obs import runtime

deus_obs.install("http://127.0.0.1:9", project="p")
first = runtime._PROVIDER
assert len(batch_processors(first)) == 1

deus_obs.install("http://127.0.0.1:9", project="p")
assert runtime._PROVIDER is first
assert len(batch_processors(first)) == 1
print("OK")
"""
    )
    assert run.clean, run


def test_a_module_reload_does_not_stack_a_second_exporter():
    """The case the module sentinel cannot see: fresh module, same process.

    This is uvicorn --reload. ``_INSTALLED`` is back to False because the
    module object is new; the global provider from before is not.
    """
    run = run_python(
        _COUNT
        + """
import deus_obs
from deus_obs import runtime

deus_obs.install("http://127.0.0.1:9", project="p")
provider = runtime._PROVIDER
runtime._reset_for_tests()            # what re-importing the module looks like

cfg = deus_obs.install("http://127.0.0.1:9", project="p")
assert cfg.enabled, cfg
assert runtime._PROVIDER is provider
assert len(batch_processors(provider)) == 1
print("OK")
"""
    )
    assert run.clean, run


def test_install_after_shutdown_re_arms_the_drained_provider():
    """A drained processor accepts spans and drops them — silent loss."""
    run = run_python(
        _COUNT
        + """
import deus_obs
from deus_obs import runtime

deus_obs.install("http://127.0.0.1:9", project="p")
provider = runtime._PROVIDER
deus_obs.shutdown()
assert runtime.active_tracer() is None

cfg = deus_obs.install("http://127.0.0.1:9", project="p")
assert cfg.enabled, cfg
assert runtime._PROVIDER is provider
assert len(batch_processors(provider)) == 2   # the drained one, plus a live one
assert "re-armed" in cfg.reason, cfg.reason
print("OK")
"""
    )
    assert run.clean, run


def test_a_foreign_provider_is_adopted_and_said_so():
    run = run_python(
        """
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
trace.set_tracer_provider(TracerProvider())

import deus_obs
cfg = deus_obs.install("http://127.0.0.1:9", project="p")
assert cfg.enabled, cfg
assert "installed by something else" in cfg.reason, cfg.reason
print("OK")
"""
    )
    assert run.clean, run


def test_an_unreachable_collector_does_not_degrade_the_application():
    """DoD (g). Refused connections belong to the exporter's thread, not the app.

    Port 9 is discard, and nothing is listening. Every call below must return
    normally and the process must exit 0: an application that cannot start
    because a trace store is down has made observability a liability.
    """
    run = run_python(
        """
import time
import deus_obs

cfg = deus_obs.install("http://127.0.0.1:9", project="p")
assert cfg.enabled, cfg

@deus_obs.tool
def pick(genre): return genre.upper()

start = time.monotonic()
with deus_obs.session_scope("s-1"):
    for _ in range(50):
        assert pick("techno") == "TECHNO"
deus_obs.flush()
deus_obs.shutdown()
elapsed = time.monotonic() - start
assert elapsed < 20, elapsed
print("OK")
"""
    )
    assert run.code == 0, run
    assert run.out == "OK\n"


def test_shutdown_before_install_is_a_no_op():
    run = run_python("import deus_obs; deus_obs.shutdown(); deus_obs.flush(); print('OK')")
    assert run.clean, run
