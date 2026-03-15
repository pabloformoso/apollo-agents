import base64
import io
import json
import os
import sys

import librosa
import numpy as np
import pyrubberband as pyrb
from dotenv import load_dotenv
from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    TextClip,
    VideoClip,
    VideoFileClip,
    vfx,
)
from openai import OpenAI
from PIL import Image, ImageFilter
from pydub import AudioSegment
from scipy.ndimage import gaussian_filter, gaussian_filter1d

# === Configuration ===
TRACKS_BASE_DIR = "./tracks"
OUTPUT_BASE_DIR = "./output"
ARTWORK_BASE_DIR = "./artwork"

AUDIO_EXTENSIONS = (".mp3", ".wav", ".flac", ".m4a", ".ogg")

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
TITLE_Y = 400                    # Fixed y position for title text

# Retro title styling
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(_SCRIPT_DIR, "fonts", "PressStart2P-Regular.ttf")
TITLE_FONT_SIZE = 32             # Pixel fonts need smaller size to look crisp
RETRO_TITLE_COLOR = "#00FF88"    # Neon green
RETRO_TITLE_STROKE = "#004422"   # Dark green outline
RETRO_TITLE_SLIDE_SEC = 0.8     # Slide-in duration
RETRO_TITLE_GLOW_PERIOD = 3.0   # Seconds per glow cycle
RETRO_TITLE_GLOW_AMPLITUDE = 0.2

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

# AI-generated artwork backgrounds
ARTWORK_BLUR_RADIUS = 2
ARTWORK_DARKEN_FACTOR = 0.85        # 15% darker
ARTWORK_API_SIZE = "1792x1024"      # DALL-E 3 closest to 16:9

# Artwork prompt templates (keyed by artwork_style in session theme)
ARTWORK_PROMPTS = {
    "abstract": (
        "Abstract digital artwork inspired by '{track_name}'. "
        "Calm, serene, peaceful. Deep dark tones with subtle glowing accents. "
        "Ambient, ethereal. No text."
    ),
    "realistic": (
        "Photorealistic cosy room scene, warm ambient lighting, {track_name} mood, "
        "study desk with books, warm lamp, rain on window, plants, soft shadows. "
        "Shot on Canon 5D, 35mm lens. No text, no people."
    ),
    "anime": (
        "Beautiful anime-style illustration of a cosy Japanese study room, "
        "Studio Ghibli inspired, warm lighting, {track_name} atmosphere. "
        "Wooden desk with open books, warm table lamp, rain outside the window, "
        "potted plants, soft watercolor textures, hand-painted feel. "
        "Peaceful, nostalgic, warm color palette. No text, no characters visible."
    ),
    "dystopic-calm": (
        "Photorealistic dystopian landscape rendered in muted pastel tones, {track_name} atmosphere. "
        "Abandoned overgrown megastructure reclaimed by nature, soft fog rolling through crumbling "
        "concrete corridors, bioluminescent moss on rusted steel, still water reflecting a pale sky. "
        "Quiet desolation, no danger — just silence and slow decay. Cherry blossoms growing through "
        "broken glass, vines crawling over dormant machines. "
        "Shot on Hasselblad, 50mm lens, soft diffused light, washed-out color grading. No text, no people."
    ),
    "dark-techno": (
        "Photorealistic retropunk cyberpunk cityscape at night, {track_name} atmosphere. "
        "Rain-slicked streets reflecting neon signs, towering megastructures with exposed pipes "
        "and industrial scaffolding, holographic billboards glitching, steam rising from grates, "
        "dark alleys lit by red and magenta neon. Blade Runner meets industrial decay. "
        "Shot on Canon 5D, 35mm lens, cinematic lighting. No text, no people."
    ),
    "organic-zen": (
        "Warm painterly landscape in golden hour light, {track_name} atmosphere. "
        "Desert dunes, terracotta walls, or misty forest clearing. Earth tones — "
        "amber, sienna, sage green, warm sandstone. Textured like oil paint on rough canvas, "
        "visible brushstrokes. Organic flowing shapes, no sharp geometry. "
        "Medium format film grain, soft warm color grading. No text, no people."
    ),
    "deep-house-neon": (
        "Cinematic night scene evoking '{track_name}' — deep house music atmosphere. "
        "Moody underground club interior or rain-soaked city at 3am, deep indigo and violet "
        "tones with warm amber and electric purple neon reflections on wet surfaces. "
        "Subtle smoke haze, bokeh lights, vinyl turntable silhouette or mixing desk in shadow. "
        "Intimate, hypnotic, warm darkness. Film grain, shallow depth of field, "
        "shot on Leica M10, 50mm f/1.4. No text, no people."
    ),
}

# Video backgrounds (looped clips instead of AI artwork)
VIDEO_BG_LOOP_CROSSFADE = 1.0       # Seconds of crossfade for seamless loop
VIDEO_BG_DARKEN = 0.35              # Brightness multiplier (darker = overlays more readable)

# Beat-reactive particles
PARTICLE_COUNT = 150
PARTICLE_MIN_RADIUS = 2
PARTICLE_MAX_RADIUS = 5
PARTICLE_BASE_ALPHA = 0.15          # resting opacity
PARTICLE_BEAT_ALPHA = 0.6           # peak on beat
PARTICLE_BEAT_DECAY = 2.0           # seconds
PARTICLE_DRIFT_SPEED = 15           # px/s
PARTICLE_COLOR = [180, 200, 240]    # soft blue-white

# Waveform glow/bloom
GLOW_SIGMA = 12
GLOW_INTENSITY = 0.7

# YouTube Shorts (vertical 9:16)
SHORT_VIDEO_SIZE = (1080, 1920)
SHORT_DURATION_SEC = 20
SHORT_FADE_IN_SEC = 0.5
SHORT_FADE_OUT_SEC = 1.0
SHORT_ARTWORK_SQUARE = 600              # px, centered track artwork
SHORT_ARTWORK_Y = 400                   # top of artwork square
SHORT_SESSION_TITLE_Y = 100             # session name position
SHORT_TRACK_TITLE_Y = 1060              # below artwork square
SHORT_WAVEFORM_Y = 1350                 # waveform region top
SHORT_WAVEFORM_HEIGHT = 180
SHORT_CTA_Y = 1750                      # "Watch full session" position
SHORT_CTA_TEXT = "Watch full session"


# === Theme system ===

DEFAULT_THEME = {
    "font": FONT_PATH,
    "title_color": RETRO_TITLE_COLOR,
    "title_stroke_color": RETRO_TITLE_STROKE,
    "title_font_size": TITLE_FONT_SIZE,
    "bg_color": list(BG_COLOR),
    "waveform_color": list(SPECTRAL_PALETTE[0].astype(int)),
    "particle_color": list(PARTICLE_COLOR),
    "bg_darken": VIDEO_BG_DARKEN,
    "artwork_style": "abstract",
}


def _get_session_theme(session_config):
    """Return a merged theme dict: defaults overridden by session-specific values.

    All theme fields are individually optional — partial overrides work.
    Sessions without a theme block get all defaults (backward compatible).
    """
    theme = dict(DEFAULT_THEME)
    if session_config:
        overrides = session_config.get("theme", {})
        theme.update(overrides)
    # Resolve font path relative to project root
    if not os.path.isabs(theme["font"]):
        theme["font"] = os.path.join(_SCRIPT_DIR, theme["font"])
    return theme


# === Audio utilities ===

def _segment_to_numpy(segment):
    """Convert pydub AudioSegment to numpy float32 array."""
    samples = np.frombuffer(segment.raw_data, dtype=np.int16)
    if segment.channels > 1:
        samples = samples.reshape(-1, segment.channels)
    return samples.astype(np.float32) / 32768.0


def _numpy_to_segment(data, segment):
    """Convert numpy float32 array back to pydub AudioSegment matching source format."""
    clipped = np.clip(data, -1.0, 1.0)
    int_data = (clipped * 32768.0).astype(np.int16)
    return AudioSegment(
        data=int_data.tobytes(),
        sample_width=2,
        frame_rate=segment.frame_rate,
        channels=segment.channels,
    )


def change_tempo(segment, factor):
    """Change playback tempo without altering pitch (key-preserving).
    Uses Rubber Band for high-quality time-stretching.
    factor > 1.0 = faster, < 1.0 = slower. Pitch stays the same.
    """
    if abs(factor - 1.0) < 0.001:
        return segment
    y = _segment_to_numpy(segment)
    stretched = pyrb.time_stretch(y, segment.frame_rate, factor,
                                  rbargs={'-c': '6'})
    return _numpy_to_segment(stretched, segment)


change_speed = change_tempo


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


# === Session system ===

def resolve_session(session_arg):
    """Resolve session directory and config from CLI argument.

    Returns (session_dir, session_config_or_None).
    """
    if session_arg is not None:
        # Try as a number first: "2" → "tracks/session 2"
        session_dir = os.path.join(TRACKS_BASE_DIR, f"session {session_arg}")
        if not os.path.isdir(session_dir):
            # Try as a direct path
            session_dir = session_arg
        if not os.path.isdir(session_dir):
            print(f"Session not found: {session_arg}")
            sys.exit(1)
    else:
        # Auto-detect: list subdirectories in tracks/
        subdirs = sorted(
            d for d in os.listdir(TRACKS_BASE_DIR)
            if os.path.isdir(os.path.join(TRACKS_BASE_DIR, d))
        )
        if len(subdirs) == 0:
            print(f"No session directories found in {TRACKS_BASE_DIR}")
            sys.exit(1)
        elif len(subdirs) == 1:
            session_dir = os.path.join(TRACKS_BASE_DIR, subdirs[0])
        else:
            print("Available sessions:")
            for d in subdirs:
                print(f"  {d}")
            print(f"\nUsage: python main.py <session_number>")
            sys.exit(1)

    # Load session.json if it exists
    config_path = os.path.join(session_dir, "session.json")
    session_config = None
    if os.path.exists(config_path):
        with open(config_path) as f:
            session_config = json.load(f)

    return session_dir, session_config


def load_session_tracks(session_dir, session_config):
    """Load track entries from session config or filesystem scan.

    Returns list of dicts: [{"path", "display_name", "camelot_key", "genre"}, ...]
    """
    if session_config is not None:
        # Playlist-ordered loading from session.json
        entries = []
        for item in session_config["playlist"]:
            path = os.path.join(session_dir, item["file"])
            if not os.path.exists(path):
                print(f"Error: file not found: {path}")
                sys.exit(1)
            entries.append({
                "path": path,
                "display_name": item["display_name"],
                "camelot_key": item.get("camelot_key"),
                "genre": item.get("genre"),
            })
        print(f"Playlist: {len(entries)} entries")
        for i, e in enumerate(entries, 1):
            key = f" ({e['camelot_key']})" if e["camelot_key"] else ""
            print(f"  {i:2d}. {e['display_name']}{key}")
        return entries
    else:
        # Backward-compat: scan directory for audio files
        files = sorted(
            f for f in os.listdir(session_dir)
            if any(f.lower().endswith(ext) for ext in AUDIO_EXTENSIONS)
        )
        if not files:
            print(f"No audio files found in {session_dir}")
            sys.exit(1)
        print(f"Found {len(files)} tracks:")
        entries = []
        for f in files:
            display_name = os.path.splitext(f)[0]
            print(f"  {f}")
            entries.append({
                "path": os.path.join(session_dir, f),
                "display_name": display_name,
                "camelot_key": None,
                "genre": None,
            })
        return entries


def get_output_paths(session_dir):
    """Compute per-session output and artwork directories."""
    session_name = os.path.basename(session_dir)
    output_dir = os.path.join(OUTPUT_BASE_DIR, session_name)
    artwork_dir = os.path.join(ARTWORK_BASE_DIR, session_name)
    audio_path = os.path.join(output_dir, "mix_output.wav")
    video_path = os.path.join(output_dir, "mix_video.mp4")
    return output_dir, artwork_dir, audio_path, video_path


# === Track analysis ===

def analyze_tracks(track_entries, use_playlist_order=False):
    """Analyze BPM and beats for each track entry.

    When use_playlist_order is True, preserves playlist order.
    Otherwise sorts by BPM (backward compat).
    """
    analyzed = []
    for entry in track_entries:
        name = entry["display_name"]
        print(f"Analyzing {name} ({os.path.basename(entry['path'])})...")
        bpm, beats = get_bpm_and_beats(entry["path"])
        print(f"  BPM: {bpm:.1f} | Beats: {len(beats)}")
        analyzed.append({
            "path": entry["path"],
            "display_name": name,
            "bpm": bpm,
            "beats": beats,
            "camelot_key": entry.get("camelot_key"),
            "genre": entry.get("genre"),
        })

    if not use_playlist_order:
        analyzed.sort(key=lambda t: t["bpm"])
        print("\nPlayback order (sorted by BPM):")
    else:
        print("\nPlayback order (playlist):")
    for i, t in enumerate(analyzed, 1):
        key = f" [{t['camelot_key']}]" if t.get("camelot_key") else ""
        print(f"  {i:2d}. {t['bpm']:6.1f} BPM — {t['display_name']}{key}")
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


def build_mix(tracks, target_duration_sec=TARGET_DURATION_SEC):
    """Build the audio mix and return (AudioSegment, transitions).

    transitions is a list of {"name": str, "start_sec": float} dicts
    recording when each track becomes audible in the final mix.

    target_duration_sec: max duration in seconds, or None to use all tracks.
    """
    mix = None
    mix_bpm = None
    transitions = []

    for i, track in enumerate(tracks):
        name = track.get("display_name") or _track_display_name(track["path"])
        native_bpm = track["bpm"]
        beats = track["beats"]
        segment = AudioSegment.from_file(track["path"])
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

        if target_duration_sec and len(mix) >= target_duration_sec * 1000:
            print(f"\nReached target ({target_duration_sec / 60:.0f} min)")
            break

    # Trim + fade out
    if target_duration_sec and len(mix) > target_duration_sec * 1000:
        mix = mix[: int(target_duration_sec * 1000)]
    mix = mix.fade_out(FADE_OUT_SEC * 1000)

    print("\nTransition map:")
    for t in transitions:
        m, s = divmod(t["start_sec"], 60)
        print(f"  {int(m):02d}:{s:05.2f} — {t['name']}")

    return mix, transitions


# === Audio export ===

def export_mix(mix, output_path, audio_format="wav"):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    duration_min = len(mix) / 1000 / 60

    export_kwargs = {"format": audio_format}
    if audio_format == "mp3":
        export_kwargs["bitrate"] = EXPORT_BITRATE

    label = audio_format.upper()
    print(f"\nExporting audio to {output_path} ({label}, {duration_min:.1f} min)...")
    mix.export(output_path, **export_kwargs)
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Done! {size_mb:.1f} MB")


# === YouTube Short generation ===

def find_highlight_segment(audio_path, duration_sec=SHORT_DURATION_SEC):
    """Find the start time of the highest-energy window in the mix.

    Slides a window of `duration_sec` across the audio and returns the
    start timestamp (seconds) with maximum average RMS energy.
    """
    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    window_samples = int(duration_sec * sr)
    total_samples = len(y)

    if total_samples <= window_samples:
        return 0.0

    # Compute RMS in sliding windows with 1-second hop
    hop_samples = sr
    best_start = 0.0
    best_rms = 0.0

    for start in range(0, total_samples - window_samples, hop_samples):
        window = y[start:start + window_samples]
        rms = float(np.sqrt(np.mean(window ** 2)))
        if rms > best_rms:
            best_rms = rms
            best_start = start / sr

    print(f"  Highlight: {best_start:.1f}s (RMS={best_rms:.4f})")
    return best_start


def extract_short_audio(audio_path, start_sec, duration_sec=SHORT_DURATION_SEC):
    """Extract a segment from the mix WAV with fade-in/out. Returns AudioSegment."""
    audio = AudioSegment.from_file(audio_path)
    start_ms = int(start_sec * 1000)
    end_ms = start_ms + int(duration_sec * 1000)
    end_ms = min(end_ms, len(audio))
    segment = audio[start_ms:end_ms]
    segment = segment.fade_in(int(SHORT_FADE_IN_SEC * 1000))
    segment = segment.fade_out(int(SHORT_FADE_OUT_SEC * 1000))
    return segment


def _short_ken_burns_frame(image, t, duration):
    """Ken Burns effect adapted for vertical 1080×1920 output."""
    if isinstance(image, Image.Image):
        image = np.array(image)
    h, w = image.shape[:2]
    tgt_w, tgt_h = SHORT_VIDEO_SIZE

    scale = 1.0 + 0.05 * np.sin(np.pi * t / duration)
    offset_x = 5 * np.sin(2 * np.pi * t / duration)
    offset_y = 3 * np.cos(2 * np.pi * t / duration)

    crop_w = int(tgt_w / scale)
    crop_h = int(tgt_h / scale)

    cx = w / 2 + offset_x
    cy = h / 2 + offset_y

    x1 = int(np.clip(cx - crop_w / 2, 0, w - crop_w))
    y1 = int(np.clip(cy - crop_h / 2, 0, h - crop_h))

    cropped = image[y1:y1 + crop_h, x1:x1 + crop_w]
    pil_img = Image.fromarray(cropped)
    pil_img = pil_img.resize((tgt_w, tgt_h), Image.LANCZOS)
    return np.array(pil_img, dtype=np.uint8)


def _find_track_at_time(transitions, t):
    """Return the index and name of the track playing at time t."""
    idx = 0
    for i, tr in enumerate(transitions):
        if tr["start_sec"] <= t:
            idx = i
    return idx, transitions[idx]["name"]


def _render_short_frame(t, bg_image, track_artwork, session_title,
                        track_name, envelope, env_sr, band_energies,
                        wf_palette, theme, frame_buf):
    """Compose a single vertical short frame into frame_buf."""
    tgt_w, tgt_h = SHORT_VIDEO_SIZE

    # 1. Artwork background (darkened Ken Burns)
    bg_frame = _short_ken_burns_frame(bg_image, t, SHORT_DURATION_SEC)
    bg_darkened = (bg_frame.astype(np.float32) * theme["bg_darken"]).astype(np.uint8)
    np.copyto(frame_buf, bg_darkened)

    _apply_waveform_gradient(frame_buf, height=SHORT_WAVEFORM_HEIGHT + 100)

    # 2. Session title at top
    session_img = _render_text_rgba(
        session_title.upper(),
        theme["font"],
        max(14, theme["title_font_size"] - 8),
        _hex_to_rgb(theme["title_color"]),
        _hex_to_rgb(theme["title_stroke_color"]),
    )
    sx = (tgt_w - session_img.shape[1]) // 2
    _blend_title_onto_frame(frame_buf, session_img, sx, SHORT_SESSION_TITLE_Y, 200)

    # 3. Centered track artwork square
    if track_artwork is not None:
        sq = SHORT_ARTWORK_SQUARE
        art_x = (tgt_w - sq) // 2
        art_y = SHORT_ARTWORK_Y
        pil_art = Image.fromarray(track_artwork).resize((sq, sq), Image.LANCZOS)
        art_arr = np.array(pil_art, dtype=np.uint8)
        # Paste onto frame (no alpha needed, artwork is RGB)
        frame_buf[art_y:art_y + sq, art_x:art_x + sq] = art_arr

    # 4. Track name below artwork
    track_img = _render_text_rgba(
        track_name.upper(),
        theme["font"],
        max(14, theme["title_font_size"] - 4),
        _hex_to_rgb(theme["title_color"]),
        _hex_to_rgb(theme["title_stroke_color"]),
    )
    tx = (tgt_w - track_img.shape[1]) // 2
    _blend_title_onto_frame(frame_buf, track_img, tx, SHORT_TRACK_TITLE_Y, 255)

    # 5. Waveform visualizer (adapted width and position)
    pixel_colors, mask = _compute_waveform_data(
        envelope, env_sr, t, band_energies, tgt_w, palette=wf_palette
    )
    if pixel_colors is not None:
        wf_h = min(SHORT_WAVEFORM_HEIGHT, pixel_colors.shape[0])
        region = frame_buf[SHORT_WAVEFORM_Y:SHORT_WAVEFORM_Y + wf_h]
        pc = pixel_colors[:wf_h]
        m = mask[:wf_h]
        region[:] = np.where(m[:, :, np.newaxis], pc, region)

    # 6. CTA text at bottom
    cta_img = _render_text_rgba(
        SHORT_CTA_TEXT,
        theme["font"],
        max(12, theme["title_font_size"] - 12),
        (255, 255, 255),
        (80, 80, 80),
    )
    cx = (tgt_w - cta_img.shape[1]) // 2
    # Pulsing opacity for CTA
    cta_opacity = 0.6 + 0.3 * np.sin(2 * np.pi * t / 2.0)
    _blend_title_onto_frame(frame_buf, cta_img, cx, SHORT_CTA_Y, int(cta_opacity * 255))

    return frame_buf


def generate_short(session_dir, session_config, transitions, audio_path,
                   artwork_dir, output_path):
    """Generate a 20-second vertical YouTube Short from an existing session mix."""
    print("\n=== Generating YouTube Short ===\n")

    theme = _get_session_theme(session_config)
    session_title = session_config["name"] if session_config else os.path.basename(session_dir)

    # 1. Find highlight segment
    print("Finding highlight segment...")
    highlight_start = find_highlight_segment(audio_path)

    # 2. Determine which track plays at highlight midpoint
    midpoint = highlight_start + SHORT_DURATION_SEC / 2
    track_idx, track_name = _find_track_at_time(transitions, midpoint)
    print(f"  Track at highlight: {track_name} (#{track_idx + 1})")

    # 3. Extract short audio
    print("Extracting audio segment...")
    short_audio = extract_short_audio(audio_path, highlight_start)
    short_audio_path = output_path.replace(".mp4", "_audio.wav")
    short_audio.export(short_audio_path, format="wav")

    # 4. Load artwork for background and square
    artwork_path = os.path.join(artwork_dir, f"{track_name}.png")
    if os.path.exists(artwork_path):
        art_img = Image.open(artwork_path).convert("RGB")
        # Background: scale to cover vertical frame
        bg_w = int(SHORT_VIDEO_SIZE[0] * 1.1)
        bg_h = int(SHORT_VIDEO_SIZE[1] * 1.1)
        bg_image = np.array(_cover_crop(art_img, bg_w, bg_h), dtype=np.uint8)
        # Square: original resolution crop
        track_artwork = np.array(art_img, dtype=np.uint8)
    else:
        print(f"  No artwork found at {artwork_path}, using solid background")
        bg_color = tuple(theme["bg_color"])
        bg_image = np.full((SHORT_VIDEO_SIZE[1], SHORT_VIDEO_SIZE[0], 3),
                           bg_color, dtype=np.uint8)
        track_artwork = None

    # 5. Pre-compute audio data for waveform (from the short segment)
    print("Analyzing short audio for waveform...")
    envelope, env_sr, band_energies, _beat_times = _precompute_audio_data(short_audio_path)

    # Build waveform palette from theme
    wf_color = np.array(theme["waveform_color"], dtype=np.float32)
    if np.array_equal(wf_color.astype(int), SPECTRAL_PALETTE[0].astype(int)):
        wf_palette = SPECTRAL_PALETTE
    else:
        brightness_ramp = np.linspace(1.0, 0.5, N_SPECTRAL_BANDS)
        wf_palette = np.array(
            [wf_color * b for b in brightness_ramp], dtype=np.float32)

    # 6. Pre-allocate frame buffer
    tgt_w, tgt_h = SHORT_VIDEO_SIZE
    frame_buf = np.empty((tgt_h, tgt_w, 3), dtype=np.uint8)

    def make_frame(t):
        _render_short_frame(
            t, bg_image, track_artwork, session_title,
            track_name, envelope, env_sr, band_energies,
            wf_palette, theme, frame_buf,
        )
        return frame_buf

    # 7. Render video
    audio_clip = AudioFileClip(short_audio_path)
    duration = audio_clip.duration
    bg_clip = VideoClip(make_frame, duration=duration).with_fps(VIDEO_FPS)
    video = bg_clip.with_audio(audio_clip)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    print(f"\nRendering short to {output_path} ({tgt_w}x{tgt_h}, {VIDEO_FPS}fps)...")
    video.write_videofile(
        output_path,
        fps=VIDEO_FPS,
        codec="libx264",
        audio_codec="aac",
        audio_bitrate="320k",
        preset="medium",
        logger="bar",
    )

    # Clean up temp audio
    if os.path.exists(short_audio_path):
        os.remove(short_audio_path)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Short done! {size_mb:.1f} MB")


# === Video generation ===

def _precompute_audio_data(audio_path):
    """Load audio, compute amplitude envelope, spectral band energies, and beat times.

    Returns (envelope, env_sr, band_energies, beat_times) where:
      - envelope:      1-D float array, RMS amplitude per hop
      - env_sr:        envelope sample rate (Hz)
      - band_energies: (N_SPECTRAL_BANDS, n_frames) float32, normalised [0,1]
      - beat_times:    1-D float array, beat timestamps in seconds
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

    # --- Beat detection ---
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    print(f"  Beats: {len(beat_times)} @ ~{float(np.squeeze(tempo)):.1f} BPM")

    return envelope, env_sr, band_energies, beat_times


# Pre-computed waveform constants (avoid re-creating every frame)
_WF_CENTER = WAVEFORM_HEIGHT // 2
_WF_MAX_EXTENT = _WF_CENTER - 4
_WF_Y_COL = np.arange(WAVEFORM_HEIGHT)[:, np.newaxis]      # (H, 1)
_WF_DIST = np.abs(_WF_Y_COL - _WF_CENTER).astype(np.float32)  # (H, 1)
_WF_W_IDX_CACHE = {}


def _compute_waveform_data(envelope, env_sr, t, band_energies, width,
                           palette=SPECTRAL_PALETTE):
    """Compute waveform pixel colors and mask for time t (no frame mutation)."""
    center_idx = int(t * env_sr)
    half_window = int(WAVEFORM_WINDOW_SEC * env_sr / 2)

    start = max(0, center_idx - half_window)
    end = min(len(envelope), center_idx + half_window)
    window = envelope[start:end]

    if len(window) < 2:
        return None, None

    # Resample to screen width and smooth
    indices = np.linspace(0, len(window) - 1, width).astype(int)
    amplitudes = gaussian_filter1d(window[indices], sigma=6)

    # Spectral band energies for this window, resampled to screen width
    band_window = band_energies[:, start:end]              # (B, window_len)
    band_cols = band_window[:, indices].copy()              # (B, W)
    for b in range(N_SPECTRAL_BANDS):
        band_cols[b] = gaussian_filter1d(band_cols[b], sigma=6)

    # Compute vertical extents
    y_extents = (amplitudes * _WF_MAX_EXTENT).astype(int)

    # Vectorised mask
    upper = (_WF_CENTER - y_extents)[np.newaxis, :]         # (1, W)
    lower = (_WF_CENTER + y_extents)[np.newaxis, :]         # (1, W)
    mask = (_WF_Y_COL >= upper) & (_WF_Y_COL <= lower)     # (H, W)

    # Normalised distance from center: 0 at center, 1 at edge
    max_dist = np.maximum(y_extents[np.newaxis, :].astype(np.float32), 1.0)
    norm_dist = np.clip(_WF_DIST / max_dist, 0.0, 1.0)    # (H, W)

    # Map distance to fractional band index and interpolate colours
    band_pos = norm_dist * (N_SPECTRAL_BANDS - 1)          # (H, W)
    band_lo = np.floor(band_pos).astype(int)
    band_hi = np.minimum(band_lo + 1, N_SPECTRAL_BANDS - 1)
    frac = band_pos - band_lo                               # (H, W)

    color_lo = palette[band_lo]                              # (H, W, 3)
    color_hi = palette[band_hi]                              # (H, W, 3)
    base_color = color_lo + frac[:, :, np.newaxis] * (color_hi - color_lo)

    # Cache w_idx for this width (always the same)
    if width not in _WF_W_IDX_CACHE:
        _WF_W_IDX_CACHE[width] = np.broadcast_to(
            np.arange(width)[np.newaxis, :], (WAVEFORM_HEIGHT, width)
        )
    w_idx = _WF_W_IDX_CACHE[width]

    # Per-pixel spectral energy from the two neighbouring bands
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

    return pixel_colors, mask


def _apply_waveform_gradient(frame, height=250, max_darken=0.5):
    """Apply a vertical dark gradient to the bottom of frame for waveform readability."""
    fh, fw = frame.shape[:2]
    y_start = max(0, fh - height)
    gradient = np.linspace(1.0, 1.0 - max_darken, fh - y_start).astype(np.float32)
    frame[y_start:] = (frame[y_start:].astype(np.float32) * gradient[:, np.newaxis, np.newaxis]).astype(np.uint8)


def _apply_waveform(frame, pixel_colors, mask, y_offset=WAVEFORM_Y):
    """Stamp pre-computed waveform data onto a frame region."""
    if pixel_colors is None:
        return
    region = frame[y_offset : y_offset + WAVEFORM_HEIGHT]
    mask_3d = mask[:, :, np.newaxis]
    region[:] = np.where(mask_3d, pixel_colors, region)


TITLE_RELOCATE_SEC = 20.0            # Seconds before title moves to corner
TITLE_CORNER_POS = (30, 24)          # Top-left corner position (x, y)
TITLE_CORNER_SCALE = 0.6             # Scale factor when in corner
TITLE_CROSSFADE_SEC = 1.5            # Crossfade between center and corner
TITLE_FADE_OUT_SEC = 2.0             # Fade out at end of track


def _hex_to_rgb(hex_color):
    """Convert hex color string to (R, G, B) tuple."""
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _render_text_rgba(text, font_path, font_size, color_rgb, stroke_rgb, stroke_width=1):
    """Render text to an RGBA numpy array using PIL. Returns (H, W, 4) uint8."""
    from PIL import ImageDraw, ImageFont
    font = ImageFont.truetype(font_path, font_size)
    # Measure text bounds with padding for stroke
    pad = stroke_width * 2 + 4
    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    w = bbox[2] - bbox[0] + pad * 2
    h = bbox[3] - bbox[1] + pad * 2
    # Render
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((pad - bbox[0], pad - bbox[1]), text, font=font,
              fill=(*color_rgb, 255), stroke_fill=(*stroke_rgb, 255),
              stroke_width=stroke_width)
    return np.array(img, dtype=np.uint8)


def _precompute_title_images(transitions, total_duration, video_width, theme=None):
    """Pre-render title text images for all tracks. Returns list of title dicts."""
    font = theme["font"] if theme else FONT_PATH
    title_color = _hex_to_rgb(theme["title_color"] if theme else RETRO_TITLE_COLOR)
    stroke_color = _hex_to_rgb(theme["title_stroke_color"] if theme else RETRO_TITLE_STROKE)
    font_size = theme["title_font_size"] if theme else TITLE_FONT_SIZE
    corner_font_size = max(14, int(font_size * TITLE_CORNER_SCALE))

    titles = []
    for i, t in enumerate(transitions):
        name = t["name"].upper()
        start = t["start_sec"]
        end = transitions[i + 1]["start_sec"] if i + 1 < len(transitions) else total_duration
        duration = end - start

        center_img = _render_text_rgba(name, font, font_size, title_color, stroke_color)
        corner_img = _render_text_rgba(name, font, corner_font_size, title_color, stroke_color)

        center_x = int((video_width - center_img.shape[1]) / 2)
        fade_out = min(TITLE_FADE_OUT_SEC, duration / 3)
        relocate_at = min(TITLE_RELOCATE_SEC, duration - fade_out - TITLE_CROSSFADE_SEC)

        titles.append({
            "start": start, "end": end, "duration": duration,
            "center_img": center_img, "corner_img": corner_img,
            "center_x": center_x, "relocate_at": relocate_at,
            "fade_out_start": end - fade_out - start,  # relative to track start
        })
    return titles


def _blend_title_onto_frame(frame_buf, title_img, x, y, opacity):
    """Alpha-blend a pre-rendered RGBA title image onto the frame buffer."""
    fh, fw = frame_buf.shape[:2]
    th, tw = title_img.shape[:2]

    # Clip to frame bounds
    src_x0 = max(0, -x)
    src_y0 = max(0, -y)
    dst_x0 = max(0, x)
    dst_y0 = max(0, y)
    dst_x1 = min(fw, x + tw)
    dst_y1 = min(fh, y + th)
    if dst_x1 <= dst_x0 or dst_y1 <= dst_y0:
        return
    src_x1 = src_x0 + (dst_x1 - dst_x0)
    src_y1 = src_y0 + (dst_y1 - dst_y0)

    rgb = title_img[src_y0:src_y1, src_x0:src_x1, :3]
    alpha = title_img[src_y0:src_y1, src_x0:src_x1, 3:4].astype(np.float32) * (opacity / 255.0)

    region = frame_buf[dst_y0:dst_y1, dst_x0:dst_x1]
    blended = region.astype(np.float32) * (1.0 - alpha) + rgb.astype(np.float32) * alpha
    region[:] = blended.astype(np.uint8)


def _draw_title(frame_buf, t, transitions, titles):
    """Draw the appropriate title text directly onto frame_buf for time t."""
    # Find current track
    idx = 0
    for i, tr in enumerate(transitions):
        if tr["start_sec"] <= t:
            idx = i
    title = titles[idx]
    local_t = t - title["start"]
    if local_t < 0 or local_t > title["duration"]:
        return

    # Glow pulse
    pulse = 1.0 + RETRO_TITLE_GLOW_AMPLITUDE * np.sin(
        2 * np.pi * local_t / RETRO_TITLE_GLOW_PERIOD)

    # Compute opacity phases
    center_opacity = 0.0
    corner_opacity = 0.0

    relocate = title["relocate_at"]
    fade_out_start = title["fade_out_start"]

    if local_t < RETRO_TITLE_SLIDE_SEC:
        # Slide-in phase: center only
        center_opacity = 1.0
    elif local_t < relocate:
        # Center hold
        center_opacity = 1.0
    elif local_t < relocate + TITLE_CROSSFADE_SEC:
        # Crossfade: center fading out, corner fading in
        progress = (local_t - relocate) / TITLE_CROSSFADE_SEC
        center_opacity = 1.0 - progress
        corner_opacity = progress
    else:
        # Corner only
        corner_opacity = 1.0

    # Fade out at end of track
    if local_t > fade_out_start:
        fade = 1.0 - (local_t - fade_out_start) / (title["duration"] - fade_out_start)
        fade = max(0.0, fade)
        center_opacity *= fade
        corner_opacity *= fade

    # Apply glow pulse
    center_opacity = min(1.0, center_opacity * pulse)
    corner_opacity = min(1.0, corner_opacity * pulse)

    # Draw center title (with slide-in animation)
    if center_opacity > 0.01:
        cx = title["center_x"]
        if local_t < RETRO_TITLE_SLIDE_SEC:
            progress = local_t / RETRO_TITLE_SLIDE_SEC
            eased = 1 - (1 - progress) ** 3
            start_x = -title["center_img"].shape[1]
            cx = int(start_x + (title["center_x"] - start_x) * eased)
        _blend_title_onto_frame(frame_buf, title["center_img"],
                                cx, TITLE_Y, center_opacity * 255)

    # Draw corner title
    if corner_opacity > 0.01:
        _blend_title_onto_frame(frame_buf, title["corner_img"],
                                TITLE_CORNER_POS[0], TITLE_CORNER_POS[1],
                                corner_opacity * 255)


# === Artwork animation helpers ===

def _cover_crop(img, target_w, target_h):
    """Scale image to cover target dimensions, then center-crop. No borders."""
    w, h = img.size
    scale = max(target_w / w, target_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def _ken_burns_frame(image, t, duration):
    """Apply ping-pong zoom and subtle pan to create a Ken Burns effect.

    Args:
        image: numpy array or PIL Image — source artwork (ideally 110% of target).
        t: current time in seconds.
        duration: total loop duration in seconds.
    Returns:
        numpy array (1080, 1920, 3) uint8.
    """
    tgt_w, tgt_h = VIDEO_SIZE
    # Ensure source is a PIL Image for potential cover-crop
    if isinstance(image, np.ndarray):
        image = Image.fromarray(image)
    w, h = image.size
    # Guarantee source covers target with headroom for zoom/pan
    min_w, min_h = int(tgt_w * 1.1), int(tgt_h * 1.1)
    if w < min_w or h < min_h:
        image = _cover_crop(image, min_w, min_h)
    image = np.array(image)
    h, w = image.shape[:2]

    # Ping-pong zoom: 1.0 → 1.05 → 1.0 over duration
    scale = 1.0 + 0.05 * np.sin(np.pi * t / duration)
    # Subtle pan offsets (pixels)
    offset_x = 5 * np.sin(2 * np.pi * t / duration)
    offset_y = 3 * np.cos(2 * np.pi * t / duration)

    # Crop region size (inverse of zoom)
    crop_w = int(tgt_w / scale)
    crop_h = int(tgt_h / scale)

    # Center + pan offset
    cx = w / 2 + offset_x
    cy = h / 2 + offset_y

    x1 = int(np.clip(cx - crop_w / 2, 0, w - crop_w))
    y1 = int(np.clip(cy - crop_h / 2, 0, h - crop_h))

    cropped = image[y1:y1 + crop_h, x1:x1 + crop_w]

    # Resize to target via PIL (high quality)
    pil_img = Image.fromarray(cropped)
    pil_img = pil_img.resize((tgt_w, tgt_h), Image.LANCZOS)
    return np.array(pil_img, dtype=np.uint8)


def _ambient_particles_overlay(frame, t):
    """Render soft floating dust/bokeh particles onto a frame.

    ~30 particles drifting slowly upward with warm color and low opacity.
    Deterministic: uses fixed seed + time for reproducibility.
    """
    h, w = frame.shape[:2]
    n_particles = 30
    result = frame.astype(np.float32)

    rng = np.random.RandomState(42)
    # Pre-generate base positions
    base_x = rng.uniform(0, w, n_particles)
    base_y = rng.uniform(0, h, n_particles)
    radii = rng.uniform(4, 8, n_particles)
    speeds = rng.uniform(8, 20, n_particles)  # px/s upward drift
    x_drift = rng.uniform(-5, 5, n_particles)  # slight horizontal drift

    color = np.array([255, 240, 200], dtype=np.float32)

    for i in range(n_particles):
        # Position wraps vertically for seamless loop
        px = (base_x[i] + x_drift[i] * t) % w
        py = (base_y[i] - speeds[i] * t) % h
        r = radii[i]
        opacity = rng.uniform(0.05, 0.10)

        # Bounding box
        y1 = max(0, int(py - r))
        y2 = min(h, int(py + r) + 1)
        x1 = max(0, int(px - r))
        x2 = min(w, int(px + r) + 1)

        if y2 <= y1 or x2 <= x1:
            continue

        # Create soft circular mask
        yy, xx = np.mgrid[y1:y2, x1:x2]
        dist = np.sqrt((xx - px) ** 2 + (yy - py) ** 2)
        mask = np.clip(1.0 - dist / r, 0, 1) * opacity  # soft falloff

        # Additive blend
        result[y1:y2, x1:x2] += mask[:, :, np.newaxis] * color[np.newaxis, np.newaxis, :]

    return np.clip(result, 0, 255).astype(np.uint8)


def _light_flicker(frame, t):
    """Apply subtle +-3% brightness sine modulation with 4-second period."""
    factor = 1.0 + 0.03 * np.sin(2 * np.pi * t / 4.0)
    return np.clip(frame.astype(np.float32) * factor, 0, 255).astype(np.uint8)


def _generate_video_loop_from_artwork(artwork_path, output_path, duration=10, fps=24):
    """Compose Ken Burns + particles + flicker into a loopable MP4 clip.

    Args:
        artwork_path: path to source artwork image (PNG).
        output_path: path for the output MP4 file.
        duration: loop duration in seconds (default 10).
        fps: frames per second (default 24).
    """
    if os.path.exists(output_path):
        print(f"  Video loop cached: {output_path}")
        return

    img = Image.open(artwork_path).convert("RGB")
    # Ensure source is large enough for Ken Burns crop headroom
    src_w = int(VIDEO_SIZE[0] * 1.1)
    src_h = int(VIDEO_SIZE[1] * 1.1)
    img = img.resize((src_w, src_h), Image.LANCZOS)
    img_arr = np.array(img, dtype=np.uint8)

    def make_frame(t):
        frame = _ken_burns_frame(img_arr, t, duration)
        frame = _light_flicker(frame, t)
        frame = _ambient_particles_overlay(frame, t)
        return frame

    clip = VideoClip(make_frame, duration=duration).with_fps(fps)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    clip.write_videofile(
        output_path,
        codec="libx264",
        audio=False,
        logger=None,
    )
    clip.close()
    print(f"  Video loop created: {output_path}")


# === Video background support ===

def _predecode_video_loop(path, crossfade_sec, target_size, fps, darken=VIDEO_BG_DARKEN):
    """Load a video clip, scale/crop to target_size, create a seamless loop.

    Returns (frames_array, loop_duration) where frames_array is
    a uint8 ndarray of shape (N, H, W, 3) with darkening pre-applied.
    """
    clip = VideoFileClip(path, audio=False)
    src_w, src_h = clip.size
    tgt_w, tgt_h = target_size

    # Scale to cover target (maintain aspect ratio), then center-crop
    scale = max(tgt_w / src_w, tgt_h / src_h)
    clip = clip.resized(scale)
    cw, ch = clip.size
    if cw != tgt_w or ch != tgt_h:
        clip = clip.cropped(
            x_center=cw / 2, y_center=ch / 2,
            width=tgt_w, height=tgt_h,
        )

    # Decode all frames
    n_total = int(clip.duration * fps)
    all_frames = np.empty((n_total, tgt_h, tgt_w, 3), dtype=np.uint8)
    for i in range(n_total):
        all_frames[i] = clip.get_frame(i / fps)
    clip.close()

    # Seamless loop via crossfade blending
    n_xfade = int(crossfade_sec * fps)
    n_xfade = min(n_xfade, n_total // 2)
    n_loop = n_total - n_xfade

    loop_frames = np.empty((n_loop, tgt_h, tgt_w, 3), dtype=np.uint8)

    # Crossfade region (first n_xfade frames): blend end into start
    # At j=0: fully from tail → at j=n_xfade-1: fully from head
    # Loop point (last frame → first frame) = consecutive original frames → seamless
    for j in range(n_xfade):
        alpha = j / n_xfade
        loop_frames[j] = (
            (1 - alpha) * all_frames[n_loop + j].astype(np.float32)
            + alpha * all_frames[j].astype(np.float32)
        ).astype(np.uint8)

    # Body: unmodified frames after the crossfade region
    loop_frames[n_xfade:] = all_frames[n_xfade:n_loop]

    # Pre-apply darkening
    loop_frames = (loop_frames.astype(np.float32) * darken).astype(np.uint8)

    del all_frames
    duration = n_loop / fps
    return loop_frames, duration


def _get_bg_cache_path(video_path, darken, cache_dir):
    """Return deterministic .npy cache path based on source file identity + darken."""
    st = os.stat(video_path)
    basename = os.path.splitext(os.path.basename(video_path))[0]
    key = f"{basename}_{int(st.st_mtime)}_{st.st_size}_{darken:.4f}"
    return os.path.join(cache_dir, f"{key}.npy")


class _LazyVideoLoops:
    """Lazy-loading video loop manager with LRU eviction.

    Keeps at most `max_resident` decoded loops in memory at once.
    For small counts (≤ max_resident), all loops stay resident.
    For large counts, evicts least-recently-used loops on demand.
    """

    def __init__(self, video_paths, darken, max_resident=4):
        self._paths = video_paths
        self._darken = darken
        self._max_resident = max_resident
        # idx → (frames, duration); None means not loaded
        self._cache = {}
        # LRU order: most recent at end
        self._lru = []

    def __len__(self):
        return len(self._paths)

    def __getitem__(self, idx):
        """Return (frames, duration) for loop idx, decoding on demand."""
        if idx in self._cache:
            # Move to end of LRU
            if idx in self._lru:
                self._lru.remove(idx)
            self._lru.append(idx)
            return self._cache[idx]

        # Evict if at capacity
        while len(self._cache) >= self._max_resident and self._lru:
            evict_idx = self._lru.pop(0)
            evicted = self._cache.pop(evict_idx, None)
            if evicted is not None:
                name = os.path.basename(self._paths[evict_idx])
                print(f"    [bg] evicted {name}")
                del evicted

        # Decode
        path = self._paths[idx]
        name = os.path.basename(path)
        print(f"    [bg] decoding {name}...")
        frames, dur = _predecode_video_loop(
            path, VIDEO_BG_LOOP_CROSSFADE, VIDEO_SIZE, VIDEO_FPS,
            darken=self._darken,
        )
        self._cache[idx] = (frames, dur)
        self._lru.append(idx)
        return (frames, dur)


def _load_video_backgrounds(video_bg_list, session_dir, darken=VIDEO_BG_DARKEN,
                            cache_dir=None):
    """Load video backgrounds, using disk mmap cache or lazy in-memory LRU.

    - When cache_dir is set and there are few videos (≤8): decode once, save as
      .npy files, and memory-map them. Peak RAM ≈ 1 frame per video (OS pages on demand).
    - When there are many videos or no cache_dir: return a _LazyVideoLoops object
      that decodes on demand and keeps at most 4 loops resident.
    """
    MAX_MMAP_VIDEOS = 8

    # Resolve full paths
    full_paths = [os.path.join(session_dir, vpath) for vpath in video_bg_list]
    n_videos = len(full_paths)

    # Use mmap for small sets with cache_dir
    if cache_dir and n_videos <= MAX_MMAP_VIDEOS:
        print(f"\nPre-decoding {n_videos} video backgrounds (disk cache)...")
        os.makedirs(cache_dir, exist_ok=True)

        loops = []
        for full_path in full_paths:
            name = os.path.basename(full_path)
            cache_path = _get_bg_cache_path(full_path, darken, cache_dir)
            meta_path = cache_path + ".json"

            if os.path.exists(cache_path) and os.path.exists(meta_path):
                with open(meta_path) as f:
                    meta = json.load(f)
                frames = np.load(cache_path, mmap_mode='r')
                dur = meta["duration"]
                mb = frames.nbytes / (1024 * 1024)
                print(f"  {name} (cached) {len(frames)} frames, {dur:.1f}s loop, {mb:.0f} MB")
            else:
                print(f"  {name} (decoding)...")
                frames, dur = _predecode_video_loop(
                    full_path, VIDEO_BG_LOOP_CROSSFADE, VIDEO_SIZE, VIDEO_FPS,
                    darken=darken,
                )
                mb = frames.nbytes / (1024 * 1024)
                print(f"    {len(frames)} frames, {dur:.1f}s loop, {mb:.0f} MB")
                np.save(cache_path, frames)
                with open(meta_path, 'w') as f:
                    json.dump({"duration": dur}, f)
                print(f"    Saved to cache: {os.path.basename(cache_path)}")
                del frames
                frames = np.load(cache_path, mmap_mode='r')

            loops.append((frames, dur))

        total_mb = sum(f.nbytes for f, _ in loops) / (1024 * 1024)
        print(f"  Total video background size: {total_mb:.0f} MB (memory-mapped)")
        return loops

    # Lazy LRU for large sets — decode on demand during rendering
    print(f"\nVideo backgrounds: {n_videos} loops (lazy LRU, max 4 resident)")
    return _LazyVideoLoops(full_paths, darken, max_resident=4)


def _get_video_bg_frame(t, transitions, video_loops, frame_buf, blend_buf):
    """Write looped video background for time t into frame_buf.

    Cycles through video clips per track, crossfades at transitions.
    """
    n_loops = len(video_loops)

    current_idx = 0
    for i, tr in enumerate(transitions):
        if t >= tr["start_sec"]:
            current_idx = i

    vid_idx = current_idx % n_loops
    frames, dur = video_loops[vid_idx]
    frame_i = int((t % dur) * VIDEO_FPS) % len(frames)

    # Check for crossfade with next track's video
    if current_idx + 1 < len(transitions):
        next_start = transitions[current_idx + 1]["start_sec"]
        xfade_start = next_start - CROSSFADE_SEC
        if xfade_start <= t < next_start:
            next_vid_idx = (current_idx + 1) % n_loops
            if next_vid_idx != vid_idx:
                alpha = int((t - xfade_start) / CROSSFADE_SEC * 256)
                next_frames, next_dur = video_loops[next_vid_idx]
                next_i = int((t % next_dur) * VIDEO_FPS) % len(next_frames)

                np.add(
                    np.multiply(frames[frame_i], 256 - alpha,
                                dtype=np.uint16, out=blend_buf),
                    np.multiply(next_frames[next_i], alpha, dtype=np.uint16),
                    out=blend_buf,
                )
                np.right_shift(blend_buf, 8, out=blend_buf)
                frame_buf[:] = blend_buf.astype(np.uint8)
                return

    np.copyto(frame_buf, frames[frame_i])


# === Artwork generation ===

def _generate_artwork(track_name, artwork_dir, theme=None):
    """Generate artwork for a track using DALL-E 3, with caching.

    Uses theme["artwork_style"] to select prompt template from ARTWORK_PROMPTS.
    Falls back to "abstract" style when no theme is provided.
    """
    os.makedirs(artwork_dir, exist_ok=True)
    cache_path = os.path.join(artwork_dir, f"{track_name}.png")

    if os.path.exists(cache_path):
        print(f"  Artwork cached: {cache_path}")
        return cache_path

    if not os.environ.get("OPENAI_API_KEY"):
        print(f"  Skipping artwork for '{track_name}' (no API key)")
        return None

    # Select prompt template based on theme artwork_style
    style = "abstract"
    if theme:
        style = theme.get("artwork_style", "abstract")
    template = ARTWORK_PROMPTS.get(style, ARTWORK_PROMPTS["abstract"])
    prompt = template.format(track_name=track_name)

    print(f"  Generating artwork for '{track_name}' (style: {style})...")
    try:
        client = OpenAI()
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=ARTWORK_API_SIZE,
            quality="standard",
            response_format="b64_json",
            n=1,
        )
        image_data = base64.b64decode(response.data[0].b64_json)
        img = Image.open(io.BytesIO(image_data))
        img = _cover_crop(img, VIDEO_SIZE[0], VIDEO_SIZE[1])
        img.save(cache_path)
        print(f"  Saved: {cache_path}")
        return cache_path
    except Exception as e:
        print(f"  Artwork generation failed: {e}")
        return None


def _load_artwork_images(transitions, artwork_dir, bg_color=None):
    """Load, blur, and darken artwork images for all tracks.

    Images are cover-cropped to 110% of VIDEO_SIZE to provide headroom
    for Ken Burns zoom/pan, then blurred and darkened.
    """
    fallback_color = tuple(bg_color) if bg_color else BG_COLOR
    kb_w, kb_h = int(VIDEO_SIZE[0] * 1.1), int(VIDEO_SIZE[1] * 1.1)
    images = []
    for t in transitions:
        path = os.path.join(artwork_dir, f"{t['name']}.png")
        if not os.path.exists(path):
            images.append(
                np.full((kb_h, kb_w, 3), fallback_color, dtype=np.uint8)
            )
            continue
        img = Image.open(path).convert("RGB")
        img = _cover_crop(img, kb_w, kb_h)
        img = img.filter(ImageFilter.GaussianBlur(radius=ARTWORK_BLUR_RADIUS))
        arr = np.array(img, dtype=np.float32) * ARTWORK_DARKEN_FACTOR
        images.append(arr.astype(np.uint8))
    return images


def _get_artwork_frame(t, transitions, artwork_images, frame_buf, blend_buf):
    """Write artwork background for time t into pre-allocated frame_buf.

    Artwork images may be oversized (110%) to provide Ken Burns headroom.
    Each frame is extracted via _ken_burns_frame which handles zoom/pan
    and outputs exactly VIDEO_SIZE.
    """
    current_idx = 0
    for i, tr in enumerate(transitions):
        if t >= tr["start_sec"]:
            current_idx = i

    # Compute segment-local time and duration for Ken Burns animation
    seg_start = transitions[current_idx]["start_sec"]
    if current_idx + 1 < len(transitions):
        seg_end = transitions[current_idx + 1]["start_sec"]
    else:
        seg_end = seg_start + 300  # fallback for last segment
    seg_duration = seg_end - seg_start
    seg_t = t - seg_start

    current_bg = _ken_burns_frame(artwork_images[current_idx], seg_t, seg_duration)

    # Crossfade blending during transition window
    if current_idx + 1 < len(transitions):
        next_start = transitions[current_idx + 1]["start_sec"]
        crossfade_start = next_start - CROSSFADE_SEC
        if crossfade_start <= t < next_start:
            alpha = int((t - crossfade_start) / CROSSFADE_SEC * 256)
            # Ken Burns the next segment too
            next_seg_start = next_start
            if current_idx + 2 < len(transitions):
                next_seg_end = transitions[current_idx + 2]["start_sec"]
            else:
                next_seg_end = next_seg_start + 300
            next_seg_t = t - next_seg_start
            next_bg = _ken_burns_frame(
                artwork_images[current_idx + 1], max(0, next_seg_t),
                next_seg_end - next_seg_start,
            )
            # Integer blend: avoids two 25MB float32 conversions
            np.add(
                np.multiply(current_bg, 256 - alpha, dtype=np.uint16, out=blend_buf),
                np.multiply(next_bg, alpha, dtype=np.uint16),
                out=blend_buf,
            )
            np.right_shift(blend_buf, 8, out=blend_buf)
            frame_buf[:] = blend_buf.astype(np.uint8)
            return

    np.copyto(frame_buf, current_bg)


# === Particle system ===

def _init_particles(count):
    """Initialize particle properties with seeded RNG for determinism."""
    rng = np.random.RandomState(42)
    return {
        "x0": rng.uniform(0, VIDEO_SIZE[0], count),
        "y0": rng.uniform(0, VIDEO_SIZE[1], count),
        "vx": rng.uniform(-PARTICLE_DRIFT_SPEED, PARTICLE_DRIFT_SPEED, count),
        "vy": rng.uniform(-PARTICLE_DRIFT_SPEED * 0.5, PARTICLE_DRIFT_SPEED * 0.5, count),
        "radii": rng.randint(PARTICLE_MIN_RADIUS, PARTICLE_MAX_RADIUS + 1, count),
        "phase": rng.uniform(0, 2 * np.pi, count),
    }


def _precompute_particle_stamps(min_r, max_r):
    """Pre-compute soft circle alpha masks for each integer radius."""
    stamps = {}
    for r in range(min_r, max_r + 1):
        y, x = np.ogrid[-r : r + 1, -r : r + 1]
        dist = np.sqrt(x * x + y * y).astype(np.float32)
        stamp = np.clip(1.0 - dist / r, 0.0, 1.0) ** 1.5
        stamps[r] = stamp
    return stamps


def _precompute_beat_scatter(beat_times, count):
    """Pre-compute scatter offsets for each beat (avoids RandomState per frame)."""
    scatter_table = {}
    for i, bt in enumerate(beat_times):
        seed = int(bt * 1000) & 0x7FFFFFFF
        rng = np.random.RandomState(seed)
        scatter_table[i] = (
            rng.uniform(-10, 10, count),
            rng.uniform(-10, 10, count),
        )
    return scatter_table


def _compute_particles(t, particles, beat_times, scatter_table):
    """Compute particle positions and brightness at time t (pure function)."""
    count = len(particles["x0"])

    # Position: drift + sine oscillation, wrapped to screen
    x = (
        particles["x0"]
        + particles["vx"] * t
        + 8.0 * np.sin(particles["phase"] + 0.3 * t)
    ) % VIDEO_SIZE[0]
    y = (
        particles["y0"]
        + particles["vy"] * t
        + 5.0 * np.cos(particles["phase"] + 0.2 * t)
    ) % VIDEO_SIZE[1]

    # Beat pulse
    brightness = np.full(count, PARTICLE_BASE_ALPHA)

    if len(beat_times) > 0:
        idx = np.searchsorted(beat_times, t, side="right") - 1
        if idx >= 0:
            dt = t - beat_times[idx]
            if dt < PARTICLE_BEAT_DECAY:
                pulse = 1.0 - (dt / PARTICLE_BEAT_DECAY) ** 2
                brightness = np.full(
                    count,
                    PARTICLE_BASE_ALPHA
                    + (PARTICLE_BEAT_ALPHA - PARTICLE_BASE_ALPHA) * pulse,
                )
                # Beat scatter in first 150ms
                if dt < 0.15:
                    scatter_x, scatter_y = scatter_table[idx]
                    scatter_strength = 1.0 - dt / 0.15
                    x = (x + scatter_x * scatter_strength) % VIDEO_SIZE[0]
                    y = (y + scatter_y * scatter_strength) % VIDEO_SIZE[1]

    return x, y, particles["radii"], brightness


def _draw_particles(frame, x, y, radii, brightness, stamps, particle_color=None):
    """Draw particles onto frame using additive blending (single float pass)."""
    h, w = frame.shape[:2]
    color_arr = np.array(particle_color or PARTICLE_COLOR, dtype=np.float32)

    # Convert once to float32, accumulate all particles, clip once
    frame_f = frame.astype(np.float32)

    for i in range(len(x)):
        px, py = int(x[i]), int(y[i])
        r = int(radii[i])
        stamp = stamps.get(r)
        if stamp is None:
            continue

        sr = stamp.shape[0] // 2

        # Compute source and dest bounds with clipping
        x1, x2 = px - sr, px + sr + 1
        y1, y2 = py - sr, py + sr + 1
        sx1, sy1 = 0, 0
        sx2, sy2 = stamp.shape[1], stamp.shape[0]

        if x1 < 0:
            sx1 -= x1
            x1 = 0
        if y1 < 0:
            sy1 -= y1
            y1 = 0
        if x2 > w:
            sx2 -= x2 - w
            x2 = w
        if y2 > h:
            sy2 -= y2 - h
            y2 = h

        if x1 >= x2 or y1 >= y2:
            continue

        alpha = stamp[sy1:sy2, sx1:sx2] * brightness[i]
        frame_f[y1:y2, x1:x2] += alpha[:, :, np.newaxis] * color_arr

    np.clip(frame_f, 0, 255, out=frame_f)
    frame[:] = frame_f.astype(np.uint8)


def generate_video(audio_path, transitions, output_path, artwork_dir,
                    session_config=None, session_dir=None):
    """Compose a video: bg (artwork or video loops) + particles + glow waveform + titles."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Resolve theme (merges session overrides with defaults)
    theme = _get_session_theme(session_config)

    audio = AudioFileClip(audio_path)
    total_duration = audio.duration
    width = VIDEO_SIZE[0]

    # Pre-compute audio data (envelope, spectral bands, beats)
    envelope, env_sr, band_energies, beat_times = _precompute_audio_data(audio_path)

    # Determine background mode: video loops or static artwork
    video_bg_list = session_config.get("video_backgrounds") if session_config else None
    video_loops = None
    artwork_images = None

    if video_bg_list and session_dir:
        bg_cache_dir = os.path.join(os.path.dirname(output_path), "bg_cache")
        video_loops = _load_video_backgrounds(
            video_bg_list, session_dir, darken=theme["bg_darken"],
            cache_dir=bg_cache_dir)
    else:
        # Generate and load artwork backgrounds (deduplicate by display name)
        print("\nGenerating artwork...")
        generated_names = set()
        for t in transitions:
            if t["name"] not in generated_names:
                _generate_artwork(t["name"], artwork_dir=artwork_dir, theme=theme)
                generated_names.add(t["name"])

        # Auto-generate video loops for realistic artwork style
        if theme["artwork_style"] == "realistic" and not video_bg_list:
            loops_dir = os.path.join(artwork_dir, "loops")
            os.makedirs(loops_dir, exist_ok=True)
            print("\nGenerating video loops from artwork...")
            loop_paths = []
            for name in generated_names:
                artwork_path = os.path.join(artwork_dir, f"{name}.png")
                loop_path = os.path.join(loops_dir, f"{name}.mp4")
                if os.path.exists(artwork_path):
                    _generate_video_loop_from_artwork(artwork_path, loop_path)
                    loop_paths.append(loop_path)
            if loop_paths:
                bg_cache_dir = os.path.join(os.path.dirname(output_path), "bg_cache")
                video_loops = _load_video_backgrounds(
                    loop_paths, ".", darken=theme["bg_darken"],
                    cache_dir=bg_cache_dir)

        if not video_loops:
            print("Loading artwork images...")
            artwork_images = _load_artwork_images(
                transitions, artwork_dir=artwork_dir, bg_color=theme["bg_color"])

    # Initialize particle system
    particles = _init_particles(PARTICLE_COUNT)
    stamps = _precompute_particle_stamps(PARTICLE_MIN_RADIUS, PARTICLE_MAX_RADIUS)
    scatter_table = _precompute_beat_scatter(beat_times, PARTICLE_COUNT)

    # Build waveform palette from theme (monochromatic gradient from waveform_color)
    wf_color = np.array(theme["waveform_color"], dtype=np.float32)
    if np.array_equal(wf_color.astype(int), SPECTRAL_PALETTE[0].astype(int)):
        wf_palette = SPECTRAL_PALETTE  # default: use full spectral palette
    else:
        # Generate warm monochromatic palette: brighter at center, dimmer at edge
        brightness_ramp = np.linspace(1.0, 0.5, N_SPECTRAL_BANDS)
        wf_palette = np.array(
            [wf_color * b for b in brightness_ramp], dtype=np.float32)

    # --- Pre-allocate reusable buffers (avoids per-frame allocation) ---
    frame_buf = np.empty((VIDEO_SIZE[1], VIDEO_SIZE[0], 3), dtype=np.uint8)
    blend_buf = np.empty((VIDEO_SIZE[1], VIDEO_SIZE[0], 3), dtype=np.uint16)

    # Glow: half-resolution for ~8x faster blur
    pad = 2 * GLOW_SIGMA
    glow_h = WAVEFORM_HEIGHT + 2 * pad
    glow_half_h = glow_h // 2
    glow_half_w = width // 2
    glow_buf = np.zeros((glow_h, width, 3), dtype=np.uint8)
    glow_half_f = np.empty((glow_half_h, glow_half_w, 3), dtype=np.float32)

    # Pre-compute glow region mapping (constant across frames)
    frame_y_start = max(0, WAVEFORM_Y - pad)
    frame_y_end = min(VIDEO_SIZE[1], WAVEFORM_Y + WAVEFORM_HEIGHT + pad)
    buf_y_start = frame_y_start - (WAVEFORM_Y - pad)
    buf_y_end = buf_y_start + (frame_y_end - frame_y_start)
    glow_region_f = np.empty((frame_y_end - frame_y_start, width, 3), dtype=np.float32)

    def make_frame(t):
        # 1. Background (video loops or artwork)
        if video_loops:
            _get_video_bg_frame(t, transitions, video_loops, frame_buf, blend_buf)
        else:
            _get_artwork_frame(t, transitions, artwork_images, frame_buf, blend_buf)

        # 2. Particles (additive blend)
        px, py, pradii, pbrightness = _compute_particles(
            t, particles, beat_times, scatter_table
        )
        _draw_particles(frame_buf, px, py, pradii, pbrightness, stamps,
                        particle_color=theme["particle_color"])

        # 2.5 Waveform region gradient for readability
        _apply_waveform_gradient(frame_buf)

        # 3. Compute waveform data ONCE, apply twice
        pixel_colors, mask = _compute_waveform_data(
            envelope, env_sr, t, band_energies, width, palette=wf_palette
        )

        # 3a. Waveform glow (half-res blur for speed)
        glow_buf[:] = 0
        _apply_waveform(glow_buf, pixel_colors, mask, y_offset=pad)

        # Downsample -> blur at half sigma -> upsample
        glow_half_f[:] = glow_buf[::2, ::2]  # implicit uint8->float32
        glow_blurred_half = gaussian_filter(
            glow_half_f, sigma=(GLOW_SIGMA // 2, GLOW_SIGMA // 2, 0)
        )
        glow_blurred_half *= GLOW_INTENSITY
        # Nearest-neighbour upsample via repeat
        glow_full = np.repeat(np.repeat(glow_blurred_half, 2, axis=0), 2, axis=1)

        # Additive blend glow into frame region (reuse pre-allocated buffer)
        np.copyto(
            glow_region_f,
            frame_buf[frame_y_start:frame_y_end],
            casting="unsafe",
        )
        np.add(glow_region_f, glow_full[buf_y_start:buf_y_end], out=glow_region_f)
        np.clip(glow_region_f, 0, 255, out=glow_region_f)
        frame_buf[frame_y_start:frame_y_end] = glow_region_f.astype(np.uint8)

        # 4. Sharp waveform on top (overwrite)
        _apply_waveform(frame_buf, pixel_colors, mask)

        # 5. Title text (direct numpy blend — no MoviePy compositing)
        _draw_title(frame_buf, t, transitions, titles)

        return frame_buf

    # Pre-render title images for all tracks
    titles = _precompute_title_images(transitions, total_duration, width, theme=theme)

    bg = VideoClip(make_frame, duration=total_duration)
    video = bg.with_audio(audio)

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

def _parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="Deep Session Generator")
    parser.add_argument("session", nargs="?", default=None,
                        help="Session number or path")
    parser.add_argument("--short", action="store_true",
                        help="Generate a 20-second YouTube Short instead of full video")
    return parser.parse_args()


def main():
    print("=== Deep Session Generator ===\n")

    args = _parse_args()

    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        print("Warning: OPENAI_API_KEY not set. Artwork generation will be skipped.\n")

    # Session resolution
    session_dir, session_config = resolve_session(args.session)
    session_name = session_config["name"] if session_config else os.path.basename(session_dir)
    print(f"Session: {session_name}")
    print(f"Tracks:  {session_dir}\n")

    # Per-session paths
    output_dir, artwork_dir, audio_path, video_path = get_output_paths(session_dir)

    # Load and analyze tracks
    track_entries = load_session_tracks(session_dir, session_config)
    use_playlist_order = session_config is not None
    target_duration = None if use_playlist_order else TARGET_DURATION_SEC
    tracks = analyze_tracks(track_entries, use_playlist_order=use_playlist_order)

    short_path = os.path.join(output_dir, "short.mp4")

    if args.short:
        # --- YouTube Short only ---
        if not os.path.exists(audio_path):
            print(f"Error: Mix audio not found at {audio_path}")
            print("Run the full pipeline first: python main.py <session_number>")
            sys.exit(1)

        _mix, transitions = build_mix(tracks, target_duration_sec=target_duration)
        generate_short(session_dir, session_config, transitions, audio_path,
                       artwork_dir, short_path)
    else:
        # --- Full pipeline (includes short) ---
        mix, transitions = build_mix(tracks, target_duration_sec=target_duration)
        export_mix(mix, audio_path)

        generate_video(audio_path, transitions, video_path, artwork_dir=artwork_dir,
                       session_config=session_config, session_dir=session_dir)

        generate_short(session_dir, session_config, transitions, audio_path,
                       artwork_dir, short_path)


if __name__ == "__main__":
    main()
