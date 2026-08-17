"""Regression tests for `_attach_suno_metadata`'s `prefer_title` flag.

Older Suno exports embedded a UUID in the filename, so a fresh entry's
`display_name` looked "legacy" and got replaced by the sidecar title. Newer
exports (e.g. ``Healing-Amber_Bloom``) use human-readable filenames that
aren't legacy by that test, so build_catalog now passes ``prefer_title=True``
for new entries to always adopt the Suno title. These tests pin that behavior
and guard the conservative default used on the existing-entry patch path.

This fix was originally written for the aural batch but lived only on an
unmerged branch, so the healing batch was catalogued without it and shipped
47 entries titled ``Healing-Amber_Bloom`` instead of ``Amber Bloom``. The
aural cases below are kept as the original motivating examples.
"""
from __future__ import annotations

import main as m


def _write_sidecar(tmp_path, stem: str, title: str):
    audio = tmp_path / f"{stem}.wav"
    audio.write_bytes(b"")
    (tmp_path / f"{stem}.wav.txt").write_text(f"Title: {title}\n", encoding="utf-8")
    return str(audio)


class TestPreferTitle:
    def test_prefer_title_overrides_human_readable_name(self, tmp_path):
        # Non-legacy (no UUID) filename-derived name — the exact aural case.
        audio = _write_sidecar(tmp_path, "Aural-Deep_Blue_Drift (2)", "Deep Blue Drift")
        entry = {"display_name": "Aural-Deep_Blue_Drift (2)"}
        mutated = m._attach_suno_metadata(entry, audio, prefer_title=True)
        assert mutated is True
        assert entry["display_name"] == "Deep Blue Drift"
        assert entry["suno"]["title"] == "Deep Blue Drift"

    def test_genre_prefixed_underscore_name_adopts_title(self, tmp_path):
        """The healing shape: ``Healing-Amber_Bloom`` -> ``Amber Bloom``.

        Without prefer_title this reaches the video title and the stream
        overlay with the genre prefix and underscores intact.
        """
        audio = _write_sidecar(tmp_path, "Healing-Amber_Bloom", "Amber Bloom")
        entry = {"display_name": "Healing-Amber_Bloom"}
        assert m._attach_suno_metadata(entry, audio, prefer_title=True) is True
        assert entry["display_name"] == "Amber Bloom"

    def test_default_keeps_non_legacy_name(self, tmp_path):
        # Default (existing-entry patch path) must NOT clobber a clean name.
        audio = _write_sidecar(tmp_path, "Aural-Deep_Blue_Drift (2)", "Deep Blue Drift")
        entry = {"display_name": "Aural-Deep_Blue_Drift (2)"}
        mutated = m._attach_suno_metadata(entry, audio)  # prefer_title=False
        assert entry["display_name"] == "Aural-Deep_Blue_Drift (2)"
        # sidecar still attached even though the name was left alone
        assert entry["suno"]["title"] == "Deep Blue Drift"
        assert mutated is True

    def test_legacy_uuid_name_still_replaced_by_default(self, tmp_path):
        audio = _write_sidecar(tmp_path, "song", "Real Title")
        entry = {"display_name": "track-12345678-1234-1234-1234-123456789abc"}
        assert m._attach_suno_metadata(entry, audio) is True
        assert entry["display_name"] == "Real Title"

    def test_disambiguated_name_never_overwritten(self, tmp_path):
        # A name a disambiguation pass chose must survive even prefer_title.
        audio = _write_sidecar(tmp_path, "x", "Deep Blue Drift")
        entry = {
            "display_name": "Calm Abyss",
            "suno": {"title": "Deep Blue Drift", "disambiguated": True},
        }
        mutated = m._attach_suno_metadata(entry, audio, prefer_title=True)
        assert entry["display_name"] == "Calm Abyss"
        assert mutated is False

    def test_no_title_leaves_name_untouched(self, tmp_path):
        # Untitled tracks (no sidecar title) keep their name even with prefer_title.
        audio = tmp_path / "Aural-Untitled.wav"
        audio.write_bytes(b"")
        (tmp_path / "Aural-Untitled.wav.txt").write_text(
            "Artist: pabloformoso\n", encoding="utf-8"
        )
        entry = {"display_name": "Aural-Untitled"}
        m._attach_suno_metadata(entry, str(audio), prefer_title=True)
        assert entry["display_name"] == "Aural-Untitled"
