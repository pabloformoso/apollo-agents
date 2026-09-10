"""Endpoint precedence, and the difference between the two OTEL_* variables.

The distinction the OpenTelemetry environment spec draws — signal-specific
variable carries the FULL url, generic variable carries a base — is the kind of
detail that gets flattened by whoever writes the config next, at which point
every span posts to ``/v1/traces/v1/traces`` and Phoenix answers 404 while the
app looks perfectly healthy.
"""

from __future__ import annotations

from deus_obs.config import ObsConfig

BASE = "http://collector:6006"
FULL = "http://collector:6006/v1/traces"


def test_no_configuration_is_disabled():
    cfg = ObsConfig.from_env(env={})
    assert not cfg.enabled
    assert cfg.status_line() == "deus_obs: tracing disabled (no endpoint configured)"


def test_explicit_argument_wins_and_gets_the_signal_path():
    cfg = ObsConfig.from_env(BASE, env={"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://other/x"})
    assert cfg.endpoint == FULL


def test_signal_specific_variable_is_taken_verbatim():
    cfg = ObsConfig.from_env(env={"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": FULL})
    assert cfg.endpoint == FULL
    assert cfg.source == "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"


def test_generic_variable_gets_the_signal_path_appended():
    cfg = ObsConfig.from_env(env={"OTEL_EXPORTER_OTLP_ENDPOINT": BASE})
    assert cfg.endpoint == FULL


def test_trailing_slash_does_not_double_up():
    cfg = ObsConfig.from_env(env={"OTEL_EXPORTER_OTLP_ENDPOINT": BASE + "/"})
    assert cfg.endpoint == FULL


def test_obs_endpoint_is_the_lowest_rung():
    env = {"OTEL_EXPORTER_OTLP_ENDPOINT": BASE, "OBS_ENDPOINT": "http://ignored:1"}
    assert ObsConfig.from_env(env=env).endpoint == FULL
    assert ObsConfig.from_env(env={"OBS_ENDPOINT": BASE}).endpoint == FULL


def test_empty_variables_fall_through():
    """Compose writes ``KEY: ""`` to shadow an env_file entry — that is a miss."""
    env = {
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "  ",
        "OBS_ENDPOINT": BASE,
    }
    assert ObsConfig.from_env(env=env).endpoint == FULL


def test_obs_enabled_off_beats_a_configured_endpoint():
    cfg = ObsConfig.from_env(BASE, env={"OBS_ENABLED": "false"})
    assert not cfg.enabled
    assert cfg.status_line() == "deus_obs: tracing disabled (OBS_ENABLED is off)"


def test_capture_defaults_to_metadata_and_rejects_nonsense():
    assert ObsConfig.from_env(env={}).capture == "metadata"
    assert ObsConfig.from_env(env={"OBS_CAPTURE": "everything"}).capture == "metadata"
    assert ObsConfig.from_env(env={"OBS_CAPTURE": "FULL"}).capture == "full"
    assert ObsConfig.from_env(env={"OBS_CAPTURE": "off"}).capture == "off"


def test_project_falls_back_to_service_then_to_a_placeholder():
    assert ObsConfig.from_env(env={"OBS_SERVICE": "apollo-backend"}).project == "apollo-backend"
    assert ObsConfig.from_env(env={"OBS_PROJECT": "apollo"}).project == "apollo"
    assert ObsConfig.from_env(env={}).project == "unknown-service"


def test_sample_ratio_is_clamped_and_survives_a_typo():
    assert ObsConfig.from_env(env={"OBS_SAMPLE_RATIO": "0.25"}).sample_ratio == 0.25
    assert ObsConfig.from_env(env={"OBS_SAMPLE_RATIO": "9"}).sample_ratio == 1.0
    assert ObsConfig.from_env(env={"OBS_SAMPLE_RATIO": "-1"}).sample_ratio == 0.0
    assert ObsConfig.from_env(env={"OBS_SAMPLE_RATIO": "a lot"}).sample_ratio == 1.0


def test_status_line_names_the_endpoint_and_the_project():
    cfg = ObsConfig.from_env(BASE, env={"OBS_PROJECT": "apollo"})
    assert cfg.status_line() == f"deus_obs: tracing -> {FULL} (project=apollo)"
    assert cfg.status_line().isascii()
