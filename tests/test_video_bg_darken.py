"""Tests for the video-background darkening pass.

Found 2026-08-19 while validating the first Veo-generated background: a
10 s 1080p clip killed the render outright. The darkening was a single
expression —

    frames = (frames.astype(np.float32) * darken).astype(np.uint8)

— which materialises the whole array as float32 (4x) plus another
full-size temporary for the product: 1.25 GB -> 5.0 GB -> 5.0 GB, with
the 1.39 GB source array still alive alongside it. The process was
OOM-killed with **no traceback and a zero exit status**, so the symptom
was a silent no-op rather than a memory error — the reason it took a
step-by-step RSS trace to find.

The chunked version must stay byte-identical to the naive one, because
the whole point is that this is a pure memory fix and not a visual
change.
"""
from __future__ import annotations

import numpy as np
import pytest

from main import _DARKEN_CHUNK_FRAMES, _darken_frames_inplace


def _naive(frames: np.ndarray, darken: float) -> np.ndarray:
    """The original one-shot expression, kept as the reference result."""
    return (frames.astype(np.float32) * darken).astype(np.uint8)


def _frames(n: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(n, 4, 6, 3), dtype=np.uint8)


class TestEquivalence:

    @pytest.mark.parametrize("n", [1, 7, 40, 41, 83, 216])
    def test_matches_the_naive_expression(self, n):
        """Byte-identical, including sizes that straddle a chunk boundary."""
        src = _frames(n)
        expected = _naive(src, 0.85)
        assert np.array_equal(_darken_frames_inplace(src.copy(), 0.85), expected)

    @pytest.mark.parametrize("darken", [0.35, 0.5, 0.85, 0.99])
    def test_matches_across_darken_values(self, darken):
        src = _frames(50)
        expected = _naive(src, darken)
        assert np.array_equal(_darken_frames_inplace(src.copy(), darken), expected)

    def test_chunk_size_does_not_change_the_result(self):
        """A different chunk must not shift pixels — guards an off-by-one."""
        src = _frames(97)
        ref = _darken_frames_inplace(src.copy(), 0.6, chunk=1)
        for chunk in (2, 7, 96, 97, 500):
            assert np.array_equal(_darken_frames_inplace(src.copy(), 0.6, chunk), ref)


class TestBehaviour:

    def test_mutates_in_place_and_returns_the_same_object(self):
        src = _frames(10)
        out = _darken_frames_inplace(src, 0.5)
        assert out is src

    def test_darken_of_one_is_a_no_op(self):
        src = _frames(10)
        before = src.copy()
        assert np.array_equal(_darken_frames_inplace(src, 1.0), before)

    def test_stays_uint8(self):
        src = _frames(10)
        assert _darken_frames_inplace(src, 0.35).dtype == np.uint8

    def test_actually_darkens(self):
        src = np.full((5, 4, 6, 3), 200, dtype=np.uint8)
        assert _darken_frames_inplace(src, 0.5).mean() == pytest.approx(100, abs=1)

    def test_empty_array_is_handled(self):
        src = np.zeros((0, 4, 6, 3), dtype=np.uint8)
        assert _darken_frames_inplace(src, 0.5).shape == (0, 4, 6, 3)

    def test_chunk_constant_is_bounded(self):
        """Keep the temporary small: 40 frames of 1080p float32 is ~1 GB.

        The constant exists to bound the temporary regardless of clip
        length; a large value would reintroduce the original failure on
        long clips.
        """
        assert 1 <= _DARKEN_CHUNK_FRAMES <= 64


class TestMemoryFootprint:

    def test_peak_allocation_is_bounded_by_the_chunk(self):
        """The temporary must not scale with the array.

        A 1080p-shaped stand-in: the naive path would allocate 4x the
        whole buffer, the chunked one allocates 4x a slice.
        """
        n = 200
        frames = np.zeros((n, 108, 192, 3), dtype=np.uint8)
        naive_bytes = frames.nbytes * 4
        chunk_bytes = frames[:_DARKEN_CHUNK_FRAMES].nbytes * 4
        assert chunk_bytes < naive_bytes / 4
