"""Cover art for tracks Apollo generates itself.

The catalog page has always rendered a cover: 510 of the 513 tracks
carry ``suno.cover_url`` from their Suno import. The three blanks were
exactly the tracks made at home — the two `Velvet Corridor` takes and
`AChillE` — which is every track the publish endpoint creates. The slot
existed and was proven; only the local half was missing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "web") not in sys.path:
    sys.path.insert(0, str(ROOT / "web"))

from backend import covers  # noqa: E402


# --- id safety: the id becomes a filename, so it is untrusted ------------

@pytest.mark.parametrize(
    "bad",
    [
        "",
        ".",
        "..",
        "../../etc/passwd",
        "healing/../../secret",
        "with space",
        "semi;colon",
        "sub/dir",
        "back\\slash",
        "null\x00byte",
    ],
)
def test_unsafe_track_ids_are_refused(bad):
    assert covers.is_safe_track_id(bad) is False
    assert covers.cover_path(bad) is None


@pytest.mark.parametrize(
    "good", ["healing--achille", "deep-house--velvet-corridor-v2", "a.b_c-1"]
)
def test_real_catalog_shaped_ids_are_accepted(good):
    assert covers.is_safe_track_id(good) is True
    assert covers.cover_path(good) is not None


def test_cover_path_stays_inside_the_cover_directory():
    p = covers.cover_path("healing--achille")
    assert p is not None
    assert p.parent == covers.cover_dir()
    assert p.name == "healing--achille.png"


def test_generate_cover_refuses_an_unsafe_id_without_calling_azure(monkeypatch):
    """An unsafe id must be rejected BEFORE any import or network work."""
    def explode(*_a, **_kw):  # pragma: no cover — must never run
        raise AssertionError("generation attempted for an unsafe id")

    monkeypatch.setattr(covers.importlib, "import_module", explode)
    assert covers.generate_cover("../escape", "Name", "healing") is None


# --- presence / URL -------------------------------------------------------

def test_has_cover_is_false_when_the_file_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(covers, "cover_dir", lambda: tmp_path)
    assert covers.has_cover("nothing-here") is False
    assert covers.cover_url_for("nothing-here") is None


def test_cover_url_is_relative_so_it_works_behind_dev_proxy_and_nginx(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(covers, "cover_dir", lambda: tmp_path)
    (tmp_path / "healing--achille.png").write_bytes(b"\x89PNG")
    url = covers.cover_url_for("healing--achille")
    assert url == "/api/tracks/healing--achille/cover"
    assert not url.startswith("http")


def test_cover_url_for_is_none_for_an_unsafe_id(tmp_path, monkeypatch):
    monkeypatch.setattr(covers, "cover_dir", lambda: tmp_path)
    assert covers.cover_url_for("../../etc/passwd") is None


# --- never fatal ----------------------------------------------------------

def test_generation_failure_returns_none_instead_of_raising(
    tmp_path, monkeypatch
):
    """A publish that already succeeded must not be reported as failed."""
    monkeypatch.setattr(covers, "cover_dir", lambda: tmp_path)

    class Boom:
        GENRE_THEMES: dict = {}

        @staticmethod
        def _generate_artwork(*_a, **_kw):
            raise RuntimeError("azure said no")

    monkeypatch.setattr(covers.importlib, "import_module", lambda _n: Boom)
    assert covers.generate_cover("healing--x", "X", "healing") is None


def test_an_existing_cover_is_not_regenerated(tmp_path, monkeypatch):
    """Publishing the same id twice must not buy a second image."""
    monkeypatch.setattr(covers, "cover_dir", lambda: tmp_path)
    (tmp_path / "healing--x.png").write_bytes(b"\x89PNG")

    def explode(*_a, **_kw):  # pragma: no cover — must never run
        raise AssertionError("regenerated an existing cover")

    monkeypatch.setattr(covers.importlib, "import_module", explode)
    assert covers.generate_cover("healing--x", "X", "healing") == str(
        tmp_path / "healing--x.png"
    )


def test_the_genre_theme_reaches_the_artwork_call(tmp_path, monkeypatch):
    """A cover must use its genre's visual language, not the silent default."""
    monkeypatch.setattr(covers, "cover_dir", lambda: tmp_path)
    seen = {}

    class Fake:
        GENRE_THEMES = {"synthware": {"artwork_style": "dark-techno"}}

        @staticmethod
        def _generate_artwork(name, _dir, theme, cache_name=None, prompt=None):
            seen.update(name=name, theme=theme, cache_name=cache_name)
            return "/tmp/x.png"

    monkeypatch.setattr(covers.importlib, "import_module", lambda _n: Fake)
    covers.generate_cover("synthware--neon", "Neon Rain", "Synthware")

    assert seen["theme"] == {"artwork_style": "dark-techno"}
    # The PROMPT gets the pretty name, the FILENAME gets the id.
    assert seen["name"] == "Neon Rain"
    assert seen["cache_name"] == "synthware--neon"


# --- generations: one cover per ACE task, its own namespace ---------------

def test_a_generation_cover_lives_apart_from_track_covers(tmp_path, monkeypatch):
    """`/api/tracks/{id}/cover` resolves by filename alone; a task id in
    that directory would be served under a track URL."""
    monkeypatch.setattr(covers, "cover_dir", lambda: tmp_path / "catalog")
    monkeypatch.setattr(covers, "generation_cover_dir", lambda: tmp_path / "generations")
    p = covers.generation_cover_path("9d0f4a21-77c3")
    assert p == tmp_path / "generations" / "9d0f4a21-77c3.png"
    assert covers.cover_path("9d0f4a21-77c3") != p
    assert covers.generation_cover_path("../x") is None
    assert covers.generation_cover_url_for("9d0f4a21-77c3") is None
    p.parent.mkdir()
    p.write_bytes(b"png")
    assert covers.generation_cover_url_for("9d0f4a21-77c3") == "/api/generator/generations/9d0f4a21-77c3/cover"
    assert covers.cover_url_for("9d0f4a21-77c3") is None, "the track route must not see it"


@pytest.mark.parametrize(
    ("prompt", "title"),
    [
        ("dark melodic techno, hypnotic, driving", "Dark Melodic Techno"),
        ("  warm lofi keys,\n  tape hiss  ", "Warm Lofi Keys"),
        ("neon rain at dawn over the harbour lights", "Neon Rain At Dawn Over"),
        ("a/b: <song>", "A B Song"),
        ("", "Untitled Take"),
        (None, "Untitled Take"),
    ],
)
def test_cover_title_mirrors_the_frontend_name(prompt, title):
    """The card's title, the published name and the words the image is
    drawn from are ONE name — `suggestDisplayName`, mirrored."""
    assert covers.cover_title(prompt) == title


def test_a_generation_cover_is_drawn_from_the_users_words(tmp_path, monkeypatch):
    monkeypatch.setattr(covers, "generation_cover_dir", lambda: tmp_path)
    seen = {}

    class Fake:
        GENRE_THEMES = {"techno": {"artwork_style": "dark-techno"}}

        @staticmethod
        def _generate_artwork(name, directory, theme, cache_name=None, prompt=None):
            seen.update(name=name, directory=directory, theme=theme, cache_name=cache_name)
            return str(tmp_path / f"{cache_name}.png")

    monkeypatch.setattr(covers.importlib, "import_module", lambda _n: Fake)
    out = covers.generate_generation_cover("task-1", "neon rain at dawn, hypnotic", "Techno")

    assert out == str(tmp_path / "task-1.png")
    assert seen["name"] == "Neon Rain At Dawn"        # the prompt, never the task id
    assert seen["cache_name"] == "task-1"             # the filename IS the task id
    assert seen["directory"] == str(tmp_path)
    assert seen["theme"] == {"artwork_style": "dark-techno"}


def test_a_generation_cover_already_on_disk_is_never_bought_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(covers, "generation_cover_dir", lambda: tmp_path)
    (tmp_path / "task-1.png").write_bytes(b"png")

    def explode(_name):
        raise AssertionError("main must not be imported for a cached cover")

    monkeypatch.setattr(covers.importlib, "import_module", explode)
    assert covers.generate_generation_cover("task-1", "x", "techno") == str(tmp_path / "task-1.png")
    assert covers.generate_generation_cover("../x", "x", "techno") is None


# --- art direction: one prompt per SONG, not one per genre -----------------

class _FakeMain:
    GENRE_THEMES = {"aural": {"artwork_style": "organic-zen"}}
    ARTWORK_PROMPTS = {
        "abstract": "Abstract artwork inspired by '{track_name}'.",
        "organic-zen": "Warm painterly landscape, {track_name} atmosphere. Desert dunes or misty forest.",
    }
    seen: dict = {}

    @staticmethod
    def _generate_artwork(name, directory, theme, cache_name=None, prompt=None):
        _FakeMain.seen.update(name=name, theme=theme, cache_name=cache_name, prompt=prompt)
        return f"{directory}/{cache_name}.png"


@pytest.fixture
def fake_main(monkeypatch, tmp_path):
    _FakeMain.seen.clear()
    monkeypatch.setattr(covers, "generation_cover_dir", lambda: tmp_path)
    monkeypatch.setattr(covers, "cover_dir", lambda: tmp_path / "catalog")
    monkeypatch.setattr(covers.importlib, "import_module", lambda _n: _FakeMain)
    monkeypatch.delenv("APOLLO_COVER_PROMPT_DEPLOYMENT", raising=False)
    return _FakeMain


def test_without_a_prompt_deployment_the_template_is_used_and_nothing_is_asked(fake_main, monkeypatch):
    def never(*_a):
        raise AssertionError("no chat call without APOLLO_COVER_PROMPT_DEPLOYMENT")
    monkeypatch.setattr(covers, "_ask_art_direction", never)
    covers.generate_generation_cover("t1", "neon rain at dawn", "aural")
    assert fake_main.seen["prompt"] is None
    assert fake_main.seen["name"] == "Neon Rain At Dawn"


def test_the_art_director_gets_the_song_and_the_genre_language_and_its_answer_becomes_the_prompt(fake_main, monkeypatch):
    monkeypatch.setenv("APOLLO_COVER_PROMPT_DEPLOYMENT", "gpt-4o-mini")
    asked = {}

    def fake_ask(deployment, system, user):
        asked.update(deployment=deployment, system=system, user=user)
        return "  A single paper lantern drifting over dark water at dawn,\n wide shot, amber and slate, gouache.  "

    monkeypatch.setattr(covers, "_ask_art_direction", fake_ask)
    covers.generate_generation_cover("t1", "neon rain at dawn, hypnotic", "aural")

    assert asked["deployment"] == "gpt-4o-mini"
    assert "Title: Neon Rain At Dawn" in asked["user"]
    assert "neon rain at dawn, hypnotic" in asked["user"]
    assert "Desert dunes or misty forest" in asked["user"], "the genre's mood reference"
    assert "OFF LIMITS" in asked["user"], "its objects are forbidden, not copied"
    assert "Kind of subject to use this time:" in asked["user"]
    assert "never any text" in asked["system"]
    assert "OFF LIMITS" in asked["system"]
    prompt = fake_main.seen["prompt"]
    assert prompt.startswith("A single paper lantern drifting over dark water at dawn, wide shot")
    assert prompt.endswith("No text or lettering in the image.")


def test_a_failed_or_empty_art_direction_falls_back_to_the_template(fake_main, monkeypatch):
    monkeypatch.setenv("APOLLO_COVER_PROMPT_DEPLOYMENT", "gpt-4o-mini")
    monkeypatch.setattr(covers, "_ask_art_direction", lambda *_a: (_ for _ in ()).throw(RuntimeError("429")))
    covers.generate_generation_cover("t1", "x", "aural")
    assert fake_main.seen["prompt"] is None

    monkeypatch.setattr(covers, "_ask_art_direction", lambda *_a: "ok")
    covers.generate_generation_cover("t2", "x", "aural")
    assert fake_main.seen["prompt"] is None, "a too-short answer is no answer"


def test_a_published_track_is_directed_from_the_takes_words_too(fake_main, monkeypatch):
    monkeypatch.setenv("APOLLO_COVER_PROMPT_DEPLOYMENT", "gpt-4o-mini")
    asked = {}
    monkeypatch.setattr(covers, "_ask_art_direction", lambda d, s, u: asked.update(user=u) or "A lone kite above a flooded rice terrace at first light, soft mist, celadon and gold, ink wash.")
    covers.generate_cover("aural--neon-rain", "Neon Rain", "aural", "neon rain at dawn")
    assert "Title: Neon Rain" in asked["user"]
    assert "neon rain at dawn" in asked["user"]
    assert fake_main.seen["prompt"].startswith("A lone kite")


def test_the_genre_style_descriptor_is_stripped_from_a_takes_words(monkeypatch):
    """A take's stored prompt is `<style>. <user words>`; the director must see the words."""
    import types, sys
    fake_tools = types.SimpleNamespace(genre_style_prompt=lambda g: "healing meditation music: slow binaural drones, no percussion" if g == "healing" else "")
    monkeypatch.setitem(sys.modules, "agent.tools", fake_tools)
    caption = "healing meditation music: slow binaural drones, no percussion. slow sounds to meditate on a garden"
    assert covers.user_words(caption, "Healing") == "slow sounds to meditate on a garden"
    assert covers.user_words("just the user's words", "healing") == "just the user's words"
    assert covers.user_words("healing meditation music: slow binaural drones, no percussion", "healing") == ""
    assert covers.user_words(None, "healing") == ""


def test_the_subject_kind_differs_between_songs_of_one_genre(fake_main, monkeypatch):
    monkeypatch.setenv("APOLLO_COVER_PROMPT_DEPLOYMENT", "gpt-4o-mini")
    kinds = []
    monkeypatch.setattr(covers, "_ask_art_direction", lambda d, s, u: kinds.append([l for l in u.splitlines() if l.startswith("Kind of subject")][0]) or "A long enough answer to be used as a prompt for the image.")
    for title in ("Xiexie Binaural", "Ethereal Beatless", "Green Sky Reflection", "Aural Black Sphera"):
        covers.art_direction(title, "", "aural")
    assert len(set(kinds)) >= 3, kinds
