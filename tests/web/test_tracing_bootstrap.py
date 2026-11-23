"""``app._start_tracing`` — the one startup line, in each state it can be in.

Driven with a stand-in for ``deus_obs`` so it runs in CI, where the package
is absent by design. The real install is exercised by
``tests/web/test_tracing_spans.py`` (locally, with the ``obs`` group).
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

app_module = importlib.import_module("web.backend.app")

_ALL = (*app_module._OBS_ENDPOINT_VARS, *app_module._OBS_HEADER_VARS)


class _Cfg:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def status_line(self) -> str:
        if self.enabled:
            return "deus_obs: tracing -> http://phoenix/v1/traces (project=apollo-agents)"
        return "deus_obs: tracing disabled (no endpoint configured)"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in _ALL:
        monkeypatch.delenv(name, raising=False)


def _with_package(monkeypatch, enabled: bool) -> None:
    monkeypatch.setattr(app_module, "deus_obs", SimpleNamespace(install=lambda: _Cfg(enabled)))


def _line(capsys) -> str:
    out = capsys.readouterr().out
    assert out.count("\n") == 1, out  # exactly one line, always
    return out


def test_enabled_without_an_auth_header_says_so(monkeypatch, capsys):
    _with_package(monkeypatch, True)
    app_module._start_tracing()
    assert "no OTLP auth header" in _line(capsys)


@pytest.mark.parametrize("header", app_module._OBS_HEADER_VARS)
def test_enabled_with_an_auth_header_is_just_the_status(monkeypatch, capsys, header):
    _with_package(monkeypatch, True)
    monkeypatch.setenv(header, "Authorization=Bearer%20x")
    app_module._start_tracing()
    line = _line(capsys)
    assert line.startswith("deus_obs: tracing ->")
    assert "auth header" not in line


def test_disabled_does_not_mention_headers(monkeypatch, capsys):
    _with_package(monkeypatch, False)
    app_module._start_tracing()
    assert "auth header" not in _line(capsys)


def test_absent_package_and_no_endpoint_is_silent(monkeypatch, capsys):
    monkeypatch.setattr(app_module, "deus_obs", None)
    app_module._start_tracing()
    assert capsys.readouterr().out == ""


def test_absent_package_with_an_endpoint_is_loud(monkeypatch, capsys):
    monkeypatch.setattr(app_module, "deus_obs", None)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://phoenix:6006")
    app_module._start_tracing()
    assert "uv sync --group obs" in _line(capsys)


def test_fastapi_native_telemetry_is_off():
    """See ``app._FASTAPI_TELEMETRY``: polls and ``?token=`` URLs."""
    assert app_module.app._telemetry["tracing"] is False
    assert app_module.app._telemetry["metrics"] is False
    assert app_module.app._telemetry["logs"] is False
