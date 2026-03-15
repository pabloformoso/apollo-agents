"""Quick experiment: seamless video loop over session 3 audio."""

import numpy as np
from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    VideoFileClip,
    concatenate_videoclips,
    vfx,
)

# --- Config ---
VIDEO_SRC = "./vids/Cyborg_and_Cyberpunk_Video_Generated.mp4"
AUDIO_SRC = "./tracks/session 3/Akira Warmup.wav"
OUTPUT = "./output/session 3 v2/test_loop.mp4"
TARGET_SIZE = (1920, 1080)
TARGET_FPS = 24
AUDIO_DURATION = 60  # seconds of audio to use
LOOP_CROSSFADE = 1.0  # seconds of crossfade for seamless loop


def make_seamless_loop(clip, crossfade_sec):
    """Create a seamless loop by crossfading the tail back into the head."""
    dur = clip.duration
    if crossfade_sec >= dur / 2:
        crossfade_sec = dur / 4

    # Body: everything except the last crossfade_sec
    body = clip.subclipped(0, dur - crossfade_sec)
    # Tail: last crossfade_sec, fading out
    tail = clip.subclipped(dur - crossfade_sec, dur).with_effects(
        [vfx.CrossFadeOut(crossfade_sec)]
    )
    # Head: first crossfade_sec, fading in
    head = clip.subclipped(0, crossfade_sec).with_effects(
        [vfx.CrossFadeIn(crossfade_sec)]
    )

    # Composite: tail overlaps with head at the loop point
    # Result is body + blended transition
    loop_clip = concatenate_videoclips([body], method="compose")

    # Overlay the tail+head blend at the end
    tail_start = body.duration - crossfade_sec
    tail = tail.with_start(tail_start)
    head = head.with_start(tail_start)
    loop_clip = CompositeVideoClip(
        [loop_clip, tail, head],
        size=clip.size,
    ).with_duration(body.duration)

    return loop_clip


def main():
    print("Loading video clip...")
    vid = VideoFileClip(VIDEO_SRC, audio=False)
    print(f"  Source: {vid.size[0]}x{vid.size[1]}, {vid.duration:.1f}s")

    # Create seamless loop unit
    print(f"Creating seamless loop (crossfade={LOOP_CROSSFADE}s)...")
    loop_unit = make_seamless_loop(vid, LOOP_CROSSFADE)
    unit_dur = loop_unit.duration
    print(f"  Loop unit: {unit_dur:.1f}s")

    # Repeat to cover audio duration
    n_loops = int(np.ceil(AUDIO_DURATION / unit_dur)) + 1
    print(f"  Repeating {n_loops}x to cover {AUDIO_DURATION}s...")
    loops = [loop_unit.with_start(i * unit_dur) for i in range(n_loops)]
    looped = CompositeVideoClip(loops, size=vid.size).with_duration(AUDIO_DURATION)

    # Upscale to 1080p
    if vid.size != TARGET_SIZE:
        print(f"  Upscaling {vid.size[0]}x{vid.size[1]} -> {TARGET_SIZE[0]}x{TARGET_SIZE[1]}")
        looped = looped.resized(TARGET_SIZE)

    # Load audio (first 60s)
    print(f"Loading audio ({AUDIO_DURATION}s)...")
    audio = AudioFileClip(AUDIO_SRC).subclipped(0, AUDIO_DURATION)
    looped = looped.with_audio(audio)

    # Render
    print(f"Rendering to {OUTPUT}...")
    looped.write_videofile(
        OUTPUT,
        fps=TARGET_FPS,
        codec="libx264",
        audio_codec="aac",
        audio_bitrate="320k",
        preset="medium",
        logger="bar",
    )
    print("Done!")


if __name__ == "__main__":
    main()
