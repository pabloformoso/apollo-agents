"""Apollo's own copy of every finished take.

A take's audio used to live ONLY in ACE-Step's tmp directory and was only
reachable through ACE's ``/v1/audio`` endpoint — a choice made when Apollo
ran on Windows and ACE on another box, so HTTP was the one way to the file.
Since both run on jarvis that coupling only meant one thing: a take nobody
had published could not be played, scored or published while ACE was
stopped, which per the VRAM protocol is most of the time.

So the moment a take arrives, Apollo copies it here, and every reader
(the audio proxy, critique, publish, the edit's upload fallback) looks
here first. ACE is needed to GENERATE and to edit; a finished take is a
file.

Keyed by the BASENAME of the take's decoded ACE path: ACE names results
``<uuid>.wav``, so the basename is unique, and keeping ACE's name makes a
copy trivially traceable to its source. ``APOLLO_TAKES_DIR`` overrides
the location (read at CALL time, the generator's env rule).
"""
from __future__ import annotations

import os
import posixpath
import re
from pathlib import Path

ENV_TAKES_DIR = "APOLLO_TAKES_DIR"

#: ACE's result names, and nothing else: no separators, no dot-files.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*\.(wav|mp3|flac)$")


def takes_dir() -> Path:
    raw = (os.getenv(ENV_TAKES_DIR) or "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2] / "generations" / "takes"


def name_for(decoded_path: str | None) -> str | None:
    """The store's file name for a take, or ``None`` if it cannot have one."""
    if not decoded_path:
        return None
    name = posixpath.basename(decoded_path)
    return name if _SAFE_NAME.match(name) else None


def stored_path(decoded_path: str | None) -> Path:
    """Where the copy of ``decoded_path`` lives (whether or not it exists yet)."""
    name = name_for(decoded_path)
    if name is None:
        raise ValueError(f"not a take file name: {decoded_path!r}")
    return takes_dir() / name


def local_copy(decoded_path: str | None) -> Path | None:
    """The stored copy of a take, if Apollo has one."""
    if name_for(decoded_path) is None:
        return None
    path = stored_path(decoded_path)
    return path if path.is_file() else None


def staging_path(decoded_path: str) -> Path:
    """A ``.part`` sibling to write into, so a copy appears whole or not at all."""
    final = stored_path(decoded_path)
    final.parent.mkdir(parents=True, exist_ok=True)
    return final.with_name(final.name + ".part")
