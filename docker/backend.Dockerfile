# syntax=docker/dockerfile:1.7
#
# Backend image — FastAPI (Uvicorn) on :4020.
#
# Houses the Python pipeline + the web backend. The CLI commands
# (`python main.py --build-catalog`, `--fix-incomplete`, etc.) also work
# from this image since they share the same dependency surface — invoke
# them via ``docker compose run --rm backend uv run python main.py …``.
#
# Build args:
#   INSTALL_BEATGRID=1   — also install the optional ``beatgrid`` extra
#                          (madmom + cython, ~5 min, ~200 MB). Only needed
#                          for ``--build-catalog`` / ``--fix-incomplete``;
#                          the web app reads cached beatgrids from
#                          tracks.json and does NOT need madmom at runtime.

FROM python:3.12-slim-bookworm AS base

# System packages:
#   ffmpeg          — moviepy + librosa fallback decoders
#   rubberband-cli  — pyrubberband shells out to the ``rubberband`` binary
#   libsndfile1     — soundfile (the librosa reader)
#   build-essential — fallback for any wheel that needs a compiler
#                     (kept slim by --no-install-recommends + rm /var/lib/apt/lists)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ffmpeg \
        rubberband-cli \
        libsndfile1 \
        build-essential \
        git \
        ca-certificates \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# uv runs the whole project — install it once, keep it on PATH for the
# subsequent layers. Pin the major version so a future breaking release
# of uv doesn't silently change install semantics.
RUN pip install --no-cache-dir 'uv>=0.5,<1'

# UV_PROJECT_ENVIRONMENT redirects the virtualenv away from ``/app/.venv``.
# That matters because the dev compose bind-mounts the host project root
# to /app — if uv kept its default location, the host's Windows-built
# .venv would shadow the container's Linux venv and uvicorn would fail
# to import. By moving the venv to /opt/venv the bind-mount can't reach
# it, and the host's .venv just sits there harmlessly.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install Python deps first (cached layer) — only invalidates when the
# lockfile or pyproject change, not on every source edit.
#
# Groups:
#   --group web      → FastAPI / Uvicorn / JWT / bcrypt — always needed.
#   --group youtube  → google-api-python-client + google-auth — required
#                      for the YouTube Live Chat ingest path (otherwise
#                      ``youtube_runtime`` fails get_credentials with
#                      ``ModuleNotFoundError: No module named 'google'``
#                      and the poller silently never starts, leaving the
#                      pill stuck on ``disconnected`` regardless of
#                      whether the user has linked YouTube).
COPY pyproject.toml uv.lock ./
ARG INSTALL_BEATGRID=0
RUN if [ "$INSTALL_BEATGRID" = "1" ]; then \
        uv sync --group web --group youtube --extra beatgrid --frozen ; \
    else \
        uv sync --group web --group youtube --frozen ; \
    fi

# Source — overwritten by the bind mount at runtime, but COPY-ing it
# here means the image still works for one-off ``docker compose run
# --rm backend …`` invocations without the bind mount.
COPY . .

EXPOSE 4020

# --host 0.0.0.0 so the port is reachable from the compose network.
# --reload watches backend source only — without these excludes the
# watcher reloads on every catalog/audio/__pycache__ write and tears
# down live WebSocket sessions mid-mix (see RCA: 49 reloads + 2
# watchfiles crashes during a build-catalog run). Scope = web/ so
# tracks/, output/, artwork/, and the python bytecode cache are
# invisible to the watcher.
CMD ["uv", "run", "uvicorn", "backend.app:app", \
     "--host", "0.0.0.0", "--port", "4020", \
     "--app-dir", "web", "--reload", \
     "--reload-dir", "/app/web", \
     "--reload-dir", "/app/agent", \
     "--reload-exclude", "*__pycache__*", \
     "--reload-exclude", "*.pyc"]
