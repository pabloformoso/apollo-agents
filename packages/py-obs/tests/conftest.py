"""Shared helpers.

Several of the guarantees in this package are about what a FRESH interpreter
does — which modules it imported, what a provider looks like before anything
else has touched it, whether install() after shutdown() re-arms. None of those
can be asserted inside a pytest process that has already imported everything
and installed a set-once global. So they run in a subprocess and are checked
from its exit code and output.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

try:  # the whole suite runs twice: with the [otel] extra and without it
    import opentelemetry.sdk  # noqa: F401

    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False


@dataclass
class Run:
    code: int
    out: str
    err: str

    @property
    def clean(self) -> bool:
        return self.code == 0 and self.err == ""


def run_python(source: str) -> Run:
    """Execute ``source`` in a fresh interpreter with this environment."""
    proc = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return Run(proc.returncode, proc.stdout, proc.stderr)
