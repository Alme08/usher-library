# Backend development image for the Usher Library API.
#
# This is a DEVELOPMENT image (not production). It is intentionally not
# multi-stage and not size-optimized: the goal of T4 is to prove the
# application starts in isolation. Production hardening (multi-stage
# build, minimal runtime, dependency pinning, etc.) is out of scope for
# this spec and must be designed behind an ADR.
#
# Security posture (docs/architecture/security.md §28):
#   * runs as a non-root user
#   * exposes only the API port (BACKEND_PORT, 8000 by default)
#   * no privileged mode
#   * no Docker socket mounted
#   * no secrets baked in (configuration is injected via env at runtime)
#
# The entrypoint runs ``python -m app.core.startup``: that module waits
# for PostgreSQL and Redis with retries/backoff and a fixed total
# timeout (RF-7), inspects the database state, runs the Alembic guard
# RF-16, applies pending migrations when it is safe to do so
# (``alembic upgrade head``, RF-4) and only then ``exec``'s uvicorn
# against ``app.main:app``. If a dependency never comes up, the process
# exits non-zero and Docker Compose surfaces the failure with the
# dependency named in the log line.

# --- Runtime base -------------------------------------------------------------
FROM python:3.12-slim AS backend-dev

# Avoid pyc files and force unbuffered stdout/stderr so container logs are
# immediate. PIP_NO_CACHE_DIR keeps the image small; PIP_DISABLE_PIP_VERSION_CHECK
# avoids noisy upgrade hints on every install.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# `uvicorn[standard]` pulls in optional C-speed dependencies; build-essential
# is only needed while pip is compiling any wheels. `curl` is required by
# the Compose healthcheck (RF-9): the image ships its own lightweight HTTP
# probe so no extra tooling is needed inside the container. Removing the
# apt cache at the end of the RUN keeps the runtime lean without breaking
# installs.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && rm -rf /var/lib/apt/lists/*

# --- Application layout ------------------------------------------------------
WORKDIR /app

# Install Python dependencies first so the layer is cached as long as the
# manifest does not change. `[dev]` extras include pytest and ruff, which is
# useful for running the test suite inside the container (RNF-2: tests must
# run inside a container, not on the host).
COPY pyproject.toml ./
RUN pip install --upgrade pip \
 && pip install -e ".[dev]"

# Copy the application source. A `.dockerignore` keeps build context lean and
# avoids leaking `.env`, caches and local virtualenvs into the image.
COPY app ./app
COPY tests ./tests

# --- Non-root user ------------------------------------------------------------
# Create an unprivileged user and hand ownership of the working directory to
# it. Switching to it before `CMD` satisfies the "non-root where practical"
# guideline (security §28) without breaking editable installs.
RUN useradd --create-home --shell /bin/bash --uid 10001 appuser \
 && chown -R appuser:appuser /app
USER appuser

# --- Network ------------------------------------------------------------------
# The default uvicorn port matches the development default in `.env.example`;
# the value can be overridden at runtime by setting `BACKEND_PORT`. The
# Compose healthcheck (RF-9) targets the same port from inside the container.
EXPOSE 8000

# --- Entrypoint ---------------------------------------------------------------
# ``python -m app.core.startup`` waits for the configured dependencies
# (PostgreSQL and Redis) with exponential backoff and a fixed total timeout
# (RF-7), inspects the database state, runs the Alembic guard RF-16, applies
# pending migrations when it is safe to do so (``alembic upgrade head``,
# RF-4), and then ``exec``'s uvicorn against the module-level ``app``
# instance declared in ``app/main.py``. The host and port are read from the
# `BACKEND_HOST` and `BACKEND_PORT` environment variables so the same image
# works with any host port mapping (RF-5, RF-8). `--proxy-headers` is
# harmless locally and matches what a reverse proxy would expect later.
# `--reload` is intentionally OFF in the container: source is baked into
# the image at build time (the Compose file does not bind-mount it), and
# turning reload on would require file-system write permissions the
# non-root user does not have.
CMD ["python", "-m", "app.core.startup"]
