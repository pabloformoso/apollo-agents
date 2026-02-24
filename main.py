import os
import sys

import librosa
import numpy as np
from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    TextClip,
    VideoClip,
    vfx,
)
from pydub import AudioSegment
from scipy.ndimage import gaussian_filter1d

# === Configuration ===
TRACKS_DIR = "./tracks"
OUTPUT_DIR = "./output"
AUDIO_PATH = os.path.join(OUTPUT_DIR, "mix_output.mp3")
VIDEO_PATH = os.path.join(OUTPUT_DIR, "mix_video.mp4")

CROSSFADE_SEC = 12          # Crossfade overlap duration
TEMPO_RAMP_SEC = 16         # Gradual BPM adjustment after crossfade
BPM_MATCH_THRESHOLD = 5     # BPM diff above which we meet in the middle
RAMP_STEPS = 24             # Granularity of tempo ramp (more = smoother)
FADE_OUT_SEC = 5            # Fade-out at the very end of the mix

TARGET_DURATION_SEC = 3600
EXPORT_BITRATE = "320k"

# Video settings
VIDEO_SIZE = (1920, 1080)
VIDEO_FPS = 24
BG_COLOR = (8, 8, 14)
FONT_PATH = "/System/Library/Fonts/HelveticaNeue.ttc"
TITLE_FONT_SIZE = 56
TITLE_COLOR = "white"
TITLE_FADE_SEC = 3
TITLE_Y = 400                    # Fixed y position for title text

# Waveform visualizer
WAVEFORM_Y = 780                 # Top of waveform region
WAVEFORM_HEIGHT = 200            # Height of waveform region
WAVEFORM_WINDOW_SEC = 4.0        # Seconds of audio visible in the waveform
ENVELOPE_HOP_MS = 5              # Resolution of amplitude envelope

# Spectral coloring
N_SPECTRAL_BANDS = 6
N_MELS = 128
SPECTRAL_SMOOTHING = 0.7        # Temporal EMA smoothing (0=none, 0.9=heavy)
SPECTRAL_ENERGY_FLOOR = 0.15    # Minimum brightness so shape stays visible

# Color palette: center (bass) → edge (treble)
SPECTRAL_PALETTE = np.array([
    [240, 100,  40],   # sub-bass:  red-amber
    [240, 150,  50],   # bass:      orange
    [220, 200,  80],   # low-mid:   warm yellow
    [ 60, 200, 200],   # mid:       teal
    [ 80, 140, 230],   # high-mid:  blue
    [120,  80, 220],   # treble:    violet
], dtype=np.float32)


# === Audio utilities ===

def change_speed(segment, factor):
    """Change playback speed via resampling (affects pitch proportionally).
    This is the classic DJ turntable approach — natural-sounding for small changes.
    factor > 1.0 = faster/higher pitch, < 1.0 = slower/lower pitch.
    """
    if abs(factor - 1.0) < 0.001:
        return segment
    new_frame_rate = int(segment.frame_rate * factor)
    return segment._spawn(
        segment.raw_data, overrides={"frame_rate": new_frame_rate}
    ).set_frame_rate(segment.frame_rate)


def tempo_ramp(segment, native_bpm, from_bpm, to_bpm, steps=RAMP_STEPS):
    """Gradually change playback speed across a segment.

    The raw audio is at native_bpm. Playback starts at from_bpm and
    smoothly transitions to to_bpm over `steps` equal chunks.
    """
    if abs(from_bpm - to_bpm) < 0.5:
        return change_speed(segment, from_bpm / native_bpm)

    chunk_ms = len(segment) // steps
    if chunk_ms < 50:
        avg_factor = ((from_bpm + to_bpm) / 2) / native_bpm
        return change_speed(segment, avg_factor)

    result = AudioSegment.empty()
    for i in range(steps):
        t = i / (steps - 1) if steps > 1 else 1.0
        target_bpm = from_bpm + (to_bpm - from_bpm) * t
        factor = target_bpm / native_bpm

        start_ms = i * chunk_ms
        end_ms = (start_ms + chunk_ms) if i < steps - 1 else len(segment)
        result += change_speed(segment[start_ms:end_ms], factor)

    return result


# === Analysis ===

def get_bpm_and_beats(filepath):
    """Return (bpm, beat_times_array) for a track."""
    y, sr = librosa.load(filepath, sr=None, mono=True)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beats, sr=sr)
    return float(np.squeeze(tempo)), beat_times


def find_beat_near(beat_times, target_sec):
    """Snap a time position to the nearest detected beat."""
    if len(beat_times) == 0:
        return target_sec
    idx = np.argmin(np.abs(beat_times - target_sec))
    return float(beat_times[idx])


def compute_transition_bpm(bpm_out, bpm_in):
    """Shared BPM during crossfade.
    Small diff  → incoming stretches to match outgoing (less noticeable).
    Large diff  → meet in the middle so neither track warps too much.
    """
    if abs(bpm_out - bpm_in) <= BPM_MATCH_THRESHOLD:
        return bpm_out
    return (bpm_out + bpm_in) / 2.0


# === Track loading ===

def load_tracks(tracks_dir):
    files = sorted(f for f in os.listdir(tracks_dir) if f.lower().endswith(".mp3"))
    if not files:
        print(f"No MP3 files found in {tracks_dir}")
        sys.exit(1)
    print(f"Found {len(files)} tracks:")
    for f in files:
        print(f"  {f}")
    return [os.path.join(tracks_dir, f) for f in files]


def analyze_tracks(filepaths):
    analyzed = []
    for fp in filepaths:
        name = os.path.basename(fp)
        print(f"Analyzing {name}...")
        bpm, beats = get_bpm_and_beats(fp)
        print(f"  BPM: {bpm:.1f} | Beats: {len(beats)}")
        analyzed.append({"path": fp, "bpm": bpm, "beats": beats})

    analyzed.sort(key=lambda t: t["bpm"])
    print("\nPlayback order (sorted by BPM):")
    for t in analyzed:
        print(f"  {t['bpm']:6.1f} BPM — {os.path.basename(t['path'])}")
    return analyzed


# === Mix builder ===

def _track_display_name(filepath):
    """Strip extension for display."""
    return os.path.splitext(os.path.basename(filepath))[0]


def _adjust_outgoing_tail(mix, mix_bpm, trans_bpm):
    """Ramp the tail of the current mix from mix_bpm toward trans_bpm."""
    if abs(mix_bpm - trans_bpm) < 0.5:
        return mix

    ramp_ms = TEMPO_RAMP_SEC * 1000
    xfade_ms = CROSSFADE_SEC * 1000
    tail_ms = min(ramp_ms + xfade_ms, len(mix))

    tail = mix[-tail_ms:]
    pre_tail = mix[:-tail_ms]

    if len(tail) > xfade_ms:
        ramp_part = tail[: len(tail) - xfade_ms]
        xfade_part = tail[len(tail) - xfade_ms :]
    else:
        ramp_part = AudioSegment.empty()
        xfade_part = tail

    if len(ramp_part) > 0:
        ramp_part = tempo_ramp(ramp_part, mix_bpm, mix_bpm, trans_bpm)
    xfade_part = change_speed(xfade_part, trans_bpm / mix_bpm)

    return pre_tail + ramp_part + xfade_part


def _prepare_incoming(segment, native_bpm, trans_bpm, beats, duration_sec):
    """Split and tempo-adjust the incoming track into three sections:
    1. Crossfade section  — at trans_bpm
    2. Ramp section       — gradual trans_bpm → native_bpm
    3. Body               — native BPM (ends early, leaving room for next crossfade)
    """
    xfade_end = find_beat_near(beats, CROSSFADE_SEC)
    ramp_end = find_beat_near(beats, CROSSFADE_SEC + TEMPO_RAMP_SEC)
    body_end = find_beat_near(beats, duration_sec - CROSSFADE_SEC)

    ramp_end = max(ramp_end, xfade_end + 0.1)
    body_end = max(body_end, ramp_end + 0.1)

    xfade_part = segment[: int(xfade_end * 1000)]
    ramp_part = segment[int(xfade_end * 1000) : int(ramp_end * 1000)]
    body_part = segment[int(ramp_end * 1000) : int(body_end * 1000)]

    if abs(native_bpm - trans_bpm) > 0.5:
        xfade_part = change_speed(xfade_part, trans_bpm / native_bpm)
        ramp_part = tempo_ramp(ramp_part, native_bpm, trans_bpm, native_bpm)

    return xfade_part + ramp_part + body_part


def build_mix(tracks):
    """Build the audio mix and return (AudioSegment, transitions).

    transitions is a list of {"name": str, "start_sec": float} dicts
    recording when each track becomes audible in the final mix.
    """
    mix = None
    mix_bpm = None
    transitions = []

    for i, track in enumerate(tracks):
        name = _track_display_name(track["path"])
        native_bpm = track["bpm"]
        beats = track["beats"]
        segment = AudioSegment.from_mp3(track["path"])
        duration_sec = len(segment) / 1000.0

        print(f"\n[{i + 1}/{len(tracks)}] {name} "
              f"({native_bpm:.1f} BPM, {duration_sec:.0f}s)")

        # --- First track ---
        if i == 0:
            cut_sec = find_beat_near(beats, duration_sec - CROSSFADE_SEC)
            mix = segment[: int(cut_sec * 1000)]
            mix_bpm = native_bpm
            transitions.append({"name": name, "start_sec": 0.0})
            print(f"  Body: {cut_sec:.1f}s | Mix: {len(mix)/1000/60:.1f} min")
            continue

        # --- Transition BPM ---
        trans_bpm = compute_transition_bpm(mix_bpm, native_bpm)
        bpm_diff = abs(mix_bpm - native_bpm)
        strategy = ("meet-in-middle" if bpm_diff > BPM_MATCH_THRESHOLD
                     else "match outgoing")
        print(f"  {mix_bpm:.1f} → {native_bpm:.1f} BPM "
              f"(Δ{bpm_diff:.1f}, {strategy}, xfade@{trans_bpm:.1f})")

        # --- Adjust outgoing tail ---
        mix = _adjust_outgoing_tail(mix, mix_bpm, trans_bpm)

        # --- Prepare incoming track ---
        incoming = _prepare_incoming(
            segment, native_bpm, trans_bpm, beats, duration_sec
        )

        # Record transition timestamp (where the crossfade begins)
        crossfade_ms = min(CROSSFADE_SEC * 1000, len(mix), len(incoming))
        track_start_sec = (len(mix) - crossfade_ms) / 1000.0
        transitions.append({"name": name, "start_sec": track_start_sec})

        # --- Crossfade ---
        mix = mix.append(incoming, crossfade=crossfade_ms)
        mix_bpm = native_bpm

        total_min = len(mix) / 1000 / 60
        print(f"  Mix: {total_min:.1f} min")

        if len(mix) >= TARGET_DURATION_SEC * 1000:
            print(f"\nReached target ({TARGET_DURATION_SEC / 60:.0f} min)")
            break

    # Trim + fade out
    if len(mix) > TARGET_DURATION_SEC * 1000:
        mix = mix[: TARGET_DURATION_SEC * 1000]
    mix = mix.fade_out(FADE_OUT_SEC * 1000)

    print("\nTransition map:")
    for t in transitions:
        m, s = divmod(t["start_sec"], 60)
        print(f"  {int(m):02d}:{s:05.2f} — {t['name']}")

    return mix, transitions


# === Audio export ===

def export_mix(mix, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    duration_min = len(mix) / 1000 / 60
    print(f"\nExporting audio to {output_path} ({EXPORT_BITRATE}, {duration_min:.1f} min)...")
    mix.export(output_path, format="mp3", bitrate=EXPORT_BITRATE)
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Done! {size_mb:.1f} MB")


# === Video generation ===

def _precompute_audio_data(audio_path):
    """Load audio, compute amplitude envelope and spectral band energies.

    Returns (envelope, env_sr, band_energies) where:
      - envelope:      1-D float array, RMS amplitude per hop
      - env_sr:        envelope sample rate (Hz)
      - band_energies: (N_SPECTRAL_BANDS, n_frames) float32, normalised [0,1]
    """
    print("Loading audio for waveform & spectral analysis...")
    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    hop_samples = int(sr * ENVELOPE_HOP_MS / 1000)

    # --- Amplitude envelope (unchanged) ---
    n_frames = len(y) // hop_samples
    envelope = np.array([
        np.sqrt(np.mean(y[i * hop_samples : (i + 1) * hop_samples] ** 2))
        for i in range(n_frames)
    ])
    peak = np.max(envelope)
    if peak > 0:
        envelope /= peak
    env_sr = 1000.0 / ENVELOPE_HOP_MS
    print(f"  Envelope: {n_frames} points @ {env_sr:.0f} Hz")

    # --- Spectral band energies ---
    S = librosa.feature.melspectrogram(
        y=y, sr=sr, n_mels=N_MELS, hop_length=hop_samples,
    )
    S_db = librosa.power_to_db(S, ref=np.max)              # (128, T), [-80, 0]
    S_norm = np.clip((S_db + 80.0) / 80.0, 0.0, 1.0)      # (128, T), [0, 1]

    n_spec_frames = S_norm.shape[1]
    bins_per_band = N_MELS // N_SPECTRAL_BANDS
    band_energies = np.zeros((N_SPECTRAL_BANDS, n_spec_frames), dtype=np.float32)
    for b in range(N_SPECTRAL_BANDS):
        lo = b * bins_per_band
        hi = (b + 1) * bins_per_band if b < N_SPECTRAL_BANDS - 1 else N_MELS
        band_energies[b] = S_norm[lo:hi].mean(axis=0)

    # Per-band normalisation with soft floor to preserve relative loudness
    for b in range(N_SPECTRAL_BANDS):
        bp = band_energies[b].max()
        if bp > 0:
            band_energies[b] /= max(bp, 0.3)
            np.clip(band_energies[b], 0.0, 1.0, out=band_energies[b])

    # Temporal EMA smoothing to avoid flicker
    alpha = 1.0 - SPECTRAL_SMOOTHING
    for i in range(1, n_spec_frames):
        band_energies[:, i] = (
            alpha * band_energies[:, i]
            + SPECTRAL_SMOOTHING * band_energies[:, i - 1]
        )

    # Align lengths (mel spectrogram may have +1 frame)
    common = min(n_frames, n_spec_frames)
    envelope = envelope[:common]
    band_energies = band_energies[:, :common]

    print(f"  Spectral bands: {N_SPECTRAL_BANDS} x {common} frames")
    return envelope, env_sr, band_energies


def _draw_waveform(frame, envelope, env_sr, t, band_energies):
    """Draw a spectral-colored waveform onto the frame for time t."""
    width = frame.shape[1]
    center_idx = int(t * env_sr)
    half_window = int(WAVEFORM_WINDOW_SEC * env_sr / 2)

    start = max(0, center_idx - half_window)
    end = min(len(envelope), center_idx + half_window)
    window = envelope[start:end]

    if len(window) < 2:
        return

    # Resample to screen width and smooth
    indices = np.linspace(0, len(window) - 1, width).astype(int)
    amplitudes = gaussian_filter1d(window[indices], sigma=6)

    # Spectral band energies for this window, resampled to screen width
    band_window = band_energies[:, start:end]              # (B, window_len)
    band_cols = band_window[:, indices].copy()              # (B, W)
    for b in range(N_SPECTRAL_BANDS):
        band_cols[b] = gaussian_filter1d(band_cols[b], sigma=6)

    # Compute vertical extents (same shape logic as before)
    wf_center = WAVEFORM_HEIGHT // 2
    max_extent = wf_center - 4
    y_extents = (amplitudes * max_extent).astype(int)

    # Vectorised mask
    y_col = np.arange(WAVEFORM_HEIGHT)[:, np.newaxis]      # (H, 1)
    upper = (wf_center - y_extents)[np.newaxis, :]          # (1, W)
    lower = (wf_center + y_extents)[np.newaxis, :]          # (1, W)
    mask = (y_col >= upper) & (y_col <= lower)              # (H, W)

    # Normalised distance from center: 0 at center, 1 at edge
    dist = np.abs(y_col - wf_center).astype(np.float32)
    max_dist = np.maximum(y_extents[np.newaxis, :].astype(np.float32), 1.0)
    norm_dist = np.clip(dist / max_dist, 0.0, 1.0)         # (H, W)

    # Map distance to fractional band index and interpolate colours
    band_pos = norm_dist * (N_SPECTRAL_BANDS - 1)          # (H, W)
    band_lo = np.floor(band_pos).astype(int)
    band_hi = np.minimum(band_lo + 1, N_SPECTRAL_BANDS - 1)
    frac = band_pos - band_lo                               # (H, W)

    color_lo = SPECTRAL_PALETTE[band_lo]                    # (H, W, 3)
    color_hi = SPECTRAL_PALETTE[band_hi]                    # (H, W, 3)
    base_color = color_lo + frac[:, :, np.newaxis] * (color_hi - color_lo)

    # Per-pixel spectral energy from the two neighbouring bands
    w_idx = np.broadcast_to(np.arange(width)[np.newaxis, :], band_lo.shape)
    energy_lo = band_cols[band_lo, w_idx]                   # (H, W)
    energy_hi = band_cols[band_hi, w_idx]
    energy = energy_lo + frac * (energy_hi - energy_lo)

    # Edge fade + energy floor → final brightness
    edge_fade = np.clip(1.0 - 0.3 * norm_dist, 0.0, 1.0)
    energy_mod = np.clip(
        energy * (1.0 - SPECTRAL_ENERGY_FLOOR) + SPECTRAL_ENERGY_FLOOR,
        0.0, 1.0,
    )
    brightness = (energy_mod * edge_fade)[:, :, np.newaxis] # (H, W, 1)

    pixel_colors = (base_color * brightness).astype(np.uint8)  # (H, W, 3)

    # Apply to frame
    region = frame[WAVEFORM_Y : WAVEFORM_Y + WAVEFORM_HEIGHT]
    mask_3d = mask[:, :, np.newaxis]
    region[:] = np.where(mask_3d, pixel_colors, region)


def _make_title_clip(name, start_sec, end_sec):
    """Create a single track-title text clip with fade in/out."""
    fade_in = min(TITLE_FADE_SEC, (end_sec - start_sec) / 3)
    fade_out = min(TITLE_FADE_SEC, (end_sec - start_sec) / 3)

    clip = (
        TextClip(
            font=FONT_PATH,
            text=name,
            font_size=TITLE_FONT_SIZE,
            color=TITLE_COLOR,
            margin=(0, 20),
            duration=end_sec - start_sec,
        )
        .with_position(("center", TITLE_Y))
        .with_start(start_sec)
        .with_effects([
            vfx.CrossFadeIn(fade_in),
            vfx.CrossFadeOut(fade_out),
        ])
    )
    return clip


def generate_video(audio_path, transitions, output_path):
    """Compose a video: dark background + waveform + track titles."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    audio = AudioFileClip(audio_path)
    total_duration = audio.duration

    # Pre-compute waveform envelope and spectral band energies
    envelope, env_sr, band_energies = _precompute_audio_data(audio_path)

    # Dynamic background with spectral waveform
    def make_frame(t):
        frame = np.full(
            (VIDEO_SIZE[1], VIDEO_SIZE[0], 3), BG_COLOR, dtype=np.uint8
        )
        _draw_waveform(frame, envelope, env_sr, t, band_energies)
        return frame

    bg = VideoClip(make_frame, duration=total_duration)

    # Build title clips
    title_clips = []
    for i, t in enumerate(transitions):
        start = t["start_sec"]
        end = transitions[i + 1]["start_sec"] if i + 1 < len(transitions) else total_duration
        title_clips.append(_make_title_clip(t["name"], start, end))

    video = CompositeVideoClip([bg] + title_clips, size=VIDEO_SIZE)
    video = video.with_audio(audio)

    print(f"\nRendering video to {output_path} ({VIDEO_SIZE[0]}x{VIDEO_SIZE[1]}, {VIDEO_FPS}fps)...")
    video.write_videofile(
        output_path,
        fps=VIDEO_FPS,
        codec="libx264",
        audio_codec="aac",
        audio_bitrate="320k",
        preset="medium",
        logger="bar",
    )
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Video done! {size_mb:.1f} MB")


# === Main ===

def main():
    print("=== Deep Session Generator ===\n")

    filepaths = load_tracks(TRACKS_DIR)
    tracks = analyze_tracks(filepaths)
    mix, transitions = build_mix(tracks)
    export_mix(mix, AUDIO_PATH)
    generate_video(AUDIO_PATH, transitions, VIDEO_PATH)


if __name__ == "__main__":
    main()
