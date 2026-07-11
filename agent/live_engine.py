"""
LiveEngine — real-time two-deck audio engine for Apollo LiveDJ.

v2.5.1 splits the engine in two:

  ``LiveEngineLocal`` — the original v1.5 implementation (sounddevice +
  pyrubberband + watchdog thread). Used by ``python main.py`` / the CLI flow.
  Behavior is unchanged from v1.5.

  ``LiveEngineBrowser`` — new web-mode implementation. The browser drives
  audio playback (HTML5 ``<audio>`` + Web Audio API). This class keeps the
  playlist state machine and emits the same 6 events as ``LiveEngineLocal``
  but never reads or writes audio buffers. Time-of-playback comes from the
  browser via the WS message ``{type: "playback_pos", track_id, currentTime}``
  every ~250 ms; the watchdog logic lives inside ``report_playback_pos``
  instead of a background thread. v2.5.1 ships without time-stretch on the
  browser path — ``LiveEngineLocal`` keeps the pyrubberband pre-stretch for
  CLI mode where exposing PortAudio is required anyway.

Both implementations satisfy ``LiveEngineProtocol`` so ``agent/live_dj.py``
can talk to either via the same surface (skip / extend / queue_swap /
crossfade_now / get_state / stop). ``LiveEngine`` is kept as an alias for
``LiveEngineLocal`` so external imports (and the existing
``tests/test_live_engine.py`` suite) continue to work unchanged.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from queue import Queue
from typing import Callable, Protocol, runtime_checkable

import numpy as np
import soundfile as sf

from agent.phase_lock import (
    XFADE_EDGE_GUARD_SAMPLES,
    LiveTransitionPlan,
    build_live_transition_plan,
)
from agent.transition_styles import serialise_choice

# sounddevice requires PortAudio — guarded so the module can be imported in
# headless / CI environments without audio hardware.
try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except OSError:  # PortAudio library not found
    sd = None  # type: ignore[assignment]
    _SD_AVAILABLE = False

try:
    import librosa as _librosa
    _HAS_LIBROSA = True
except ImportError:  # pragma: no cover
    _HAS_LIBROSA = False

try:
    import pyrubberband as _pyrubberband
    _HAS_PYRUBBERBAND = True
except ImportError:  # pragma: no cover
    _HAS_PYRUBBERBAND = False

# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------
TRACK_STARTED       = "track_started"
APPROACHING_CF      = "approaching_crossfade"
CROSSFADE_TRIGGERED = "crossfade_triggered"
CROSSFADE_FINISHED  = "crossfade_finished"
TRACK_ENDED         = "track_ended"
SESSION_ENDED       = "session_ended"
# v2.6.0 — Endless / improvisation mode. Fires when only one track is
# left in the queue and the next ``approaching_crossfade`` would trip
# the final SESSION_ENDED. The LLM has ~5 s of grace to call
# ``extend_set`` before the engine deterministically auto-picks an
# in-genre continuation from the catalog.
PLAYLIST_RUNNING_LOW = "playlist_running_low"
ENDLESS_WARNING      = "endless_warning"
# v3.0.1 — phase-lock observability. Fires once per (current → next)
# transition when the planner couldn't land on a phrase boundary
# (16/8/4-bar ladder all rejected) AND fell back to the legacy linear-
# fade path. Surfaces in the UI as a "this transition didn't lock to a
# downbeat — likely missing beatgrid" banner so the DJ knows whether to
# regenerate beatgrids for the affected tracks. Carries the two track
# ids + a ``reason`` enum so the frontend can give actionable guidance.
CRITIC_WARNING       = "critic_warning"

# Human-readable explanations for each ``critic_warning`` reason. The
# UI can either show these verbatim or map the reason enum to its own
# i18n strings — both paths are valid. Keys MUST match the literals in
# ``_maybe_emit_critic_warning``.
_CRITIC_WARNING_MESSAGES = {
    "no_beatgrid_either_side": (
        "Phase-lock unavailable — neither track has a beatgrid. "
        "Run `--build-catalog --extra beatgrid` to regenerate."
    ),
    "no_beatgrid_outgoing": (
        "Phase-lock unavailable — outgoing track is missing its beatgrid. "
        "Regenerate it with `python main.py --fix-incomplete`."
    ),
    "no_beatgrid_incoming": (
        "Phase-lock unavailable — incoming track is missing its beatgrid. "
        "Regenerate it with `python main.py --fix-incomplete`."
    ),
    "no_phrase_anchor_in_window": (
        "Phase-lock fell back — no phrase boundary fits the crossfade "
        "window. The transition will use a linear fade."
    ),
}

# Grace window the LLM gets to append a successor track before the
# deterministic in-engine fallback kicks in.
ENDLESS_GRACE_SEC = 5.0
# Hard cap on how many tracks a single endless session can add. Prevents
# runaway behaviour from a misbehaving agent or LLM hallucinated loops.
# Default of 10000 covers ~a week of streaming at ~1 min/track; override
# via APOLLO_ENDLESS_APPEND_CAP for shorter or longer guardrails.
def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        v = int(raw)
        return v if v > 0 else default
    except ValueError:
        return default


ENDLESS_APPEND_CAP = _env_int("APOLLO_ENDLESS_APPEND_CAP", 10000)

# ---------------------------------------------------------------------------
# Audio constants
# ---------------------------------------------------------------------------
_SAMPLE_RATE        = 44100
_CHANNELS           = 2
_BLOCK_SIZE         = 2048
_BPM_THRESHOLD      = 5      # min BPM diff to trigger time-stretch
_STRETCH_MAX        = 1.5    # safety ceiling (v1.3 bound)
_STRETCH_MIN        = 1.0 / _STRETCH_MAX

_PROJECT_DIR = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Public protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class LiveEngineProtocol(Protocol):
    """Public surface that any LiveEngine implementation must expose.

    Both ``LiveEngineLocal`` (existing sounddevice + pyrubberband path) and
    ``LiveEngineBrowser`` (new — audio plays in the browser, time reported
    via WS) implement this. ``agent/live_dj.py`` talks to either via this
    protocol so the same control plane (skip / extend / queue_swap /
    crossfade_now) works for both.

    Note: ``play()`` accepts an optional ``playlist`` arg. ``LiveEngineLocal``
    was constructed with the playlist in v1.5 and ignores any value passed
    here; ``LiveEngineBrowser`` accepts the playlist in either ``__init__``
    or ``play()``. Either constructor pattern satisfies the protocol.
    """

    def play(self, playlist: list[dict] | None = None) -> None: ...
    def crossfade_now(self) -> str: ...
    def extend_track(self, seconds: int) -> str: ...
    def skip_track(self) -> str: ...
    def queue_swap(self, position: int, track_id: str) -> str: ...
    def set_crossfade_point(self, position_sec: float) -> str: ...
    def get_state(self) -> dict: ...
    def stop(self) -> None: ...
    # v2.5.0.1 — surfaced so the WS handler can advance ``LiveEngineBrowser``
    # when the browser reports a natural end-of-track. ``LiveEngineLocal``
    # never needs this (its watchdog detects end-of-buffer directly), so the
    # implementation falls back to a no-op.
    def report_track_ended(self, track_id: str) -> None: ...


# ---------------------------------------------------------------------------
# LiveEngineLocal (renamed from LiveEngine — v1.5 implementation)
# ---------------------------------------------------------------------------

class LiveEngineLocal:
    """Two-deck real-time DJ engine with local PortAudio output.

    This is the v1.5 implementation, RENAMED from ``LiveEngine`` for v2.5.1.
    Behavior is unchanged — every private method, sounddevice callback,
    pyrubberband pre-stretch, and watchdog thread is the same. The
    ``LiveEngine = LiveEngineLocal`` alias at the bottom of the module keeps
    backward compatibility for external imports and the existing test suite.

    Parameters
    ----------
    playlist:
        List of track dicts from context_variables["playlist"].
    event_queue:
        threading.Queue shared with the LiveDJ agent loop.
    crossfade_sec:
        Crossfade blend duration in seconds (default 12).
    approach_warn_sec:
        How many seconds before the crossfade point to fire APPROACHING_CF (default 30).
    """

    def __init__(
        self,
        playlist: list[dict],
        event_queue: Queue,
        crossfade_sec: int = 12,
        approach_warn_sec: int = 30,
    ) -> None:
        self.playlist = list(playlist)
        self.event_queue = event_queue
        self.crossfade_sec = crossfade_sec
        self.approach_warn_sec = approach_warn_sec

        # State
        self._state = "idle"  # idle | playing | crossfading | ended
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # Audio buffers (float32 stereo numpy arrays)
        self._audio: np.ndarray | None = None        # current track
        self._next_audio: np.ndarray | None = None   # pre-stretched next track
        self._pos: int = 0       # sample index into _audio
        self._cf_start: int = 0  # sample where crossfade started
        self._next_pos: int = 0  # sample index into _next_audio during crossfade
        self._in_point: int = 0  # start offset in _next_audio (from hot cue IN)

        # Playlist tracking
        self._idx: int = 0
        self._extend_samples: int = 0  # extra samples before auto-crossfade

        # v3.0.1 — debounce for ``critic_warning`` (one event per
        # transition pair regardless of how many times the planner
        # re-runs). Mirrors the browser engine's bookkeeping so the agent
        # event log isn't spammed by re-pre-stretches on skip / extend.
        self._critic_warned_for_transition: tuple[int, int] | None = None

        # Watchdog signals
        self._cf_just_finished: bool = False  # set by callback, cleared by watchdog
        self._prev_idx: int = 0

        # v3.0 — phase-lock plan computed once per transition by the
        # prestretch worker. Consumed by ``_cf_point_samples`` (to pick the
        # outgoing-anchor sample) and by ``_audio_callback`` (so the
        # equal-power cos/sin curves run over the exact same window the
        # offline render uses). Reset to ``None`` after each successful
        # crossfade so a degraded next-transition (e.g. missing beatgrid)
        # cleanly falls back to the legacy hot-cue / linear-fade path
        # without inheriting stale anchor data.
        self._transition_plan: LiveTransitionPlan | None = None

        # Threads
        self._stream: sd.OutputStream | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._prestretch_thread: threading.Thread | None = None
        self._prestretch_ready = threading.Event()

        # v2.6.0 — endless / improvisation mode state. Flag flipped by
        # the agent (live_dj.py) or the web WS handler (app.py). All
        # other fields are managed internally by the watchdog loop.
        self._endless_mode: bool = False
        self._low_water_fired: bool = False
        self._low_water_at: float | None = None
        self._endless_appended: int = 0
        # Cached snapshot of tracks.json populated at play() time so the
        # deterministic fallback can read it without disk I/O on the
        # audio-adjacent watchdog thread.
        self._catalog_cache: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def play(self, playlist: list[dict] | None = None) -> None:
        """Start live playback from the first track.

        The optional ``playlist`` argument exists to satisfy
        ``LiveEngineProtocol.play(playlist)`` — when supplied it overrides
        the playlist passed in the constructor. v1.5 callers (and the
        existing ``tests/test_live_engine.py`` suite) still use the no-arg
        form, which keeps using ``self.playlist`` from ``__init__``.
        """
        if playlist is not None:
            self.playlist = list(playlist)
        if not self.playlist:
            self._emit(SESSION_ENDED)
            return

        # v2.6.0 — snapshot the catalog at session start so the
        # endless-mode deterministic fallback can pick a continuation
        # track without doing disk I/O on the watchdog thread. Cheap
        # (~hundreds of KB) and fresh enough for a single set.
        try:
            self._catalog_cache = _load_catalog()
        except Exception:  # noqa: BLE001 — catalog read is non-critical here
            self._catalog_cache = []

        self._audio = self._load_audio(self.playlist[0])
        self._pos = 0
        self._idx = 0
        self._prev_idx = 0
        self._state = "playing"

        if not _SD_AVAILABLE or sd is None:
            raise RuntimeError(
                "sounddevice / PortAudio not available. "
                "Install PortAudio (e.g. 'apt install libportaudio2') to use live mode."
            )

        self._stream = sd.OutputStream(
            samplerate=_SAMPLE_RATE,
            channels=_CHANNELS,
            dtype="float32",
            blocksize=_BLOCK_SIZE,
            callback=self._audio_callback,
        )
        self._stream.start()
        self._emit(TRACK_STARTED, track=self.playlist[0])

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True, name="live-watchdog"
        )
        self._watchdog_thread.start()

        if len(self.playlist) > 1:
            self._start_prestretch(0, 1)

    def crossfade_now(self) -> str:
        """Trigger crossfade immediately, skipping the auto-timer."""
        with self._lock:
            if self._state != "playing":
                return f"Cannot crossfade: engine is '{self._state}'."
            if self._idx + 1 >= len(self.playlist):
                return "No next track to crossfade into."
            # Advance position to the crossfade point so watchdog fires on next tick
            cf = self._cf_point_samples(self.playlist[self._idx])
            self._pos = max(self._pos, cf)
        return "Crossfade triggered."

    def extend_track(self, seconds: int) -> str:
        """Delay the upcoming auto-crossfade by `seconds` seconds."""
        with self._lock:
            self._extend_samples += int(seconds * _SAMPLE_RATE)
        return f"Crossfade delayed by {seconds}s."

    def skip_track(self) -> str:
        """Hard-cut to the next track without crossfade."""
        with self._lock:
            next_idx = self._idx + 1
            if next_idx >= len(self.playlist):
                return "No next track."
            next_audio = (
                self._next_audio
                if self._next_audio is not None
                else self._load_audio(self.playlist[next_idx])
            )
            self._audio = next_audio
            self._pos = self._in_point
            self._next_audio = None
            self._idx = next_idx
            self._extend_samples = 0
            self._state = "playing"
        self._emit(TRACK_STARTED, track=self.playlist[next_idx])
        if next_idx + 1 < len(self.playlist):
            self._start_prestretch(next_idx, next_idx + 1)
        return f"Skipped to '{self.playlist[next_idx]['display_name']}'."

    def queue_swap(self, position: int, track_id: str) -> str:
        """Replace a future playlist position with a catalog track."""
        idx = position - 1
        with self._lock:
            if idx <= self._idx or idx >= len(self.playlist):
                return f"Position {position} is not a future slot."
        catalog = _load_catalog()
        track = next((t for t in catalog if t["id"] == track_id), None)
        if not track:
            return (
                f"Track ID '{track_id}' not found in catalog. "
                "This usually means the id was invented from a song "
                "title — re-run pick_next_track and copy the exact id "
                "from its 'id' column."
            )
        with self._lock:
            self.playlist[idx] = track
        return f"Queued '{track['display_name']}' at position {position}."

    def append_track(self, track: dict) -> str:
        """Append a track to the live playlist mid-flight (v2.6.0 endless mode).

        Thread-safe append. Enforces the session-wide cap. When the
        newly-appended track becomes the immediate successor of the one
        currently playing AND no prestretch is in flight, kicks off
        prestretch so the watchdog's natural crossfade path can pick up
        the new tail without a hard cut. Idempotent: a second
        ``append_track`` while prestretch is already running noops on
        the prestretch side.
        """
        if not track or not track.get("id"):
            return "append_track: track must include an 'id' field."
        with self._lock:
            if self._endless_appended >= ENDLESS_APPEND_CAP:
                msg = (
                    f"Append cap reached ({ENDLESS_APPEND_CAP}); "
                    "ending session after current track."
                )
                cap_reached = True
            else:
                cap_reached = False
                self.playlist.append(dict(track))
                # Reset the low-water guard so a subsequent
                # "running low" can fire when this newly-appended track
                # is itself the last one.
                self._low_water_fired = False
                self._low_water_at = None
                self._endless_appended += 1
            position = len(self.playlist)
            cur_idx = self._idx
            audio_loaded = self._audio is not None
            next_audio_loaded = self._next_audio is not None
            state = self._state
        if cap_reached:
            self._emit(ENDLESS_WARNING, reason="cap_reached", message=msg)
            return msg
        # If the just-appended track is the immediate successor of the
        # one currently playing AND nothing has been prestretched yet,
        # kick off prestretch. Without this, the watchdog's crossfade
        # trigger spins on `_prestretch_ready.wait` forever.
        new_tail_idx = position - 1
        if (
            new_tail_idx == cur_idx + 1
            and audio_loaded
            and not next_audio_loaded
            and state == "playing"
        ):
            self._start_prestretch(cur_idx, new_tail_idx)
        return (
            f"Appended '{track.get('display_name', track['id'])}' "
            f"at position {position}."
        )

    def _maybe_end_or_extend(self, current_track: dict | None) -> bool:
        """Gate ``SESSION_ENDED`` on endless-mode + autoplay fallback.

        Returns ``True`` when the caller should stop (session is truly
        over), ``False`` when the caller should keep looping (a new
        track was just appended or the grace window hasn't elapsed yet).

        - endless OFF: behave as the legacy engine did — emit and stop.
        - endless ON + grace window not yet elapsed: don't emit, the
          watchdog will re-poll on the next tick.
        - endless ON + grace elapsed + LLM already appended: keep
          looping; the new tail track is now the current one's
          successor.
        - endless ON + grace elapsed + no append: try the deterministic
          fallback. On success, append and keep looping. On no
          candidates, emit an ``endless_warning`` and let the legacy
          ``SESSION_ENDED`` fire.
        """
        with self._lock:
            endless = self._endless_mode
            idx = self._idx
            remaining_after = len(self.playlist) - idx - 1
            low_water_at = self._low_water_at

        if not endless:
            self._emit(SESSION_ENDED)
            return True

        # Successor already in the playlist (LLM beat us to it).
        if remaining_after > 0:
            return False

        # No grace window yet — first time we hit the end. Start the
        # clock and let the watchdog re-poll.
        if low_water_at is None:
            with self._lock:
                self._low_water_at = time.monotonic()
            return False

        if (time.monotonic() - low_water_at) < ENDLESS_GRACE_SEC:
            return False

        # Grace elapsed without an append → deterministic fallback.
        with self._lock:
            catalog = list(self._catalog_cache)
            exclude = {t.get("id") for t in self.playlist if t.get("id")}
        # Pull genre from the current track (catalog entries are tagged
        # with ``genre_folder``); falling back to the loose ``genre``
        # field keeps the path resilient against legacy entries.
        genre = (
            (current_track or {}).get("genre_folder")
            or (current_track or {}).get("genre")
        )
        pick = _autoplay_pick(current_track, catalog, genre, exclude, allow_repeats=True)
        if pick is None:
            self._emit(
                ENDLESS_WARNING,
                reason="no_candidates",
                message=(
                    f"No more {genre or 'matching'} tracks left to extend "
                    "with — set ending."
                ),
            )
            self._emit(SESSION_ENDED)
            return True

        # Append + keep looping. The watchdog's NEXT tick will see the
        # new tail track and resume normally.
        self.append_track(pick)
        return False

    def set_crossfade_point(self, position_sec: float) -> str:
        """Manually set where the crossfade begins in the current track."""
        with self._lock:
            if self._audio is None:
                return "No track playing."
            target = int(position_sec * _SAMPLE_RATE)
            current_cf = self._cf_point_samples(self.playlist[self._idx])
            self._extend_samples += target - current_cf
        return f"Crossfade point set to {position_sec:.1f}s."

    def get_state(self) -> dict:
        """Return a snapshot of engine state for the agent."""
        with self._lock:
            idx = self._idx
            pos = self._pos
            state = self._state
            audio_len = len(self._audio) if self._audio is not None else 0

        pos_sec = pos / _SAMPLE_RATE
        track = self.playlist[idx] if idx < len(self.playlist) else None
        next_track = self.playlist[idx + 1] if idx + 1 < len(self.playlist) else None

        if track and audio_len:
            with self._lock:
                cf_sec = self._cf_point_samples(track) / _SAMPLE_RATE
            secs_to_cf = max(0.0, cf_sec - pos_sec)
        else:
            secs_to_cf = 0.0

        return {
            "state": state,
            "position_sec": round(pos_sec, 1),
            "current_track": _track_summary(track),
            "next_track": _track_summary(next_track),
            "seconds_to_crossfade": round(secs_to_cf, 1),
            "playlist_remaining": len(self.playlist) - idx - 1,
        }

    def stop(self) -> None:
        """Stop playback and release audio resources."""
        self._stop_event.set()
        with self._lock:
            self._state = "idle"
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def report_track_ended(self, track_id: str) -> None:  # noqa: ARG002
        """Protocol no-op for the local engine.

        ``LiveEngineLocal`` detects end-of-track by reading the sounddevice
        sample counter directly in ``_audio_callback`` / ``_watchdog_loop`` —
        the browser-side ``ended`` notification is meaningless here. The
        method is required by ``LiveEngineProtocol`` (so the WS handler
        can call it without an isinstance check), but does nothing.
        """
        return None

    # ------------------------------------------------------------------
    # Audio callback (runs in sounddevice's low-latency thread)
    # ------------------------------------------------------------------

    def _audio_callback(
        self, outdata: np.ndarray, frames: int, time_info, status
    ) -> None:
        with self._lock:
            if self._audio is None or self._state == "idle":
                outdata[:] = 0
                return

            if self._state == "playing":
                end = self._pos + frames
                chunk = self._audio[self._pos : end]
                n = len(chunk)
                outdata[:n] = chunk
                if n < frames:
                    outdata[n:] = 0
                self._pos += n

            elif self._state == "crossfading":
                # v3.0 — equal-power cos/sin curves over the absolute
                # position within the cf_len window, with a 64-sample
                # raised-cosine guard at the entry to mask any rounding
                # click. Replaces the pre-v3.0 linear ramp so the live
                # engine sounds identical to the offline render's
                # ``_phase_locked_crossfade`` for the same input.
                cf_elapsed = self._pos - self._cf_start
                cf_len = int(self.crossfade_sec * _SAMPLE_RATE)
                remaining = cf_len - cf_elapsed
                n = min(frames, max(0, remaining))

                if n > 0 and self._next_audio is not None:
                    o_end = min(self._pos + n, len(self._audio))
                    i_end = min(self._next_pos + n, len(self._next_audio))
                    out_chunk = self._audio[self._pos : o_end]
                    in_chunk = self._next_audio[self._next_pos : i_end]
                    actual = min(len(out_chunk), len(in_chunk))
                    if actual > 0:
                        # Phase angle for each sample of this chunk inside
                        # the [0, π/2] crossfade arc. Using the absolute
                        # callback positions (cf_elapsed..cf_elapsed+actual)
                        # rather than a fresh linspace keeps the curve
                        # mathematically identical regardless of how
                        # sounddevice chunks the stream.
                        angles = np.linspace(
                            (cf_elapsed / cf_len) * (np.pi / 2.0),
                            ((cf_elapsed + actual) / cf_len) * (np.pi / 2.0),
                            actual, endpoint=False, dtype=np.float32,
                        )
                        fade_out = np.cos(angles).reshape(-1, 1)
                        fade_in = np.sin(angles).reshape(-1, 1)
                        mixed_out = out_chunk[:actual] * fade_out
                        # Raised-cosine edge guard at the very entry of
                        # the outgoing tail. Matches the offline path's
                        # ``XFADE_EDGE_GUARD_SAMPLES``. If this chunk lies
                        # entirely past the guard window, the slice is
                        # empty and nothing is attenuated.
                        guard_total = min(XFADE_EDGE_GUARD_SAMPLES, cf_len // 2)
                        if guard_total > 0 and cf_elapsed < guard_total:
                            g_lo = cf_elapsed
                            g_hi = min(cf_elapsed + actual, guard_total)
                            g_n = g_hi - g_lo
                            if g_n > 0:
                                ramp = (
                                    0.5
                                    - 0.5
                                    * np.cos(
                                        np.linspace(
                                            (g_lo / guard_total) * np.pi,
                                            (g_hi / guard_total) * np.pi,
                                            g_n, endpoint=False, dtype=np.float32,
                                        )
                                    )
                                ).reshape(-1, 1)
                                mixed_out[:g_n] *= ramp
                        outdata[:actual] = mixed_out + in_chunk[:actual] * fade_in
                        if actual < frames:
                            outdata[actual:] = 0
                        self._pos += actual
                        self._next_pos += actual
                    else:
                        outdata[:] = 0
                else:
                    outdata[:] = 0

                # Crossfade complete: swap tracks
                if remaining <= frames:
                    self._state = "playing"
                    self._audio = self._next_audio
                    self._pos = self._next_pos
                    self._next_audio = None
                    self._extend_samples = 0
                    self._cf_just_finished = True  # watchdog will emit events
                    # Reset the phase-lock plan — the next transition
                    # will build its own from the new current track.
                    self._transition_plan = None

    # ------------------------------------------------------------------
    # Watchdog thread
    # ------------------------------------------------------------------

    def _watchdog_loop(self) -> None:
        approached = False
        cf_triggered = False

        while not self._stop_event.is_set():
            time.sleep(0.05)  # 50 ms granularity

            with self._lock:
                state = self._state
                pos = self._pos
                idx = self._idx
                audio_len = len(self._audio) if self._audio is not None else 0
                cf_just_finished = self._cf_just_finished
                if cf_just_finished:
                    self._cf_just_finished = False

            if state == "idle":
                continue

            # ── Crossfade finished: emit events, advance bookkeeping ─────────
            if cf_just_finished:
                prev_track = self.playlist[self._prev_idx]
                cur_track = self.playlist[idx] if idx < len(self.playlist) else None
                self._emit(CROSSFADE_FINISHED, from_track=prev_track, to_track=cur_track)
                self._emit(TRACK_ENDED, track=prev_track)

                if cur_track:
                    self._emit(TRACK_STARTED, track=cur_track)
                    approached = False
                    cf_triggered = False
                    self._prev_idx = idx
                    if idx + 1 < len(self.playlist):
                        self._start_prestretch(idx, idx + 1)
                else:
                    if self._maybe_end_or_extend(prev_track):
                        return
                    # endless mode auto-appended — pick up the new tail
                    # next tick.
                continue

            if idx >= len(self.playlist):
                if self._maybe_end_or_extend(None):
                    return
                continue

            with self._lock:
                cf_samples = self._cf_point_samples(self.playlist[idx])
            cf_sec = cf_samples / _SAMPLE_RATE
            pos_sec = pos / _SAMPLE_RATE

            # ── APPROACHING_CF warning ───────────────────────────────────────
            if not approached and pos_sec >= cf_sec - self.approach_warn_sec:
                next_idx = idx + 1
                self._emit(
                    APPROACHING_CF,
                    track=self.playlist[idx],
                    next_track=self.playlist[next_idx] if next_idx < len(self.playlist) else None,
                    seconds_remaining=round(max(0.0, cf_sec - pos_sec), 1),
                )
                approached = True
                # v2.6.0 — endless mode poke. Fires once per "approaching
                # the last track" window so the LLM gets a deterministic
                # deadline (vs. polling len(playlist)) to call extend_set.
                # v3.6 — also fires while the LAST track itself plays
                # (remaining == 0): a tail track appended by a previous
                # extension must re-poke the LLM, otherwise only the
                # deterministic fallback ever extends past it.
                with self._lock:
                    remaining = len(self.playlist) - idx - 1
                    fire_low = (
                        self._endless_mode
                        and remaining <= 1
                        and not self._low_water_fired
                    )
                    if fire_low:
                        self._low_water_fired = True
                        self._low_water_at = time.monotonic()
                if fire_low:
                    self._emit(
                        PLAYLIST_RUNNING_LOW,
                        track=self.playlist[idx],
                        seconds_remaining=round(max(0.0, cf_sec - pos_sec), 1),
                    )

            # ── Trigger crossfade ────────────────────────────────────────────
            if not cf_triggered and pos >= cf_samples:
                next_idx = idx + 1
                if next_idx < len(self.playlist):
                    self._prestretch_ready.wait(timeout=3.0)
                    with self._lock:
                        if self._next_audio is not None and self._state == "playing":
                            self._cf_start = pos
                            self._next_pos = self._in_point
                            self._idx = next_idx
                            self._state = "crossfading"
                            cf_triggered = True
                    if cf_triggered:
                        self._emit(
                            CROSSFADE_TRIGGERED,
                            from_track=self.playlist[idx],
                            to_track=self.playlist[next_idx],
                        )
                else:
                    # Last track — let it play to the end
                    if pos >= audio_len:
                        current = self.playlist[idx]
                        self._emit(TRACK_ENDED, track=current)
                        if self._maybe_end_or_extend(current):
                            return
                        # endless mode auto-appended; the current audio
                        # buffer is fully drained so we can't crossfade
                        # — hard-cut to the new tail and reset edges
                        # so APPROACHING_CF can fire for it.
                        with self._lock:
                            has_successor = self._idx + 1 < len(self.playlist)
                        if has_successor:
                            self.skip_track()
                        cf_triggered = False
                        approached = False

    # ------------------------------------------------------------------
    # Pre-stretch thread
    # ------------------------------------------------------------------

    def _start_prestretch(self, current_idx: int, next_idx: int) -> None:
        if self._prestretch_thread and self._prestretch_thread.is_alive():
            return
        self._prestretch_ready.clear()
        self._prestretch_thread = threading.Thread(
            target=self._prestretch_worker,
            args=(current_idx, next_idx),
            daemon=True,
            name="live-prestretch",
        )
        self._prestretch_thread.start()

    def _prestretch_worker(self, current_idx: int, next_idx: int) -> None:
        if next_idx >= len(self.playlist):
            return
        current_track = self.playlist[current_idx]
        next_track = self.playlist[next_idx]

        audio = self._load_audio(next_track)
        audio = self._time_stretch(audio, next_track, current_track)

        # v3.0 — compute the phase-lock plan now that the post-stretch
        # incoming buffer exists. ``incoming_audio_y`` lets
        # ``pick_incoming_anchor`` run its pickup-skip RMS heuristic on
        # the SAME bytes the audio callback will play, so skipping a
        # quiet intro can't disagree with what the user hears.
        plan = self._build_transition_plan_for_next(
            current_track, next_track, audio,
        )

        # Pick the start offset:
        #   - With a phase-lock plan: trim to the chosen incoming anchor
        #     downbeat (or downbeats[1] if pickup-skip fired) so the
        #     incoming buffer's sample 0 IS a downbeat — that's what
        #     makes the overlay-add phase-lock.
        #   - Without a plan (no v2 beatgrid, both sides missing, fallback
        #     tier): fall back to the legacy IN hot cue / 0 path.
        if plan is not None and plan.phrase_tier != "fallback":
            in_pt = max(0, min(plan.incoming_start_sample, len(audio)))
        else:
            in_pt = self._in_point_of(next_track)
        audio_trimmed = audio[in_pt:] if in_pt < len(audio) else audio

        with self._lock:
            self._next_audio = audio_trimmed
            self._in_point = 0  # already trimmed to in-point
            self._transition_plan = plan
        self._prestretch_ready.set()

        # v3.0.1 — surface phase-lock fallbacks to the agent's event
        # log. ``plan is None`` covers the no-duration-data case
        # ``_build_transition_plan_for_next`` returns early on; treat
        # it like a fallback for warning purposes since the audible
        # outcome (linear fade, no downbeat lock) is the same.
        if plan is None or plan.phrase_tier == "fallback":
            self._maybe_emit_critic_warning(
                plan, current_idx, current_track, next_track,
            )

    def _maybe_emit_critic_warning(
        self,
        plan: LiveTransitionPlan | None,
        current_idx: int,
        current_track: dict,
        next_track: dict,
    ) -> None:
        """CLI-side mirror of the browser engine's warning emitter.

        Debounced via ``self._critic_warned_for_transition`` so the
        event fires at most once per (current_idx, next_idx) pair, even
        if the user skips back-and-forth and re-pre-stretches the same
        transition. The agent loop in ``live_dj.py`` consumes the
        event queue; logging this gives operators visible evidence
        that "this transition won't be downbeat-locked, regenerate
        the beatgrid".
        """
        next_idx = current_idx + 1
        key = (current_idx, next_idx)
        if self._critic_warned_for_transition == key:
            return
        self._critic_warned_for_transition = key

        out_bg = current_track.get("beatgrid")
        in_bg = next_track.get("beatgrid")
        if not out_bg and not in_bg:
            reason = "no_beatgrid_either_side"
        elif not out_bg:
            reason = "no_beatgrid_outgoing"
        elif not in_bg:
            reason = "no_beatgrid_incoming"
        else:
            reason = "no_phrase_anchor_in_window"

        self._emit(
            CRITIC_WARNING,
            kind="phase_lock_fallback",
            reason=reason,
            outgoing_track={
                "id": current_track.get("id"),
                "display_name": current_track.get("display_name"),
            },
            incoming_track={
                "id": next_track.get("id"),
                "display_name": next_track.get("display_name"),
            },
            phrase_tier=(plan.phrase_tier if plan is not None else "fallback"),
            message=_CRITIC_WARNING_MESSAGES.get(reason, reason),
        )

    def _build_transition_plan_for_next(
        self,
        current_track: dict,
        next_track: dict,
        next_audio_post_stretch: np.ndarray,
    ) -> LiveTransitionPlan | None:
        """Compute the phase-lock plan for the upcoming transition.

        Returns ``None`` if either side is missing enough metadata for
        the plan to be meaningful (e.g. a track came in with no
        ``duration_sec`` at all). The caller treats ``None`` as
        equivalent to the legacy fallback path.

        Note on the catalog vs. post-stretch duration: the outgoing
        beatgrid lives in catalog time (un-stretched), while the body
        of the current track is playing at native_bpm and so the
        outgoing-anchor catalog sample == outgoing-anchor playback
        sample within ``_audio``. The incoming side has been stretched
        already, so we feed the POST-stretch buffer (and the
        recalibrated duration) to ``build_live_transition_plan`` and
        use the catalog beatgrid's downbeats AS IF they apply to the
        stretched signal — true to ±1 sample given how pyrubberband
        preserves relative positions across the stretch.
        """
        outgoing_beatgrid = current_track.get("beatgrid")
        incoming_beatgrid = next_track.get("beatgrid")
        outgoing_duration = float(
            current_track.get("duration_sec")
            or (len(self._audio) / _SAMPLE_RATE if self._audio is not None else 0.0)
        )
        incoming_duration = float(len(next_audio_post_stretch)) / _SAMPLE_RATE
        if outgoing_duration <= 0 or incoming_duration <= 0:
            return None

        # ``incoming_audio_y`` is mono'd for the RMS heuristic — the
        # full stereo buffer would just double the compute for no gain.
        if next_audio_post_stretch.ndim == 2:
            incoming_y = next_audio_post_stretch.mean(axis=1)
        else:
            incoming_y = next_audio_post_stretch

        return build_live_transition_plan(
            outgoing_beatgrid=outgoing_beatgrid,
            outgoing_duration_sec=outgoing_duration,
            incoming_beatgrid=incoming_beatgrid,
            incoming_duration_sec=incoming_duration,
            incoming_audio_y=incoming_y,
            sample_rate=_SAMPLE_RATE,
            target_xfade_sec=float(self.crossfade_sec),
            outgoing_bpm=float(current_track.get("bpm") or 0) or None,
            incoming_bpm=float(next_track.get("bpm") or 0) or None,
            bpm_match_threshold=_BPM_THRESHOLD,
        )

    # ------------------------------------------------------------------
    # Audio helpers
    # ------------------------------------------------------------------

    def _load_audio(self, track: dict) -> np.ndarray:
        """Load a track WAV as float32 stereo at _SAMPLE_RATE."""
        rel = track.get("file", "")
        path = (_PROJECT_DIR / rel) if rel and not Path(rel).is_absolute() else Path(rel)
        audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
        # Ensure stereo
        if audio.shape[1] == 1:
            audio = np.hstack([audio, audio])
        audio = audio[:, :2]
        # Resample if needed
        if sr != _SAMPLE_RATE and _HAS_LIBROSA:
            audio = _librosa.resample(audio.T, orig_sr=sr, target_sr=_SAMPLE_RATE).T
        return audio.astype(np.float32)

    def _time_stretch(
        self, audio: np.ndarray, track: dict, target_track: dict
    ) -> np.ndarray:
        """Stretch `audio` so its BPM matches the current track's BPM."""
        if not _HAS_PYRUBBERBAND:
            return audio
        from_bpm = float(track.get("bpm") or 0)
        to_bpm = float(target_track.get("bpm") or 0)
        if from_bpm <= 0 or to_bpm <= 0:
            return audio
        if abs(from_bpm - to_bpm) <= _BPM_THRESHOLD:
            return audio
        ratio = to_bpm / from_bpm
        ratio = max(_STRETCH_MIN, min(_STRETCH_MAX, ratio))
        stretched = _pyrubberband.time_stretch(audio, _SAMPLE_RATE, ratio)
        return stretched.astype(np.float32)

    def _cf_point_samples(self, track: dict) -> int:
        """Return sample index where crossfade should begin.

        Priority ladder:
          1. v3.0 phase-lock plan (``self._transition_plan``) — produced
             by the prestretch worker from the v2 beatgrid; honours
             16/8/4-bar phrase boundaries. This is the unified path that
             matches the offline render's ``build_mix`` behaviour.
          2. OUT hot cue from the catalog (legacy v2.x).
          3. ``duration_sec - crossfade_sec - 5`` (legacy v1.x).

        ``_extend_samples`` is added at every level so the agent's
        ``extend_track`` tool keeps shifting the cut point regardless of
        which path produced the base anchor.
        """
        plan = self._transition_plan
        if plan is not None and plan.phrase_tier != "fallback":
            return plan.outgoing_anchor_sample + self._extend_samples
        cues = track.get("hot_cues", [])
        out_cues = [c for c in cues if c.get("type") == "out"]
        if out_cues:
            sec = float(out_cues[0]["position_sec"])
        else:
            duration = float(track.get("duration_sec") or (len(self._audio) / _SAMPLE_RATE))
            sec = max(0.0, duration - self.crossfade_sec - 5)
        return int(sec * _SAMPLE_RATE) + self._extend_samples

    @staticmethod
    def _in_point_of(track: dict) -> int:
        """Return sample offset for the IN hot cue, or 0."""
        cues = track.get("hot_cues", [])
        in_cues = [c for c in cues if c.get("type") == "in"]
        return int(in_cues[0]["position_sec"] * _SAMPLE_RATE) if in_cues else 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit(self, type_: str, **kwargs) -> None:
        self.event_queue.put({"type": type_, **kwargs})


# ---------------------------------------------------------------------------
# LiveEngineBrowser — v2.5.1 web-mode implementation
# ---------------------------------------------------------------------------

class LiveEngineBrowser:
    """LiveEngine implementation where audio plays in the browser.

    The browser drives playback (HTML5 ``<audio>`` + Web Audio API). This
    class maintains:

    - The playlist queue + position state machine.
    - The watchdog event emitter (same 6 events as ``LiveEngineLocal``).
    - State (``playing`` / ``crossfading`` / ``idle`` / ``ended``).

    What it does NOT do:

    - Read or write audio buffers (no ``_audio_callback``, no sounddevice).
    - Pre-stretch with pyrubberband (v2.5.1 ships without time-stretch on
      the browser path; ``LiveEngineLocal`` keeps stretch for terminal mode).

    Time-of-playback comes from the browser via the WS message::

        {"type": "playback_pos", "track_id": <id>, "currentTime": <seconds>}

    sent ~every 250 ms. The watchdog uses the latest reported time instead
    of reading a sounddevice frame counter, so no background thread is
    needed.

    The ``emitter`` is a callable injected at construction. The WS handler
    in ``app.py`` constructs ``LiveEngineBrowser(emitter=ws_send)`` so events
    go straight to the client.

    Parameters
    ----------
    emitter:
        Sync callable invoked with each event dict. The WS handler wraps an
        async send so the engine stays threading/asyncio-agnostic.
    crossfade_sec:
        Crossfade blend duration in seconds (default 12).
    approach_warn_sec:
        How many seconds before the crossfade point to fire APPROACHING_CF
        (default 30).
    """

    def __init__(
        self,
        emitter: Callable[[dict], None] | None = None,
        crossfade_sec: int = 12,
        approach_warn_sec: int = 30,
    ) -> None:
        # Default emitter is a no-op so the engine is still construct-able
        # for unit tests that don't care about events.
        self._emitter: Callable[[dict], None] = emitter or (lambda _ev: None)
        self.crossfade_sec = crossfade_sec
        self.approach_warn_sec = approach_warn_sec

        self._lock = threading.Lock()
        self._state: str = "idle"  # idle | playing | crossfading | ended
        self.playlist: list[dict] = []
        self._idx: int = 0
        # Last reported currentTime per track id (browser pings it every
        # ~250 ms).
        self._reported_pos_sec: float = 0.0
        # Bookkeeping for watchdog edges (per current track index).
        self._approached: bool = False
        self._cf_triggered: bool = False
        self._extend_sec: float = 0.0  # accumulated extend offset in seconds

        # v2.6.0 — endless / improvisation mode state. The web flow
        # flips ``_endless_mode`` via the WS ``set_endless_mode``
        # command; everything else is engine-managed.
        self._endless_mode: bool = False
        self._low_water_fired: bool = False
        self._low_water_at: float | None = None
        self._endless_appended: int = 0
        # v3.6 — one-shot latch for the in-flight fallback extension
        # (``_try_endless_extend_inflight``). Scoped per current track;
        # re-armed on every track advance.
        self._extend_attempted: bool = False

        # v3.0 — phase-lock plan for the UPCOMING transition. Rebuilt
        # every time the current track changes (in ``play``,
        # ``_emit_next_track``, ``_begin_crossfade``, ``skip_track``).
        # The browser doesn't run audio buffer math itself; instead the
        # plan's fields are forwarded in ``engine_command`` payloads so
        # the frontend can schedule sample-accurate WebAudio crossfades
        # against the same anchors the offline + terminal-live paths use.
        self._transition_plan: LiveTransitionPlan | None = None

        # v3.0.1 — debounce for ``critic_warning`` so the engine fires
        # AT MOST once per (current_idx, next_idx) transition pair.
        # Without this, every position update (~4 Hz) would re-emit
        # whenever the plan kept landing on "fallback" — visually
        # equivalent to a stuck siren in the UI banner.
        self._critic_warned_for_transition: tuple[int, int] | None = None

    # ------------------------------------------------------------------
    # Public API (matches LiveEngineProtocol)
    # ------------------------------------------------------------------

    def play(self, playlist: list[dict] | None = None) -> None:
        """Start the browser-driven playback session.

        Replaces any existing playlist with the new one. Emits
        ``track_started`` for the first track and a ``cmd_load`` command so
        the browser knows which track to load and play. If the playlist is
        empty, emits ``session_ended`` and returns.
        """
        if playlist is not None:
            self.playlist = list(playlist)
        if not self.playlist:
            self._emit(SESSION_ENDED)
            return

        with self._lock:
            self._state = "playing"
            self._idx = 0
            self._reported_pos_sec = 0.0
            self._approached = False
            self._cf_triggered = False
            self._extend_sec = 0.0
            # v3.6 — a new playlist is a new set: reset the endless
            # bookkeeping. Without this, a re-``play()`` after a WS
            # reconnect inherits a minutes-old ``_low_water_at`` (the
            # 2026-07-10 stream logged grace-elapsed values of 200-400 s)
            # and a stale append counter. ``_endless_mode`` itself is
            # intentionally kept — the WS handler / phase_live own it.
            self._low_water_fired = False
            self._low_water_at = None
            self._endless_appended = 0
            self._extend_attempted = False

        first = self.playlist[0]
        # v3.0 — build the phase-lock plan for the first → second
        # transition BEFORE we read cf_point_sec, otherwise the first
        # TRACK_STARTED event would carry the legacy fallback cut point.
        self._rebuild_transition_plan()
        # Tell the browser to load + play the first track.
        self._emit_command("load", track=first, position=0)
        # v2.5.2 — include ``cf_point_sec`` so the frontend can drive a
        # live-ticking countdown from the deck's ``currentTime`` instead of
        # relying on the single ``approaching_crossfade`` emit (which was
        # the v2.5.1 source of the "Crossfade in: 0s stuck" bug).
        self._emit(
            TRACK_STARTED,
            track=first,
            cf_point_sec=round(self._cf_point_seconds(first), 2),
            phase_lock=self._phase_lock_payload(),
        )

    def report_playback_pos(self, track_id: str, current_time: float) -> None:
        """Update playback position from a browser ping.

        Called by the WS handler whenever the browser sends a ``playback_pos``
        message. Triggers ``approaching_crossfade``, ``crossfade_triggered``,
        and ``track_ended`` / ``session_ended`` events as the position
        crosses each threshold.

        v2.5.0.1 endgame safeguard
        --------------------------
        The browser stops emitting ``playback_pos`` updates once natural
        playback ends (the ``<audio>`` element fires ``ended`` and pauses,
        which freezes ``currentTime``). If the watchdog never crosses the
        crossfade threshold we'd be stuck on the last reported position
        forever — the user observes "track 1 plays out, then silence". To
        defend against that we synthesise a ``track_ended`` advance whenever
        the reported position lands within the last 2 s of the track AND no
        crossfade has fired yet. The dedicated browser ``ended`` listener
        sends ``{type: track_ended}`` over WS for the same situation; the
        two paths are independent so either one alone suffices.
        """
        with self._lock:
            if self._state == "idle" or self._idx >= len(self.playlist):
                return
            current_track = self.playlist[self._idx]
            # Guard against stale pings from a previous track (e.g. arriving
            # right after skip_track has flipped self._idx).
            if track_id and current_track.get("id") and track_id != current_track.get("id"):
                return
            self._reported_pos_sec = float(current_time)
            cf_sec = self._cf_point_seconds(current_track)
            secs_to_cf = cf_sec - self._reported_pos_sec
            approached = self._approached
            cf_triggered = self._cf_triggered
            idx = self._idx
            duration = float(current_track.get("duration_sec") or 0)
            next_track = (
                self.playlist[idx + 1] if idx + 1 < len(self.playlist) else None
            )

        # Emit edges outside the lock so the consumer can call back into
        # other methods without deadlocking.
        if not approached and secs_to_cf <= self.approach_warn_sec and next_track:
            with self._lock:
                self._approached = True
            self._emit(
                APPROACHING_CF,
                track=current_track,
                next_track=next_track,
                seconds_remaining=round(max(0.0, secs_to_cf), 1),
                # v2.5.2 — authoritative crossfade target time so the
                # frontend can derive a live-ticking countdown from the
                # deck's ``currentTime`` (rather than freezing on the
                # single emit).
                cf_point_sec=round(cf_sec, 2),
                # v3.0 — phase-lock anchors. Empty dict when no v2
                # beatgrid is available, in which case the frontend
                # keeps its legacy linear-fade scheduling.
                phase_lock=self._phase_lock_payload(),
            )

        # v3.6 — endless-mode "running low" poke. Decoupled from the
        # APPROACHING_CF edge above, which requires a ``next_track``:
        # nested inside it (the v2.6.0 placement) the poke could never
        # fire while the LAST track played, so a tail track appended by
        # a previous extension never re-poked the LLM and every endless
        # set died one track after the original playlist ran out
        # (observed live 2026-07-10). Fires once per low-water window;
        # ``append_track`` re-arms it.
        if secs_to_cf <= self.approach_warn_sec:
            with self._lock:
                remaining = len(self.playlist) - self._idx - 1
                fire_low = (
                    self._endless_mode
                    and remaining <= 1
                    and not self._low_water_fired
                )
                if fire_low:
                    self._low_water_fired = True
                    self._low_water_at = time.monotonic()
            if fire_low:
                self._emit(
                    PLAYLIST_RUNNING_LOW,
                    track=current_track,
                    seconds_remaining=round(max(0.0, secs_to_cf), 1),
                )

        if not cf_triggered and self._reported_pos_sec >= cf_sec:
            if next_track is not None:
                self._begin_crossfade(current_track, next_track)
            elif duration > 0 and self._reported_pos_sec >= duration:
                # Last track played to its end — emit final events.
                self._emit(TRACK_ENDED, track=current_track)
                if self._maybe_end_or_extend(current_track, track_over=True):
                    with self._lock:
                        self._state = "idle"
                else:
                    # Endless mode appended a successor — advance to it
                    # and emit TRACK_STARTED via the existing helper.
                    with self._lock:
                        has_successor = self._idx + 1 < len(self.playlist)
                        new_idx = self._idx + 1 if has_successor else self._idx
                    if has_successor:
                        self._emit_next_track(self.playlist[new_idx])
            else:
                # v3.6 — past the crossfade point on the LAST track with
                # nothing queued. Extend NOW, while the deck still plays:
                # once the browser's <audio> dies the ping stream freezes
                # (``_cf_triggered`` gates every later path), so no code
                # would ever get another chance to run the fallback. An
                # append here means the next ping takes the
                # ``_begin_crossfade`` branch above — a seamless blend
                # instead of end-of-track silence.
                self._try_endless_extend_inflight(current_track)
            return

        # Endgame safeguard: if we're inside the last 2 s of the track and
        # no crossfade has been triggered yet, force a ``track_ended``-style
        # advance. This is a belt-and-braces complement to the explicit
        # browser ``ended`` event — it catches the case where the
        # ``playback_pos`` ping wins the race and arrives just before the
        # browser gets a chance to emit its own ``track_ended`` message.
        if (
            not cf_triggered
            and duration > 0
            and self._reported_pos_sec >= max(0.0, duration - 2.0)
        ):
            self.report_track_ended(track_id or current_track.get("id", ""))

    def report_track_ended(self, track_id: str) -> None:
        """Advance the engine when the browser reports a natural ``ended``.

        v2.5.0.1 — the browser's ``<audio>`` element fires ``ended`` when
        natural playback finishes; the frontend forwards that as a
        ``{type: track_ended}`` WS message. The WS handler invokes this
        method, which advances the cursor to the next track (if any) or
        ends the session.

        Idempotent: stale pings for a track that's no longer current
        (e.g. arriving right after a manual ``skip_track``) are ignored,
        same as ``report_playback_pos``.
        """
        with self._lock:
            if self._state == "idle" or self._idx >= len(self.playlist):
                return
            current_track = self.playlist[self._idx]
            # Stale-ping guard. If track_id is empty we accept the message
            # — the browser fallback path may not know the id.
            if (
                track_id
                and current_track.get("id")
                and track_id != current_track.get("id")
            ):
                return
            idx = self._idx
            next_idx = idx + 1
            has_next = next_idx < len(self.playlist)
            next_track = self.playlist[next_idx] if has_next else None
            # Mark the current track as already-handled so a late
            # ``playback_pos`` ping doesn't re-fire the safeguard.
            self._cf_triggered = True

        self._emit(TRACK_ENDED, track=current_track)
        if has_next and next_track is not None:
            self._emit_next_track(next_track)
        else:
            if self._maybe_end_or_extend(current_track, track_over=True):
                with self._lock:
                    self._state = "idle"
                return
            # Endless mode appended a successor between TRACK_ENDED and
            # the SESSION_ENDED gate — advance to it.
            with self._lock:
                if self._idx + 1 < len(self.playlist):
                    new_track = self.playlist[self._idx + 1]
                else:
                    new_track = None
            if new_track is not None:
                self._emit_next_track(new_track)

    def _emit_next_track(self, next_track: dict) -> None:
        """Advance the cursor and tell the browser to load the next track.

        Used by ``report_track_ended`` (and the endgame safeguard) when we
        need to advance without going through a full crossfade ramp. We
        emit a ``stop_deck`` command first to tell the browser to release
        the active deck (so the new track plays cleanly into the same
        deck), then a ``load`` command for the new track plus the
        ``track_started`` engine event.
        """
        with self._lock:
            self._idx += 1
            self._approached = False
            self._cf_triggered = False
            self._extend_sec = 0.0
            self._reported_pos_sec = 0.0
            self._state = "playing"
            self._extend_attempted = False

        # v3.0 — rebuild the phase-lock plan for the new
        # (current → next-next) pair so the next ``approaching_crossfade``
        # event can carry the correct anchors.
        self._rebuild_transition_plan()
        # Stop the active deck so its audio doesn't bleed into the new
        # track (browser-side this releases the <audio> src).
        self._emit_command("stop_deck")
        # Tell the browser to load + play the new track in the active
        # deck — same payload shape ``play()`` uses for the first track.
        self._emit_command("load", track=next_track, position=0)
        self._emit(
            TRACK_STARTED,
            track=next_track,
            cf_point_sec=round(self._cf_point_seconds(next_track), 2),
            phase_lock=self._phase_lock_payload(),
        )

    def crossfade_now(self) -> str:
        """Trigger crossfade immediately, skipping the auto-timer."""
        with self._lock:
            if self._state != "playing":
                return f"Cannot crossfade: engine is '{self._state}'."
            if self._idx + 1 >= len(self.playlist):
                return "No next track to crossfade into."
            current_track = self.playlist[self._idx]
            next_track = self.playlist[self._idx + 1]
        self._begin_crossfade(current_track, next_track)
        return "Crossfade triggered."

    def extend_track(self, seconds: int) -> str:
        """Delay the upcoming auto-crossfade by ``seconds`` seconds."""
        with self._lock:
            self._extend_sec += float(seconds)
            # An extend always re-arms the approaching warning so the
            # listener gets a fresh countdown after the bump.
            self._approached = False
        return f"Crossfade delayed by {seconds}s."

    def skip_track(self) -> str:
        """Hard-cut to the next track without a crossfade ramp.

        Skip is intentionally a hard cut: it's a user-initiated immediate
        response (button press / agent command), and the audible delay of
        a crossfade ramp would defeat that purpose. For a *ramped* skip
        (fast crossfade), use :meth:`crossfade_now` instead — the agent
        and the UI both have access to that method.

        See PR #v2.5.2a for the design discussion behind keeping skip as
        a hard cut while making the natural-end-of-track path always run
        a full crossfade ramp.
        """
        with self._lock:
            next_idx = self._idx + 1
            if next_idx >= len(self.playlist):
                return "No next track."
            self._idx = next_idx
            self._approached = False
            self._cf_triggered = False
            self._extend_sec = 0.0
            self._reported_pos_sec = 0.0
            self._state = "playing"
            self._extend_attempted = False
            new_track = self.playlist[next_idx]
        # v3.0 — rebuild for the (skipped-to → next-after-that) pair.
        self._rebuild_transition_plan()
        # Tell the browser to switch decks immediately.
        self._emit_command("skip", track=new_track, position=0)
        self._emit(
            TRACK_STARTED,
            track=new_track,
            cf_point_sec=round(self._cf_point_seconds(new_track), 2),
            phase_lock=self._phase_lock_payload(),
        )
        return f"Skipped to '{new_track.get('display_name', '?')}'."

    def queue_swap(self, position: int, track_id: str) -> str:
        """Replace a future playlist position with a catalog track."""
        idx = position - 1
        with self._lock:
            if idx <= self._idx or idx >= len(self.playlist):
                return f"Position {position} is not a future slot."
        catalog = _load_catalog()
        track = next((t for t in catalog if t.get("id") == track_id), None)
        if not track:
            return f"Track ID '{track_id}' not found in catalog."
        with self._lock:
            self.playlist[idx] = track
        self._emit_command("queue_swap", position=position, track=track)
        return f"Queued '{track.get('display_name', '?')}' at position {position}."

    def queue_swap_with_track(self, position: int, new_track: dict) -> str:
        """Replace a future slot with an explicit track dict (web variant).

        The web flow can resolve the catalog lookup at the WS layer (where it
        has access to the FastAPI cache + per-user filtering) and pass the
        resolved track dict in directly. This avoids round-tripping through
        ``_load_catalog`` on the engine side, which has no awareness of the
        web-mode catalog substitutes used by mock_pipeline. Falls back to the
        same validation used by ``queue_swap``.
        """
        idx = position - 1
        with self._lock:
            if idx <= self._idx or idx >= len(self.playlist):
                return f"Position {position} is not a future slot."
            self.playlist[idx] = new_track
        self._emit_command("queue_swap", position=position, track=new_track)
        return f"Queued '{new_track.get('display_name', '?')}' at position {position}."

    def append_track(self, track: dict) -> str:
        """Append a track to the live playlist (v2.6.0 endless mode).

        Thread-safe append, mirrors ``LiveEngineLocal.append_track``.
        For the browser engine there's no pre-stretch — the frontend
        audio engine handles encoding seamlessly — so the path is
        simpler: append, reset the low-water guard, and let the next
        ``report_playback_pos`` ping pick up the new tail naturally.
        """
        if not track or not track.get("id"):
            return "append_track: track must include an 'id' field."
        with self._lock:
            if self._endless_appended >= ENDLESS_APPEND_CAP:
                msg = (
                    f"Append cap reached ({ENDLESS_APPEND_CAP}); "
                    "ending session after current track."
                )
                cap_reached = True
            else:
                cap_reached = False
                self.playlist.append(dict(track))
                self._low_water_fired = False
                self._low_water_at = None
                self._endless_appended += 1
            position = len(self.playlist)
        if cap_reached:
            self._emit(ENDLESS_WARNING, reason="cap_reached", message=msg)
            return msg
        return (
            f"Appended '{track.get('display_name', track['id'])}' "
            f"at position {position}."
        )

    def _maybe_end_or_extend(
        self, current_track: dict | None, *, track_over: bool = False
    ) -> bool:
        """Browser-engine variant of the endless-mode SESSION_ENDED gate.

        Same semantics as ``LiveEngineLocal._maybe_end_or_extend`` but
        reads the catalog fresh at fallback time — the browser engine
        runs on the WS loop thread where I/O is fine. Returns True when
        the caller should stop (let SESSION_ENDED fire), False when it
        should keep looping (a successor is now present).

        ``track_over=True`` (v3.6) means the current track has ALREADY
        finished playing. Unlike the local engine, this engine has no
        watchdog thread — its "ticks" are browser pings, and those
        freeze once the deck's natural ``ended`` fires. Deferring on the
        grace window here would therefore wait for a re-poll that can
        never arrive: the engine hangs in silence until the user
        refreshes and the WS teardown kills the session (the 2026-07-10
        live failure). With ``track_over`` the grace is skipped and the
        deterministic fallback runs immediately.
        """
        with self._lock:
            endless = self._endless_mode
            idx = self._idx
            remaining_after = len(self.playlist) - idx - 1
            low_water_at = self._low_water_at

        # Diagnostic — surfaces in backend.log so we can see WHICH branch
        # the engine takes when a session reaches the last track. Removed
        # once endless-mode end-of-set is verified across genre + catalog
        # combinations.
        cur_id = (current_track or {}).get("id") or "?"
        cur_name = ((current_track or {}).get("display_name") or "?")[:40]
        print(
            f"[engine _maybe_end_or_extend] track={cur_id!r} ({cur_name!r}) "
            f"endless={endless} remaining_after={remaining_after} "
            f"low_water_at={'set' if low_water_at else 'None'}",
            flush=True,
        )

        if not endless:
            print(
                f"[engine _maybe_end_or_extend] DECISION: emit SESSION_ENDED (endless OFF)",
                flush=True,
            )
            self._emit(SESSION_ENDED)
            return True
        if remaining_after > 0:
            print(
                f"[engine _maybe_end_or_extend] DECISION: keep looping (agent appended)",
                flush=True,
            )
            return False
        if not track_over:
            if low_water_at is None:
                with self._lock:
                    self._low_water_at = time.monotonic()
                print(
                    f"[engine _maybe_end_or_extend] DECISION: start grace timer "
                    f"(PLAYLIST_RUNNING_LOW never fired — first end-of-set ping)",
                    flush=True,
                )
                return False
            elapsed = time.monotonic() - low_water_at
            if elapsed < ENDLESS_GRACE_SEC:
                print(
                    f"[engine _maybe_end_or_extend] DECISION: wait grace "
                    f"({elapsed:.1f}s of {ENDLESS_GRACE_SEC}s)",
                    flush=True,
                )
                return False

        # Track already over (track_over) or grace elapsed without an
        # append → deterministic fallback.
        catalog = _load_catalog()
        with self._lock:
            exclude = {t.get("id") for t in self.playlist if t.get("id")}
        genre = (
            (current_track or {}).get("genre_folder")
            or (current_track or {}).get("genre")
        )
        print(
            f"[engine _maybe_end_or_extend] "
            f"{'track over' if track_over else 'grace elapsed'} — "
            f"running fallback: genre={genre!r} catalog_size={len(catalog)} "
            f"exclude_size={len(exclude)}",
            flush=True,
        )
        pick = _autoplay_pick(current_track, catalog, genre, exclude, allow_repeats=True)
        if pick is None:
            print(
                f"[engine _maybe_end_or_extend] DECISION: _autoplay_pick returned None — "
                f"emit ENDLESS_WARNING + SESSION_ENDED",
                flush=True,
            )
            self._emit(
                ENDLESS_WARNING,
                reason="no_candidates",
                message=(
                    f"No more {genre or 'matching'} tracks left to extend "
                    "with — set ending."
                ),
            )
            self._emit(SESSION_ENDED)
            return True
        print(
            f"[engine _maybe_end_or_extend] DECISION: append fallback track "
            f"{pick.get('id')!r} ({(pick.get('display_name') or '')[:40]!r})",
            flush=True,
        )
        self.append_track(pick)
        return False

    def _try_endless_extend_inflight(self, current_track: dict | None) -> bool:
        """Run the deterministic fallback BEFORE the deck dies (v3.6).

        Called from ``report_playback_pos`` when the LAST track crosses
        its crossfade point with nothing queued. Appending here — while
        audio is still playing — lets the next ping take the normal
        ``_begin_crossfade`` branch, blending into the successor
        seamlessly. Waiting for TRACK_ENDED instead was the v2.6.0
        deadlock: after natural ``ended`` the ping stream freezes, so a
        grace window that defers "until the next poll" never got one.

        Grace semantics: the LLM keeps priority. The low-water poke set
        ``_low_water_at`` back at the approach edge (~30 s earlier), so
        by the crossfade point ``ENDLESS_GRACE_SEC`` has normally long
        elapsed. If the poke never fired (very short tail track), the
        clock starts now and the still-alive ping stream re-polls.
        One-shot per track via ``_extend_attempted`` so a fruitless
        catalog scan doesn't repeat at ping rate (~4 Hz). Returns True
        when a track was appended.
        """
        with self._lock:
            if not self._endless_mode or self._extend_attempted:
                return False
            if len(self.playlist) - self._idx - 1 > 0:
                return False
            low_water_at = self._low_water_at
        if low_water_at is None:
            with self._lock:
                self._low_water_at = time.monotonic()
            return False
        if (time.monotonic() - low_water_at) < ENDLESS_GRACE_SEC:
            return False
        with self._lock:
            self._extend_attempted = True
            exclude = {t.get("id") for t in self.playlist if t.get("id")}
        catalog = _load_catalog()
        genre = (
            (current_track or {}).get("genre_folder")
            or (current_track or {}).get("genre")
        )
        pick = _autoplay_pick(current_track, catalog, genre, exclude, allow_repeats=True)
        print(
            f"[engine _try_endless_extend_inflight] genre={genre!r} "
            f"catalog_size={len(catalog)} exclude_size={len(exclude)} "
            f"pick={(pick or {}).get('id')!r}",
            flush=True,
        )
        if pick is None:
            # No candidates — let the end-of-track path emit the
            # ENDLESS_WARNING + SESSION_ENDED pair when the deck drains.
            return False
        self.append_track(pick)
        return True

    def set_crossfade_point(self, position_sec: float) -> str:
        """Manually set where the crossfade begins in the current track."""
        with self._lock:
            if self._idx >= len(self.playlist):
                return "No track playing."
            current_track = self.playlist[self._idx]
            current_cf = self._cf_point_seconds(current_track)
            self._extend_sec += float(position_sec) - current_cf
            self._approached = False
        return f"Crossfade point set to {position_sec:.1f}s."

    def get_state(self) -> dict:
        """Return a snapshot of engine state for the agent."""
        with self._lock:
            idx = self._idx
            state = self._state
            pos = self._reported_pos_sec
            track = self.playlist[idx] if idx < len(self.playlist) else None
            next_track = (
                self.playlist[idx + 1] if idx + 1 < len(self.playlist) else None
            )
            cf_sec = self._cf_point_seconds(track) if track else 0.0

        secs_to_cf = max(0.0, cf_sec - pos) if track else 0.0

        return {
            "state": state,
            "position_sec": round(pos, 1),
            "current_track": _track_summary(track),
            "next_track": _track_summary(next_track),
            "seconds_to_crossfade": round(secs_to_cf, 1),
            "playlist_remaining": max(0, len(self.playlist) - idx - 1),
        }

    def stop(self) -> None:
        """Stop the session and tell the browser to release audio resources."""
        with self._lock:
            already_idle = self._state == "idle"
            self._state = "idle"
        # Always send the stop command so the browser can clean up the
        # ``<audio>`` elements even if we were idle (e.g. after the playlist
        # ran out and the engine self-transitioned to idle).
        self._emit_command("stop")
        if not already_idle:
            self._emit(SESSION_ENDED)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _begin_crossfade(self, from_track: dict, to_track: dict) -> None:
        """Transition from ``from_track`` to ``to_track``.

        v2.5.1 fires ``crossfade_triggered`` followed immediately by
        ``crossfade_finished`` + ``track_ended`` (browser-side the dual-deck
        crossfade ramp is what produces the audible blend over
        ``crossfade_sec`` seconds — the engine doesn't need to model the
        ramp itself because no audio buffer math happens here).

        v2.5.2 — advance ``_idx`` and re-arm the per-track watchdog flags so
        the new current track's ``approaching_crossfade`` /
        ``crossfade_triggered`` thresholds fire afresh. The state machine
        leaves ``crossfading`` immediately because the engine doesn't model
        the ramp itself; the audible ramp is fully owned by the browser.
        """
        # v3.0 — capture the OUTGOING-side phase-lock payload BEFORE we
        # advance the cursor + rebuild. The frontend uses this on the
        # ``crossfade`` engine_command to (a) start the incoming deck at
        # the right downbeat (skipping any pickup) and (b) replace its
        # linear GainNode ramp with equal-power cos/sin curves.
        outgoing_phase_lock = self._phase_lock_payload()

        with self._lock:
            self._idx += 1
            # Re-arm watchdog edges for the new current track. The previous
            # ``_cf_triggered`` flag was scoped to ``from_track`` — a new
            # crossfade for ``to_track`` must be allowed when we cross its
            # threshold later.
            self._approached = False
            self._cf_triggered = False
            self._extend_sec = 0.0
            self._reported_pos_sec = 0.0
            self._state = "playing"
            self._extend_attempted = False
        # Rebuild for the (to_track → after_to_track) pair so the next
        # transition's anchors are ready by the time the new current
        # track's ``approaching_crossfade`` fires.
        self._rebuild_transition_plan()
        self._emit_command(
            "crossfade",
            from_track=from_track,
            to_track=to_track,
            crossfade_sec=self.crossfade_sec,
            phase_lock=outgoing_phase_lock,
        )
        self._emit(CROSSFADE_TRIGGERED, from_track=from_track, to_track=to_track)
        self._emit(CROSSFADE_FINISHED, from_track=from_track, to_track=to_track)
        self._emit(TRACK_ENDED, track=from_track)
        self._emit(
            TRACK_STARTED,
            track=to_track,
            cf_point_sec=round(self._cf_point_seconds(to_track), 2),
            phase_lock=self._phase_lock_payload(),
        )

    def _cf_point_seconds(self, track: dict | None) -> float:
        """Return the catalog-time seconds at which the crossfade should fire.

        Priority ladder mirrors ``LiveEngineLocal._cf_point_samples``:
          1. v3.0 phase-lock plan (when ``self._transition_plan`` is set
             and lands on a real phrase boundary).
          2. OUT hot cue.
          3. ``duration_sec - crossfade_sec - 5`` legacy formula.

        ``_extend_sec`` is added at every level so the agent's
        ``extend_track`` works for catalogs that have already migrated
        to v2 beatgrids.
        """
        if not track:
            return 0.0
        plan = self._transition_plan
        if (
            plan is not None
            and plan.phrase_tier != "fallback"
            and track.get("id") is not None
            and track is self._current_track_for_plan()
        ):
            return plan.plan.outgoing_anchor_catalog_sec + self._extend_sec
        cues = track.get("hot_cues") or []
        out_cues = [c for c in cues if c.get("type") == "out"]
        if out_cues:
            sec = float(out_cues[0].get("position_sec", 0.0))
        else:
            duration = float(track.get("duration_sec") or 0.0)
            sec = max(0.0, duration - self.crossfade_sec - 5)
        return sec + self._extend_sec

    def _current_track_for_plan(self) -> dict | None:
        """Return the track the cached ``_transition_plan`` was built for.

        The plan caches anchors for the OUTGOING side of the upcoming
        transition (i.e. for the currently-playing track). When
        ``_cf_point_seconds`` is called for any other track (e.g. a
        speculative pre-flight call), we must skip the plan and use the
        legacy fallback ladder instead of reading stale anchor data.

        Reads ``self._idx`` + ``self.playlist`` without acquiring
        ``self._lock`` because ``_cf_point_seconds`` is sometimes called
        from inside a ``with self._lock`` block (notably the head of
        ``report_playback_pos``). A reentrant grab would deadlock on
        this non-reentrant Lock. A torn read is harmless here — the
        worst case is a one-tick-stale ``_idx``, and the caller only
        uses the return value for an identity comparison against
        ``track``, not as authoritative state.
        """
        idx = self._idx
        if 0 <= idx < len(self.playlist):
            return self.playlist[idx]
        return None

    def _rebuild_transition_plan(self) -> None:
        """Recompute ``self._transition_plan`` for (current → next).

        Called whenever the current-track cursor changes. Browser-engine
        flavour: there is no audio buffer to feed the pickup-skip RMS
        heuristic, so the plan is derived from the catalog beatgrids
        only. The frontend has the audio bytes — if it wants to refine
        the incoming start (e.g. detect a tail of silence on the
        outgoing track) it can do so locally; the backend simply
        publishes the catalog-time anchors.
        """
        with self._lock:
            idx = self._idx
            if idx >= len(self.playlist):
                self._transition_plan = None
                return
            current_track = self.playlist[idx]
            next_track = (
                self.playlist[idx + 1] if idx + 1 < len(self.playlist) else None
            )
        if next_track is None:
            with self._lock:
                self._transition_plan = None
            return
        outgoing_duration = float(current_track.get("duration_sec") or 0.0)
        incoming_duration = float(next_track.get("duration_sec") or 0.0)
        if outgoing_duration <= 0 or incoming_duration <= 0:
            with self._lock:
                self._transition_plan = None
            return
        plan = build_live_transition_plan(
            outgoing_beatgrid=current_track.get("beatgrid"),
            outgoing_duration_sec=outgoing_duration,
            incoming_beatgrid=next_track.get("beatgrid"),
            incoming_duration_sec=incoming_duration,
            incoming_audio_y=None,  # browser holds the bytes; backend doesn't
            sample_rate=_SAMPLE_RATE,
            target_xfade_sec=float(self.crossfade_sec),
            outgoing_bpm=float(current_track.get("bpm") or 0) or None,
            incoming_bpm=float(next_track.get("bpm") or 0) or None,
            bpm_match_threshold=_BPM_THRESHOLD,
        )
        with self._lock:
            self._transition_plan = plan

        # v3.0.1 — emit a critic_warning when the planner couldn't land
        # on a phrase boundary. The frontend reads ``critic_warning``
        # events and surfaces them as a non-blocking banner so the DJ
        # knows the upcoming transition will use the linear-fade legacy
        # path (not phase-locked). Only fire ONCE per transition pair —
        # ``_rebuild_transition_plan`` runs on every position update.
        self._maybe_emit_critic_warning(plan, idx, current_track, next_track)

    def _maybe_emit_critic_warning(
        self,
        plan: LiveTransitionPlan,
        current_idx: int,
        current_track: dict,
        next_track: dict,
    ) -> None:
        """Emit ``critic_warning`` if the plan landed on the fallback tier.

        Debounced via ``self._critic_warned_for_transition`` so the
        event fires at most once per (current_idx, next_idx) pair —
        without that guard a stalled-at-fallback session would emit a
        warning on every position update (~4 Hz). The reason string is
        chosen to match the most likely fix in the UI ("regenerate
        beatgrid for X"), not just to describe the symptom.
        """
        if plan.phrase_tier != "fallback":
            return
        next_idx = current_idx + 1
        key = (current_idx, next_idx)
        if self._critic_warned_for_transition == key:
            return
        self._critic_warned_for_transition = key

        out_bg = current_track.get("beatgrid")
        in_bg = next_track.get("beatgrid")
        if not out_bg and not in_bg:
            reason = "no_beatgrid_either_side"
        elif not out_bg:
            reason = "no_beatgrid_outgoing"
        elif not in_bg:
            reason = "no_beatgrid_incoming"
        else:
            # Both grids exist but the phrase ladder still gave up —
            # usually means the planner couldn't fit the requested
            # xfade window inside the available bars (very short
            # incoming track, or outgoing's tail too close to the end).
            reason = "no_phrase_anchor_in_window"

        self._emit(
            CRITIC_WARNING,
            kind="phase_lock_fallback",
            reason=reason,
            outgoing_track={
                "id": current_track.get("id"),
                "display_name": current_track.get("display_name"),
            },
            incoming_track={
                "id": next_track.get("id"),
                "display_name": next_track.get("display_name"),
            },
            phrase_tier=plan.phrase_tier,
            # Human-readable fallback string the UI can show verbatim if
            # it doesn't want to map the reason enum locally.
            message=_CRITIC_WARNING_MESSAGES.get(reason, reason),
        )

    def _phase_lock_payload(self) -> dict:
        """Serialise the current ``_transition_plan`` for the WS layer.

        Returns an empty dict when no plan is active or the plan landed
        on the "fallback" tier — the frontend uses the empty payload as
        the signal to take its legacy linear-fade path. Keeping the
        empty case explicitly empty (rather than a structure-with-nulls)
        keeps the frontend branch concise: ``if (payload?.xfade_sec) {…}``.

        v3.1 — ``incoming_rate`` / ``outgoing_rate`` carry the tempo-match
        playback rate. The frontend applies ``incoming_rate`` as
        ``HTMLMediaElement.playbackRate`` (with ``preservesPitch=true``)
        on the incoming deck so its BPM matches the outgoing's during the
        crossfade, mirroring the pyrubberband pre-stretch the CLI engine
        runs. ``1.0`` means "no rate change" (BPMs already within
        threshold, or one of them was missing from the catalog).
        """
        plan = self._transition_plan
        if plan is None or plan.phrase_tier == "fallback":
            return {}
        payload = {
            "outgoing_anchor_sec": round(plan.plan.outgoing_anchor_catalog_sec, 4),
            "incoming_anchor_sec": round(plan.plan.incoming_anchor_catalog_sec, 4),
            "xfade_sec": round(plan.plan.xfade_catalog_sec, 4),
            "phrase_tier": plan.phrase_tier,
            "incoming_pickup_skipped": plan.incoming_pickup_skipped,
            "edge_guard_samples": XFADE_EDGE_GUARD_SAMPLES,
            "sample_rate": plan.sample_rate,
            "incoming_rate": round(plan.incoming_rate, 6),
            "outgoing_rate": round(plan.outgoing_rate, 6),
        }
        # v3.3 — name + automation params for the chosen crossfade move.
        # Always present (defaults to {"transition_style": "smooth_blend"}
        # so the frontend can branch on a guaranteed key instead of
        # `?.transition_style`). The bass_swap sub-block is included only
        # when the picker chose BASS_SWAP, keeping the contract narrow.
        payload.update(serialise_choice(plan.transition_style))

        # v3.5 — feed-forward beat-lock grid-warp. Only emitted when the
        # picker produced a real per-bar lock schedule (tight 4/4 grids);
        # loose-grid genres leave it absent and the frontend keeps using
        # the single static ``incoming_rate`` above. The frontend applies
        # these as AudioBufferSourceNode.playbackRate automation against
        # the same `when` clock as the source start, so every incoming
        # downbeat lands on an outgoing downbeat for the whole overlap.
        sched = plan.beat_rate_schedule
        if sched.mode == "grid_warp" and sched.segments:
            payload["beat_rate_schedule"] = [
                {"at_sec": seg.at_sec, "rate": seg.rate, "ramp": seg.ramp}
                for seg in sched.segments
            ]
        return payload

    def _emit(self, type_: str, **kwargs) -> None:
        try:
            self._emitter({"type": type_, **kwargs})
        except Exception:  # noqa: BLE001 — never let UI plumbing kill the engine
            pass

    def _emit_command(self, name: str, **kwargs) -> None:
        """Emit an ``engine_command`` event so the browser can react.

        Examples: ``load`` (start playing this track), ``crossfade``
        (begin the ramp), ``skip`` (hard cut), ``queue_swap`` (replace a
        future track in the UI), ``stop``.
        """
        try:
            self._emitter({"type": "engine_command", "command": name, **kwargs})
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Backwards-compat alias — keeps `from agent.live_engine import LiveEngine`
# working for v1.5 callers and the existing test suite. Renaming the class
# without this alias would break the public surface.
# ---------------------------------------------------------------------------

LiveEngine = LiveEngineLocal


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _load_catalog() -> list[dict]:
    catalog_path = _PROJECT_DIR / "tracks" / "tracks.json"
    if not catalog_path.exists():
        return []
    with open(catalog_path, encoding="utf-8") as f:
        return json.load(f).get("tracks", [])


# Camelot wheel — adjacency = ±1 number AND same letter (A or B); the
# "energy boost" relative move (same number, flip letter) costs 0.5 in
# our metric so it stays preferred over a true clash.
def _camelot_distance(a: str | None, b: str | None) -> float:
    """Cyclic distance between two Camelot keys (e.g. ``8A``, ``11B``).

    Returns ``0.0`` for identical keys, low values for adjacent moves on
    the wheel, and ``6.0+`` for the worst case. Missing or malformed
    keys score ``6.0`` so unknowns never accidentally rank as good
    candidates.
    """
    if not a or not b:
        return 6.0
    try:
        num_a, letter_a = int(a[:-1]), a[-1].upper()
        num_b, letter_b = int(b[:-1]), b[-1].upper()
    except (ValueError, IndexError):
        return 6.0
    if not (1 <= num_a <= 12 and 1 <= num_b <= 12):
        return 6.0
    if letter_a not in ("A", "B") or letter_b not in ("A", "B"):
        return 6.0
    diff = abs(num_a - num_b)
    cyclic = min(diff, 12 - diff)  # 0..6
    if letter_a != letter_b:
        cyclic += 0.5  # A↔B flip at the same number is the "energy boost"
    return float(cyclic)


def _autoplay_pick(
    current_track: dict | None,
    catalog: list[dict],
    genre: str | None,
    exclude_ids: set[str],
    *,
    allow_repeats: bool = False,
) -> dict | None:
    """Choose the best in-genre continuation track.

    Filters ``catalog`` by ``genre_folder`` (or ``genre`` as a fallback)
    matching ``genre`` case-insensitively, drops ids in ``exclude_ids``
    (typically the tracks already in the live playlist), and ranks the
    remaining candidates ascending by ``(|Δbpm|, camelot_distance)``
    against ``current_track``. Returns the top candidate or ``None`` if
    nothing matches.

    When ``allow_repeats=True`` and the exclude-filtered candidate set
    is empty, recycle from the full in-genre catalog excluding only the
    track currently playing — this is what makes a true 24/7 endless
    stream possible once a small catalog has been fully cycled.

    Pure / module-level so the engine watchdog can call it without
    touching ``self``, and so tests can exercise it without spinning up
    an engine instance.
    """
    if not catalog:
        return None
    target_genre = (genre or "").strip().lower()
    cur_bpm = float((current_track or {}).get("bpm") or 0.0)
    cur_key = (current_track or {}).get("camelot_key")
    cur_id = (current_track or {}).get("id")

    def in_genre(t: dict) -> bool:
        gf = (t.get("genre_folder") or t.get("genre") or "").strip().lower()
        return bool(gf) and (not target_genre or gf == target_genre)

    candidates = [
        t for t in catalog
        if t.get("id") and t["id"] not in exclude_ids and in_genre(t)
    ]
    if not candidates and allow_repeats:
        # Endless mode: catalog exhausted for this genre. Recycle any
        # in-genre track that isn't the one currently playing so the
        # stream stays alive — back-to-back repeats are still avoided.
        candidates = [
            t for t in catalog
            if t.get("id") and t["id"] != cur_id and in_genre(t)
        ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda t: (
            abs(float(t.get("bpm") or 0.0) - cur_bpm),
            _camelot_distance(t.get("camelot_key"), cur_key),
        )
    )
    return candidates[0]


def _track_summary(track: dict | None) -> dict | None:
    """Pack the subset of a catalog entry that crosses the WS to the frontend.

    Only the fields the UI actually reads — full beatgrids contain a
    100+ float downbeats array per track and would inflate every
    track_started / live_state message. The frontend's VisualLayer only
    needs ``beatgrid.bpm`` + ``first_beat_sec`` for its sample-accurate
    beat clock; phase-lock anchors travel separately in the
    ``phase_lock`` payload, so the heavy downbeats array stays
    backend-side. Without this slim ``beatgrid`` block the UI's
    "Degraded sync — this track has no beatgrid" banner fires on EVERY
    track even when the catalog has full madmom data, because the
    TypeScript ``LiveTrackSummary.beatgrid`` contract was declared but
    never populated by this function.
    """
    if not track:
        return None
    bg_full = track.get("beatgrid") or {}
    bg_slim: dict | None
    if bg_full.get("bpm") is not None and bg_full.get("first_beat_sec") is not None:
        bg_slim = {
            "bpm": bg_full["bpm"],
            "first_beat_sec": bg_full["first_beat_sec"],
        }
    else:
        bg_slim = None
    return {
        "display_name": track.get("display_name", "?"),
        "bpm": track.get("bpm", 0),
        "camelot_key": track.get("camelot_key", "?"),
        "hot_cues": track.get("hot_cues", []),
        "beatgrid": bg_slim,
    }
