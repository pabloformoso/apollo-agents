# Capability: Key-Preserving Tempo

## Purpose

Ensure that all BPM/tempo adjustments during mix transitions preserve the original musical key of each track, using high-quality time-stretching rather than pitch-shifting resampling.

## Requirements

### Requirement: Tempo adjustment preserves musical key
The system SHALL adjust track playback tempo without altering pitch. When a track's BPM is changed to match a transition target, the original musical key (as declared in session.json's `camelot_key`) MUST remain invariant.

**Primary files:** `main.py` — `change_speed()` function (line ~176)

#### Scenario: Small BPM delta preserves key
- **WHEN** a track at 130.8 BPM is tempo-adjusted to 127.8 BPM (Δ3.0)
- **THEN** the output audio plays at 127.8 BPM with the same musical key as the original

#### Scenario: Large BPM delta preserves key
- **WHEN** a track at 95.3 BPM is tempo-adjusted to 113.1 BPM (Δ17.8, meet-in-middle)
- **THEN** the output audio plays at 113.1 BPM with the same musical key as the original

#### Scenario: No adjustment needed
- **WHEN** the tempo adjustment factor is within 0.1% of 1.0 (abs(factor - 1.0) < 0.001)
- **THEN** the audio segment is returned unmodified with no processing

### Requirement: Time-stretch uses Rubber Band engine
The system SHALL use the pyrubberband library (Rubber Band C library wrapper) for all time-stretching operations. The system SHALL NOT use librosa's phase vocoder or simple resampling for tempo changes.

**Primary files:** `main.py` — `change_speed()` function, `pyproject.toml`

#### Scenario: Rubber Band processes audio
- **WHEN** a tempo adjustment is applied to any audio segment
- **THEN** the processing is performed by pyrubberband.time_stretch with the Rubber Band engine

#### Scenario: Transient preservation mode
- **WHEN** pyrubberband performs a time-stretch
- **THEN** crispness SHALL be set to maximum (level 6) to preserve percussive transients

### Requirement: Uniform application to all transitions
The system SHALL apply key-preserving time-stretch to every BPM adjustment uniformly. There SHALL be no threshold or condition that falls back to pitch-shifting resampling.

**Primary files:** `main.py` — `change_speed()`, `tempo_ramp()`, `_adjust_outgoing_tail()`, `_prepare_incoming()`

#### Scenario: All callers use time-stretch
- **WHEN** `tempo_ramp()`, `_adjust_outgoing_tail()`, or `_prepare_incoming()` invoke tempo adjustment
- **THEN** the adjustment is performed via key-preserving time-stretch (not resampling)

#### Scenario: Tempo ramp preserves key across steps
- **WHEN** `tempo_ramp()` gradually changes speed across multiple steps
- **THEN** each step uses key-preserving time-stretch so the key remains constant throughout the ramp

### Requirement: pydub AudioSegment interface preserved
The `change_speed()` function (renamed to `change_tempo()`) SHALL accept and return pydub `AudioSegment` objects. All format conversion (pydub <-> numpy float32) SHALL be contained within the function. Callers MUST NOT need modification.

**Primary files:** `main.py` — `change_speed()` / `change_tempo()`

#### Scenario: Drop-in replacement
- **WHEN** existing code calls `change_speed(segment, factor)`
- **THEN** the function accepts the same arguments and returns an AudioSegment with identical sample rate, channels, and sample width as the input

#### Scenario: Stereo audio handled correctly
- **WHEN** a stereo AudioSegment is passed to `change_tempo()`
- **THEN** both channels are time-stretched together and returned as a stereo AudioSegment

### Requirement: pyrubberband added as project dependency
The project SHALL declare pyrubberband as a Python dependency in `pyproject.toml`. Setup documentation SHALL note the system-level `rubberband` library requirement.

**Primary files:** `pyproject.toml`

#### Scenario: Dependency declared
- **WHEN** the project dependencies are installed via `uv sync`
- **THEN** pyrubberband is available for import

#### Scenario: System library documented
- **WHEN** a user sets up the project on macOS
- **THEN** documentation indicates `brew install rubberband` is required
