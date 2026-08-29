"""Tests for `main.ingest_track` — the `--ingest` catalog append.

Everything runs against a tmp `tracks/` tree (the suite never touches a
real catalog): the fixtures `chdir` into `tmp_path` so `main`'s
relative `TRACKS_BASE_DIR` / `CATALOG_PATH` defaults resolve there, the
same trick `tests/test_catalog_mp3.py` uses for `build_catalog`.

The ffmpeg resample is REAL — a 3 s 48 kHz source pushed through the
actual binary and probed back with soundfile. Mocking it would test
nothing: the whole point of the step is that the bytes come out at
44.1 kHz / 16-bit / stereo.
"""
from __future__ import annotations

import builtins
import hashlib
import json
import os
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest
import soundfile as sf

import main

# Long enough to clear the 120 s session-eligibility floor.
LONG_SEC = 121


def _write_wav(path: Path, seconds: float, rate: int = 44100, channels: int = 2,
               sampwidth: int = 2) -> Path:
    """A real (silent) PCM WAV of the requested shape."""
    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(rate)
        wf.writeframes(b"\x00" * (frames * channels * sampwidth))
    return path


def _write_tone_wav(path: Path, seconds: float, rate: int, channels: int = 2) -> Path:
    """Non-silent 16-bit PCM, so a resample has something to actually chew on."""
    frames = int(rate * seconds)
    buf = bytearray()
    for i in range(frames):
        # ~440 Hz square-ish wave; exact shape is irrelevant, non-zero is not.
        value = 8000 if (i // max(1, rate // 880)) % 2 == 0 else -8000
        buf += struct.pack("<" + "h" * channels, *([value] * channels))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(bytes(buf))
    return path


def _sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tree_hash(root: Path) -> list[tuple[str, str]]:
    """(relative path, sha256) for every file under `root`, sorted."""
    out = []
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            out.append((str(p.relative_to(root)).replace(os.sep, "/"), _sha256(p)))
    return out


@pytest.fixture(scope="module")
def long_wav_44k(tmp_path_factory):
    """Conformant source: 44.1 kHz / 16-bit / stereo, over the duration floor."""
    d = tmp_path_factory.mktemp("sources")
    return _write_wav(d / "conformant.wav", LONG_SEC, rate=44100, channels=2)


@pytest.fixture(scope="module")
def long_wav_48k(tmp_path_factory):
    """What ACE-Step actually renders: 48 kHz stereo."""
    d = tmp_path_factory.mktemp("sources48")
    return _write_wav(d / "ace.wav", LONG_SEC, rate=48000, channels=2)


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    """A tmp tracks/ tree with two genre folders and an existing catalog."""
    monkeypatch.chdir(tmp_path)
    tracks = tmp_path / "tracks"
    (tracks / "techno").mkdir(parents=True)
    (tracks / "healing").mkdir(parents=True)
    (tracks / "tracks.json").write_text(
        json.dumps({"tracks": [{
            "id": "techno--old-signal",
            "display_name": "Old Signal",
            "file": "tracks/techno/Old Signal.wav",
            "genre_folder": "techno",
            "genre": "techno",
            "camelot_key": "5A",
            "bpm": 138.0,
            "variant_of": None,
        }]}, indent=2),
        encoding="utf-8",
    )
    return tracks


def _read_catalog(tracks: Path) -> list[dict]:
    return json.loads((tracks / "tracks.json").read_text(encoding="utf-8"))["tracks"]


class TestHappyPath:
    def test_entry_shape_and_file_land(self, catalog, long_wav_44k):
        entry = main.ingest_track(
            str(long_wav_44k), "techno",
            display_name="Neon Rain", bpm=130, keyscale="A Minor",
        )
        assert entry == {
            "id": "techno--neon-rain",
            "display_name": "Neon Rain",
            "file": "tracks/techno/Neon Rain.wav",
            "genre_folder": "techno",
            "genre": "techno",
            "camelot_key": "8A",
            "bpm": 130.0,
            "variant_of": None,
        }
        assert (catalog / "techno" / "Neon Rain.wav").exists()

        entries = _read_catalog(catalog)
        assert len(entries) == 2
        assert entries[-1] == entry
        # The catalog's key order is the one tracks.json.example uses.
        assert list(entries[-1]) == [
            "id", "display_name", "file", "genre_folder", "genre",
            "camelot_key", "bpm", "variant_of",
        ]

    def test_genre_folder_matches_case_insensitively(self, catalog, long_wav_44k):
        entry = main.ingest_track(
            str(long_wav_44k), "TECHNO",
            display_name="Case Test", bpm=130, keyscale="A Minor",
        )
        # The real on-disk folder name wins, not what the caller typed.
        assert entry["genre_folder"] == "techno"
        assert entry["file"] == "tracks/techno/Case Test.wav"

    def test_creates_catalog_when_absent(self, tmp_path, monkeypatch, long_wav_44k):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "tracks" / "techno").mkdir(parents=True)
        main.ingest_track(
            str(long_wav_44k), "techno",
            display_name="First Ever", bpm=130, keyscale="A Minor",
        )
        entries = _read_catalog(tmp_path / "tracks")
        assert [e["id"] for e in entries] == ["techno--first-ever"]
        # Nothing to back up on a fresh catalog.
        assert list((tmp_path / "tracks").glob("*.bak")) == []

    def test_id_follows_make_track_id(self, catalog, long_wav_44k):
        entry = main.ingest_track(
            str(long_wav_44k), "healing",
            display_name="Silver Bloom", bpm=65, keyscale="C Major",
        )
        assert entry["id"] == main._make_track_id("healing", "Silver Bloom", False)
        assert entry["camelot_key"] == "8B"

    @pytest.mark.parametrize("variant_of", [None, "techno--old-signal"])
    def test_a_later_build_catalog_would_rederive_the_same_entry(
        self, catalog, long_wav_44k, variant_of,
    ):
        """The filename convention is load-bearing, so pin it.

        `build_catalog` derives display_name/variant from the file's
        STEM (`main.py`: strip a trailing " (1)" -> base_name +
        is_variant). Ingest runs that backwards; if it didn't, a later
        `--build-catalog` scan would mint a second, different entry for
        the same WAV.
        """
        name = "Old Signal" if variant_of else "Fresh Cut"
        entry = main.ingest_track(str(long_wav_44k), "techno", display_name=name,
                                  bpm=130, keyscale="A Minor", variant_of=variant_of)

        # --- build_catalog's derivation, verbatim ---
        stem = os.path.splitext(os.path.basename(entry["file"]))[0]
        if stem.endswith(" (1)"):
            base_name, is_variant = stem[:-4].strip(), True
        else:
            base_name, is_variant = stem, False

        assert base_name == entry["display_name"]
        assert is_variant == bool(entry["variant_of"])
        assert main._make_track_id("techno", base_name, is_variant) == entry["id"]
        assert (base_name if is_variant else None) == entry["variant_of"]


class TestAudioConformance:
    def test_conformant_input_is_copied_bit_exact(self, catalog, long_wav_44k):
        main.ingest_track(
            str(long_wav_44k), "techno",
            display_name="Bit Exact", bpm=130, keyscale="A Minor",
        )
        dest = catalog / "techno" / "Bit Exact.wav"
        assert _sha256(dest) == _sha256(long_wav_44k), "conformant source was re-encoded"

    def test_real_ffmpeg_resample_of_48k_source(self, tmp_path):
        """A 3 s 48 kHz stereo WAV through the real binary, probed back."""
        if not main._ffmpeg_available():
            pytest.skip("ffmpeg not on PATH")
        src = _write_tone_wav(tmp_path / "src48.wav", 3.0, rate=48000, channels=2)
        dst = tmp_path / "out.wav"
        main._ingest_write_wav(str(src), str(dst), conformant=False)

        info = sf.info(str(dst))
        assert info.samplerate == 44100
        assert info.channels == 2
        assert info.subtype == "PCM_16"
        assert info.frames / info.samplerate == pytest.approx(3.0, abs=0.05)
        assert _sha256(dst) != _sha256(src)

    def test_ingest_resamples_a_48k_source(self, catalog, long_wav_48k):
        if not main._ffmpeg_available():
            pytest.skip("ffmpeg not on PATH")
        main.ingest_track(
            str(long_wav_48k), "techno",
            display_name="From Ace", bpm=130, keyscale="A Minor",
        )
        info = sf.info(str(catalog / "techno" / "From Ace.wav"))
        assert (info.samplerate, info.channels, info.subtype) == (44100, 2, "PCM_16")

    @pytest.mark.parametrize(("rate", "channels", "width"), [
        (48000, 2, 2),   # ACE-Step's native rate
        (44100, 1, 2),   # mono
        (44100, 2, 1),   # 8-bit
    ])
    def test_non_conformant_shapes_are_not_copied(self, tmp_path, rate, channels, width):
        src = _write_wav(tmp_path / "src.wav", 1.0, rate=rate, channels=channels,
                         sampwidth=width)
        samplerate, ch, subtype, _ = main._ingest_probe(str(src))
        conformant = (samplerate == 44100 and ch == 2 and subtype == "PCM_16")
        assert not conformant


class TestRefusals:
    def test_short_track(self, catalog, tmp_path):
        short = _write_wav(tmp_path / "short.wav", 30.0)
        with pytest.raises(SystemExit) as exc:
            main.ingest_track(str(short), "techno",
                              display_name="Too Short", bpm=130, keyscale="A Minor")
        assert exc.value.code == 1

    def test_short_track_message_names_the_floor(self, catalog, tmp_path, capsys):
        short = _write_wav(tmp_path / "short.wav", 30.0)
        with pytest.raises(SystemExit):
            main.ingest_track(str(short), "techno",
                              display_name="Too Short", bpm=130, keyscale="A Minor")
        out = capsys.readouterr().out
        assert "30.0s" in out and "120s minimum" in out
        assert not (catalog / "techno" / "Too Short.wav").exists()

    def test_missing_genre_folder_lists_what_exists(self, catalog, long_wav_44k, capsys):
        with pytest.raises(SystemExit):
            main.ingest_track(str(long_wav_44k), "synthware",
                              display_name="Nope", bpm=130, keyscale="A Minor")
        out = capsys.readouterr().out
        assert "synthware" in out
        assert "healing" in out and "techno" in out  # available folders listed

    def test_bpm_outside_window_names_the_window(self, catalog, long_wav_44k, capsys):
        with pytest.raises(SystemExit):
            main.ingest_track(str(long_wav_44k), "techno",
                              display_name="Too Slow", bpm=90, keyscale="A Minor")
        out = capsys.readouterr().out
        assert "90" in out and "120-160" in out
        assert len(_read_catalog(catalog)) == 1  # catalog untouched

    def test_bpm_at_window_edges_is_accepted(self, catalog, long_wav_44k):
        lo = main.ingest_track(str(long_wav_44k), "techno",
                               display_name="Edge Lo", bpm=120, keyscale="A Minor")
        hi = main.ingest_track(str(long_wav_44k), "techno",
                               display_name="Edge Hi", bpm=160, keyscale="A Minor")
        assert (lo["bpm"], hi["bpm"]) == (120.0, 160.0)

    def test_genre_without_bpm_window(self, tmp_path, monkeypatch, long_wav_44k, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "tracks" / "brand new genre").mkdir(parents=True)
        with pytest.raises(SystemExit):
            main.ingest_track(str(long_wav_44k), "brand new genre",
                              display_name="Orphan", bpm=130, keyscale="A Minor")
        assert "BPM_GENRE_RANGES" in capsys.readouterr().out

    def test_unparseable_keyscale(self, catalog, long_wav_44k, capsys):
        with pytest.raises(SystemExit):
            main.ingest_track(str(long_wav_44k), "techno",
                              display_name="Bad Key", bpm=130, keyscale="H Dorian")
        out = capsys.readouterr().out
        assert "H Dorian" in out
        assert not (catalog / "techno" / "Bad Key.wav").exists()

    def test_missing_required_metadata(self, catalog, long_wav_44k, capsys):
        with pytest.raises(SystemExit):
            main.ingest_track(str(long_wav_44k), "techno", display_name="Only Name")
        out = capsys.readouterr().out
        assert "--bpm" in out and "--keyscale" in out

    def test_missing_audio_file(self, catalog, capsys):
        with pytest.raises(SystemExit):
            main.ingest_track("no/such/file.wav", "techno",
                              display_name="Ghost", bpm=130, keyscale="A Minor")
        assert "not found" in capsys.readouterr().out

    def test_refuses_to_overwrite_an_existing_wav(self, catalog, long_wav_44k, capsys):
        (catalog / "techno" / "Occupied.wav").write_bytes(b"pre-existing")
        with pytest.raises(SystemExit):
            main.ingest_track(str(long_wav_44k), "techno",
                              display_name="Occupied", bpm=130, keyscale="A Minor")
        assert "refusing to overwrite" in capsys.readouterr().out
        assert (catalog / "techno" / "Occupied.wav").read_bytes() == b"pre-existing"

    def test_display_name_with_illegal_filename_chars(self, catalog, long_wav_44k, capsys):
        with pytest.raises(SystemExit):
            main.ingest_track(str(long_wav_44k), "techno",
                              display_name="Bad/Name?", bpm=130, keyscale="A Minor")
        assert "illegal characters" in capsys.readouterr().out

    def test_non_numeric_bpm(self, catalog, long_wav_44k, capsys):
        with pytest.raises(SystemExit):
            main.ingest_track(str(long_wav_44k), "techno",
                              display_name="NaN", bpm="fast", keyscale="A Minor")
        assert "not a number" in capsys.readouterr().out


class TestIdCollision:
    def test_second_ingest_of_the_same_name_is_refused(self, catalog, long_wav_44k, capsys):
        main.ingest_track(str(long_wav_44k), "techno",
                          display_name="Twin", bpm=130, keyscale="A Minor")
        with pytest.raises(SystemExit):
            main.ingest_track(str(long_wav_44k), "techno",
                              display_name="Twin", bpm=130, keyscale="A Minor")
        out = capsys.readouterr().out
        assert "techno--twin" in out
        assert "--variant-of" in out  # the message points at the way out
        assert len(_read_catalog(catalog)) == 2  # the seed entry + the first Twin

    def test_collision_against_a_pre_existing_entry(self, catalog, long_wav_44k, capsys):
        with pytest.raises(SystemExit):
            main.ingest_track(str(long_wav_44k), "techno",
                              display_name="Old Signal", bpm=130, keyscale="A Minor")
        out = capsys.readouterr().out
        assert "techno--old-signal" in out
        assert "tracks/techno/Old Signal.wav" in out  # names the file it clashes with


class TestVariantOf:
    def test_variant_by_id_resolves_to_the_base_display_name(self, catalog, long_wav_44k):
        entry = main.ingest_track(
            str(long_wav_44k), "techno", display_name="Old Signal",
            bpm=130, keyscale="A Minor", variant_of="techno--old-signal",
        )
        # track_identity.piece_keys rebuilds the base id from variant_of,
        # so it has to hold the base take's display_name.
        assert entry["variant_of"] == "Old Signal"
        assert entry["id"] == "techno--old-signal-v2"
        assert entry["file"] == "tracks/techno/Old Signal (1).wav"
        assert (catalog / "techno" / "Old Signal (1).wav").exists()

    def test_variant_by_display_name_passes_through(self, catalog, long_wav_44k):
        entry = main.ingest_track(
            str(long_wav_44k), "techno", display_name="Old Signal",
            bpm=130, keyscale="A Minor", variant_of="Old Signal",
        )
        assert entry["variant_of"] == "Old Signal"
        assert entry["id"] == "techno--old-signal-v2"

    def test_the_two_takes_share_a_piece_key(self, catalog, long_wav_44k):
        from agent.track_identity import piece_keys

        entry = main.ingest_track(
            str(long_wav_44k), "techno", display_name="Old Signal",
            bpm=130, keyscale="A Minor", variant_of="techno--old-signal",
        )
        base = _read_catalog(catalog)[0]
        assert piece_keys(entry) & piece_keys(base), "variant did not link to its base take"

    def test_dangling_variant_of_is_refused(self, catalog, long_wav_44k, capsys):
        with pytest.raises(SystemExit):
            main.ingest_track(str(long_wav_44k), "techno", display_name="Orphan Take",
                              bpm=130, keyscale="A Minor", variant_of="techno--nothing")
        assert "matches no catalog id or display_name" in capsys.readouterr().out


class TestSidecar:
    def _sidecar(self, tmp_path, **payload) -> str:
        p = tmp_path / "meta.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return str(p)

    def test_sidecar_supplies_everything(self, catalog, tmp_path, long_wav_44k):
        side = self._sidecar(tmp_path, bpm=140, keyscale="C# Major",
                             display_name="From Sidecar")
        entry = main.ingest_track(str(long_wav_44k), "techno", sidecar=side)
        assert entry["display_name"] == "From Sidecar"
        assert entry["bpm"] == 140.0
        assert entry["camelot_key"] == "3B"

    def test_flags_win_over_sidecar(self, catalog, tmp_path, long_wav_44k):
        side = self._sidecar(tmp_path, bpm=140, keyscale="C# Major",
                             display_name="Sidecar Name", variant_of="Old Signal")
        entry = main.ingest_track(
            str(long_wav_44k), "techno", sidecar=side,
            display_name="Flag Name", bpm=125, keyscale="A Minor",
        )
        assert entry["display_name"] == "Flag Name"
        assert entry["bpm"] == 125.0
        assert entry["camelot_key"] == "8A"
        # variant_of came only from the sidecar, so it still applies.
        assert entry["variant_of"] == "Old Signal"

    def test_sidecar_variant_of_is_used_when_no_flag(self, catalog, tmp_path, long_wav_44k):
        side = self._sidecar(tmp_path, bpm=130, keyscale="A Minor",
                             display_name="Old Signal", variant_of="techno--old-signal")
        entry = main.ingest_track(str(long_wav_44k), "techno", sidecar=side)
        assert entry["id"] == "techno--old-signal-v2"

    def test_missing_sidecar_is_refused(self, catalog, long_wav_44k, capsys):
        with pytest.raises(SystemExit):
            main.ingest_track(str(long_wav_44k), "techno", sidecar="no/such/meta.json")
        assert "sidecar not found" in capsys.readouterr().out

    def test_malformed_sidecar_is_refused(self, catalog, tmp_path, long_wav_44k, capsys):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(SystemExit):
            main.ingest_track(str(long_wav_44k), "techno", sidecar=str(bad))
        assert "not readable JSON" in capsys.readouterr().out

    def test_sidecar_must_be_an_object(self, catalog, tmp_path, long_wav_44k, capsys):
        bad = tmp_path / "list.json"
        bad.write_text("[1, 2]", encoding="utf-8")
        with pytest.raises(SystemExit):
            main.ingest_track(str(long_wav_44k), "techno", sidecar=str(bad))
        assert "must be a JSON object" in capsys.readouterr().out


class TestLyrics:
    def test_lyrics_file_lands_as_an_lrc_sidecar(self, catalog, tmp_path, long_wav_44k):
        lyr = tmp_path / "words.txt"
        lyr.write_text("[Verse]\nneon rain\n", encoding="utf-8")
        main.ingest_track(str(long_wav_44k), "techno", display_name="With Words",
                          bpm=130, keyscale="A Minor", lyrics=str(lyr))
        lrc = catalog / "techno" / "With Words.lrc"
        assert lrc.read_text(encoding="utf-8") == "[Verse]\nneon rain\n"

    def test_sidecar_lyrics_text_lands_too(self, catalog, tmp_path, long_wav_44k):
        side = tmp_path / "meta.json"
        side.write_text(json.dumps({
            "bpm": 130, "keyscale": "A Minor",
            "display_name": "Sidecar Words", "lyrics": "[Chorus]\nhold",
        }), encoding="utf-8")
        main.ingest_track(str(long_wav_44k), "techno", sidecar=str(side))
        assert (catalog / "techno" / "Sidecar Words.lrc").read_text(
            encoding="utf-8") == "[Chorus]\nhold"

    def test_no_lyrics_means_no_lrc(self, catalog, long_wav_44k):
        main.ingest_track(str(long_wav_44k), "techno", display_name="Instrumental",
                          bpm=130, keyscale="A Minor")
        assert not (catalog / "techno" / "Instrumental.lrc").exists()

    def test_missing_lyrics_file_is_refused(self, catalog, long_wav_44k, capsys):
        with pytest.raises(SystemExit):
            main.ingest_track(str(long_wav_44k), "techno", display_name="Ghost Words",
                              bpm=130, keyscale="A Minor", lyrics="no/such/words.txt")
        assert "lyrics file not found" in capsys.readouterr().out


class TestBackup:
    def test_backup_uses_the_gitignored_naming(self, catalog, long_wav_44k):
        before = _read_catalog(catalog)
        main.ingest_track(str(long_wav_44k), "techno", display_name="Backed Up",
                          bpm=130, keyscale="A Minor")
        backups = list(catalog.glob("tracks.json.*.bak"))
        assert len(backups) == 1, [p.name for p in catalog.iterdir()]
        # `.gitignore` carries `tracks/tracks.json.*.bak` — the stamp sits
        # between the name and the suffix, so backups stay ignored.
        stamp = backups[0].name[len("tracks.json."):-len(".bak")]
        assert len(stamp) == 15 and stamp[8] == "-" and stamp.replace("-", "").isdigit()
        # It holds the catalog as it was BEFORE the append.
        assert json.loads(backups[0].read_text(encoding="utf-8"))["tracks"] == before

    def test_no_backup_when_the_ingest_is_refused(self, catalog, long_wav_44k):
        with pytest.raises(SystemExit):
            main.ingest_track(str(long_wav_44k), "techno", display_name="Nope",
                              bpm=999, keyscale="A Minor")
        assert list(catalog.glob("*.bak")) == []


class TestDryRun:
    def test_touches_nothing(self, catalog, long_wav_44k, capsys):
        before = _tree_hash(catalog)
        entry = main.ingest_track(
            str(long_wav_44k), "techno", display_name="Phantom",
            bpm=130, keyscale="A Minor", dry_run=True,
        )
        assert _tree_hash(catalog) == before
        out = capsys.readouterr().out
        assert "--dry-run: nothing written." in out
        # The plan is the full plan: destination, conversion, key, entry.
        assert "tracks/techno/Phantom.wav" in out
        assert "A Minor → 8A" in out
        assert "techno--phantom" in out
        assert "120-160" in out
        # The entry it reports is the one a real run would write.
        assert entry["id"] == "techno--phantom"

    def test_dry_run_still_refuses(self, catalog, long_wav_44k, capsys):
        with pytest.raises(SystemExit):
            main.ingest_track(str(long_wav_44k), "techno", display_name="Phantom",
                              bpm=90, keyscale="A Minor", dry_run=True)
        assert "120-160" in capsys.readouterr().out

    def test_dry_run_reports_the_resample_plan(self, catalog, long_wav_48k, capsys):
        main.ingest_track(str(long_wav_48k), "techno", display_name="Phantom48",
                          bpm=130, keyscale="A Minor", dry_run=True)
        out = capsys.readouterr().out
        assert "48000 Hz" in out
        assert "resampling to 44100 Hz" in out

    def test_dry_run_reports_a_bit_exact_copy(self, catalog, long_wav_44k, capsys):
        main.ingest_track(str(long_wav_44k), "techno", display_name="Phantom44",
                          bpm=130, keyscale="A Minor", dry_run=True)
        assert "copying bit-exact" in capsys.readouterr().out


class TestNoMadmom:
    def test_ingest_runs_on_a_host_without_madmom(self, catalog, long_wav_44k, monkeypatch):
        """The ingest path must import cleanly where madmom does not exist."""
        for mod in [m for m in sys.modules if m.startswith("madmom")]:
            monkeypatch.delitem(sys.modules, mod, raising=False)

        real_import = builtins.__import__

        def blocking_import(name, *args, **kwargs):
            if name == "madmom" or name.startswith("madmom."):
                raise ImportError("madmom is not installed on this host")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocking_import)
        entry = main.ingest_track(str(long_wav_44k), "techno", display_name="No Madmom",
                                  bpm=130, keyscale="A Minor")
        assert entry["id"] == "techno--no-madmom"
        assert not any(m.startswith("madmom") for m in sys.modules)

    def test_entry_carries_no_analysis_fields(self, catalog, long_wav_44k):
        """Beatgrid/peaks/duration are --fix-incomplete's job, not ingest's."""
        entry = main.ingest_track(str(long_wav_44k), "techno", display_name="Lean",
                                  bpm=130, keyscale="A Minor")
        for field in ("beatgrid", "waveform_peaks", "duration_sec", "mp3_file"):
            assert field not in entry


class TestCli:
    """`--ingest` reaches `ingest_track` through the real argparse wiring."""

    def _run(self, tmp_path, *args):
        return subprocess.run(
            [sys.executable, str(Path(main.__file__).resolve()), *args],
            cwd=str(tmp_path), capture_output=True, text=True,
        )

    def test_dry_run_through_the_cli(self, catalog, tmp_path, long_wav_44k):
        before = _tree_hash(catalog)
        res = self._run(
            tmp_path, "--ingest", str(long_wav_44k), "--genre", "techno",
            "--display-name", "Cli Phantom", "--bpm", "130",
            "--keyscale", "A Minor", "--dry-run",
        )
        assert res.returncode == 0, res.stdout + res.stderr
        assert "--dry-run: nothing written." in res.stdout
        assert _tree_hash(catalog) == before

    def test_ingest_without_genre_is_refused(self, catalog, tmp_path, long_wav_44k):
        res = self._run(tmp_path, "--ingest", str(long_wav_44k),
                        "--display-name", "No Genre", "--bpm", "130",
                        "--keyscale", "A Minor")
        assert res.returncode == 1
        assert "--genre required with --ingest" in res.stdout

    def test_help_states_flag_precedence(self, tmp_path):
        res = self._run(tmp_path, "--help")
        assert res.returncode == 0
        assert "Flags win over the sidecar on conflict" in " ".join(res.stdout.split())
