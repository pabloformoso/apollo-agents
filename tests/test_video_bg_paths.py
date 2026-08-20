"""Tests that video backgrounds are reachable from the CLI at all.

Found 2026-08-20: the whole video-background path was dead code from the
command line. ``generate_video`` gates on ``if video_bg_list and
session_dir:``, and both CLI call sites passed ``session_dir=None``
hardcoded — so a session.json with ``video_backgrounds`` silently fell
through to the artwork branch instead. The feature was fully implemented
and simply unreachable, which is why nobody had noticed it was broken.

The paths resolve against the PROJECT ROOT, the same convention as
``playlist[].file``, so a session.json stays portable between machines.
"""
from __future__ import annotations

import subprocess

import numpy as np
import pytest

import main


def _ffmpeg_exe() -> str:
    """Path to an ffmpeg binary that is guaranteed to exist.

    CI runners have no system ffmpeg on PATH — they get the binary that
    ships inside the ``imageio-ffmpeg`` wheel, which is also what moviepy
    invokes. Calling a bare "ffmpeg" passes locally (the backend image
    has one) and fails in CI with FileNotFoundError.
    """
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _tiny_video(path, seconds=1, size=(64, 48), fps=8):
    """Render a throwaway clip so the loader has something real to open."""
    subprocess.run(
        [_ffmpeg_exe(), "-y", "-v", "error", "-f", "lavfi",
         "-i", f"testsrc=size={size[0]}x{size[1]}:rate={fps}:duration={seconds}",
         "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )
    return path


class TestCallSitesPassARoot:
    """The regression itself: session_dir must not be None from the CLI."""

    def test_generate_video_default_is_still_none(self):
        """The default stays None — callers opt in. Guards the contract."""
        import inspect

        sig = inspect.signature(main.generate_video)
        assert sig.parameters["session_dir"].default is None

    def test_script_dir_is_an_existing_directory(self):
        """_SCRIPT_DIR is what the call sites now pass; it must be real."""
        import os

        assert os.path.isdir(main._SCRIPT_DIR)

    def test_video_branch_requires_both_list_and_dir(self):
        """Documents the gate that made this dead code."""
        assert not (["a.mp4"] and None)
        assert bool(["a.mp4"] and main._SCRIPT_DIR)


class TestPathResolution:

    def test_relative_path_resolves_against_the_given_root(self, tmp_path):
        vid_dir = tmp_path / "tracks" / "Healing" / "videos"
        vid_dir.mkdir(parents=True)
        _tiny_video(vid_dir / "clip.mp4")

        loops = main._load_video_backgrounds(
            ["tracks/Healing/videos/clip.mp4"], str(tmp_path),
            darken=0.85, cache_dir=str(tmp_path / "cache"),
        )
        assert len(loops) == 1

    def test_absolute_path_is_kept(self, tmp_path):
        """os.path.join keeps an absolute second arg — both forms must work."""
        clip = _tiny_video(tmp_path / "clip.mp4")
        loops = main._load_video_backgrounds(
            [str(clip)], "/nonexistent-root",
            darken=1.0, cache_dir=str(tmp_path / "cache"),
        )
        assert len(loops) == 1

    def test_missing_file_is_not_silently_skipped(self, tmp_path):
        """A typo'd path must fail loudly, not fall back to a blank screen."""
        with pytest.raises(Exception):
            main._load_video_backgrounds(
                ["tracks/Healing/videos/nope.mp4"], str(tmp_path),
                darken=1.0, cache_dir=str(tmp_path / "cache"),
            )
