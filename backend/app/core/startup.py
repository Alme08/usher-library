"""Backend startup helpers: wait for dependencies with retries (RF-7).

When the backend container starts it must not assume that PostgreSQL
or Redis are *already* accepting connections: in practice they take
a few seconds to come up, and the readiness ordering produced by
Compose `depends_on: condition: service_healthy` is a useful but not
absolute guarantee.

This module provides a tiny, dependency-free helper that retries a
probe with exponential backoff and a hard total timeout. When the
timeout elapses the helper raises a `DependencyUnavailableError`
that *identifies the dependency* by name and records the last
encountered error. The backend entrypoint catches that error,
emits a single structured log line and exits non-zero so Docker
Compose surfaces the failure with the name of the offending
dependency (RF-7, RF-8).

After the dependency probes succeed, the entrypoint inspects the
PostgreSQL database and asks the migration guard what to do
(``decideMigrationAction`` in ``app.domain.migration_guard``).
For empty or already-migrated databases it runs
``alembic upgrade head`` automatically (RF-4); for databases that
contain user tables but no ``alembic_version`` it aborts with a
clear log line and a non-zero exit code, leaving the schema and the
data untouched (RF-16). Only after the migration step does the
process hand off to uvicorn.

The helper takes an injectable `sleep` callable so the behaviour
is fully unit-testable without touching the wall clock (RNF-2).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# Imported eagerly here because ``app.domain.migration_guard`` only
# contains pure data classes and a literal-typed function (no I/O,
# no framework dependencies). Bringing the import to module level
# keeps ``_amain`` readable and lets type checkers resolve the
# return type of ``decideMigrationAction`` without a forward
# reference.
from app.domain.migration_guard import (
    DbState,
    decideMigrationAction,
)

# A probe returns True when the dependency is reachable. Anything
# else (False, exception) is treated as "not ready yet".
Probe = Callable[[], Awaitable[bool]]


# A `SleepFn` is just `asyncio.sleep` typed for injection. Tests pass
# a recorder so they do not have to wait for real time.
SleepFn = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class DependencyUnavailableError(Exception):
    """Raised when a dependency never became available.

    Attributes:
        dependency: Human-readable name of the dependency that never
            came up (e.g. ``"postgres"``). The name is required by
            RF-7 so the entrypoint log identifies the cause.
        attempts: Number of probe attempts performed before giving up.
        elapsed_seconds: Wall-clock time spent waiting.
        last_error: Optional stringified form of the last exception
            raised by the probe (or ``"probe returned False"`` when
            the probe declined without raising). Useful for debugging.
    """

    dependency: str
    attempts: int
    elapsed_seconds: float
    last_error: str | None

    def __str__(self) -> str:  # noqa: D401 - Exception __str__ override
        message = (
            f"dependency unavailable: {self.dependency} "
            f"(attempts={self.attempts}, elapsed={self.elapsed_seconds:.1f}s"
        )
        if self.last_error:
            message += f", last_error={self.last_error}"
        return message


# Defaults chosen so that with a 30s overall budget we get a useful
# schedule (0.5, 1, 2, 4, 8, capped at 5) without flooding the log
# during the typical Compose start window.
_DEFAULT_INITIAL_DELAY: Final[float] = 0.5
_DEFAULT_MAX_DELAY: Final[float] = 5.0
_DEFAULT_BACKOFF_FACTOR: Final[float] = 2.0


async def wait_for_dependency(
    name: str,
    probe: Probe,
    *,
    timeout_seconds: float,
    initial_delay: float = _DEFAULT_INITIAL_DELAY,
    max_delay: float = _DEFAULT_MAX_DELAY,
    backoff_factor: float = _DEFAULT_BACKOFF_FACTOR,
    sleep: SleepFn = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Wait until ``probe()`` returns True.

    The probe is called repeatedly with exponential backoff between
    attempts. The function returns as soon as the probe reports
    success, and raises :class:`DependencyUnavailableError` if the
    probe never succeeds within ``timeout_seconds` of wall-clock
    time. The final scheduled delay is clamped to the remaining
    budget so the total wait never silently exceeds the cap.

    Args:
        name: Dependency identifier used in logs and error messages
            (e.g. ``"postgres"``).
        probe: Awaitable that returns ``True`` when the dependency is
            ready. Raising any exception is treated as "not ready".
        timeout_seconds: Total time budget for waiting.
        initial_delay: Delay before the second probe attempt.
        max_delay: Cap on the per-attempt delay.
        backoff_factor: Multiplicative growth factor between attempts.
        sleep: Awaitable used to wait between attempts; injected so
            tests can record the schedule without sleeping.
        clock: Callable returning the current monotonic time. Injected
            so tests can drive the wait deterministically (RNF-2).

    Raises:
        DependencyUnavailableError: when the probe never reports
            success within ``timeout_seconds``.
    """
    if timeout_seconds <= 0:
        # Negative or zero budget cannot yield success; fail fast so
        # the entrypoint does not busy-loop.
        raise DependencyUnavailableError(
            dependency=name,
            attempts=0,
            elapsed_seconds=0.0,
            last_error="timeout_seconds must be positive",
        )

    start = clock()
    delay = initial_delay
    attempt = 0
    last_error: str | None = None

    while True:
        attempt += 1
        try:
            ok = await probe()
        except Exception as exc:  # noqa: BLE001 - intentionally broad
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if ok:
                return
            last_error = "probe returned False"

        elapsed = clock() - start
        if elapsed >= timeout_seconds:
            raise DependencyUnavailableError(
                dependency=name,
                attempts=attempt,
                elapsed_seconds=elapsed,
                last_error=last_error,
            )

        # Clamp the delay to the remaining budget so the loop never
        # overshoots the timeout on its very last sleep.
        remaining = max(timeout_seconds - elapsed, 0.0)
        await sleep(min(delay, remaining))

        delay = min(delay * backoff_factor, max_delay)


# ---------------------------------------------------------------------------
# Entrypoint glue
# ---------------------------------------------------------------------------
#
# When the module is invoked as ``python -m app.core.startup`` (the
# default ``CMD`` for the backend development image), the block below
# waits for the configured dependencies and then ``exec``\u2019s the
# production ASGI server. The wait happens *before* uvicorn binds to
# its port, so a host port collision (RF-8) is reported by Compose
# with the offending service named; a dependency outage (RF-7) is
# reported by *this* module as a structured log line naming the
# dependency, and the process exits with a non-zero code so Compose
# marks the container as failed.
#
# Auto-migration is intentionally NOT wired here. T7–T10 will introduce
# Alembic; until then the entrypoint stays minimal and the dependency
# wait is the only side effect.


# ---------------------------------------------------------------------------
# Migration inspection + guard (RF-4, RF-16)
# ---------------------------------------------------------------------------
#
# After the dependency probes succeed we know PostgreSQL is reachable,
# but we do not yet know whether the schema has been initialised. The
# migration guard (``app.domain.migration_guard.decideMigrationAction``)
# decides what to do next. We split the work in two pieces:
#
#   1. ``_inspect_db_state`` connects to PostgreSQL with ``asyncpg`` and
#      reads two booleans from the live database: does
#      ``alembic_version`` exist? Are there any *user* tables? This is
#      the only place where the entrypoint touches the application
#      schema directly; everything else goes through the guard.
#
#   2. ``_run_alembic_upgrade`` is the synchronous wrapper around
#      ``alembic.command.upgrade(cfg, "head")`` that we run on the
#      ``"apply"`` branch. It is invoked through ``asyncio.to_thread``
#      from the async entrypoint so the event loop stays responsive.
#
# Both functions are module-level and intentionally easy to patch in
# tests; the suite injects fakes so the test runner never needs a real
# PostgreSQL (RNF-2).


# SQL: check whether a table exists in the ``public`` schema. The
# query goes against ``pg_catalog`` so we do not depend on having
# access to any user tables.
_ALEMBIC_VERSION_EXISTS_SQL = (
    "SELECT EXISTS ("
    "  SELECT 1 FROM pg_catalog.pg_class c"
    "  JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace"
    "  WHERE c.relkind IN ('r', 'p')"
    "    AND c.relname = 'alembic_version'"
    "    AND n.nspname = 'public'"
    ")"
)

# SQL: count the *user* tables (i.e. everything except
# ``alembic_version``) in the ``public`` schema. The query is written
# against ``pg_catalog`` so it works even when the schema is empty.
_USER_TABLE_COUNT_SQL = (
    "SELECT COUNT(*) FROM pg_catalog.pg_class c"
    " JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace"
    " WHERE c.relkind IN ('r', 'p')"
    "   AND n.nspname = 'public'"
    "   AND c.relname <> 'alembic_version'"
)


# Repository layout: ``backend/alembic.ini`` sits next to ``app/`` and
# ``tests/``. Resolving it relative to this file keeps the entrypoint
# runnable from any working directory, which matters for the
# ``python -m app.core.startup`` invocation in the Dockerfile.
_BACKEND_DIR: Final[Path] = Path(__file__).resolve().parent.parent.parent
_ALEMBIC_INI: Final[Path] = _BACKEND_DIR / "alembic.ini"


@dataclass(frozen=True)
class MigrationUpgradeError(Exception):
    """Raised when ``alembic upgrade head`` fails.

    Attributes:
        revision: The Alembic revision we tried to reach (always
            ``"head"`` in this entrypoint).
        last_error: The stringified form of the underlying exception
            raised by Alembic. Kept as a string so the entrypoint log
            can render it without re-raising.
    """

    revision: str
    last_error: str


async def _inspect_db_state(settings) -> DbState:
    """Read the database state the migration guard consumes (RF-16).

    The function opens an ``asyncpg`` connection against the configured
    PostgreSQL instance and runs two cheap ``pg_catalog`` queries:
    one to detect the ``alembic_version`` table, one to count any
    other tables in the ``public`` schema. The result feeds the guard
    in ``app.domain.migration_guard``.

    The asyncpg import is lazy: the helpers in this file are only called
    from the live entrypoint, never the test suite, so a missing asyncpg
    installation never breaks the offline ``pytest`` run (RNF-2).

    Args:
        settings: The application settings; used for the connection
            parameters (``postgres_host``/``postgres_port``/...).

    Returns:
        A ``DbState`` reflecting what ``alembic_version`` and user
        tables look like right now.

    Raises:
        asyncpg.PostgresError / OSError / asyncio.TimeoutError: when
            the database cannot be reached. The entrypoint treats
            these as "dependency unavailable: postgres", mirroring
            the existing dependency wait.
    """
    # Local import: the helper runs only inside the container, where
    # ``asyncpg`` is installed. Importing at module top would force
    # the offline test suite to depend on it.
    import asyncpg

    connection = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database=settings.postgres_db,
        timeout=settings.probe_timeout_seconds,
    )
    try:
        has_alembic_version = bool(
            await connection.fetchval(_ALEMBIC_VERSION_EXISTS_SQL)
        )
        user_table_count = int(
            await connection.fetchval(_USER_TABLE_COUNT_SQL)
        )
    finally:
        await connection.close()

    return DbState(
        hasAlembicVersion=has_alembic_version,
        hasUserTables=user_table_count > 0,
    )


def _run_alembic_upgrade(settings) -> None:
    """Synchronous wrapper around ``alembic upgrade head`` (RF-4).

    The function builds an Alembic ``Config`` pointing at the
    ``alembic.ini`` of this backend, lets ``env.py`` inject the URL
    from the application settings, and runs ``upgrade head``. The
    connection settings are read at process start-up; the migration
    targets the same database the application will serve.

    The function raises :class:`MigrationUpgradeError` with the
    stringified cause when Alembic fails. The entrypoint logs the
    error and exits non-zero so Docker Compose marks the container
    as failed (RF-8).

    Args:
        settings: The application settings (currently only used to
            force a re-read of the cached ``Settings`` instance so
            monkey-patched environment variables are honoured).
    """
    # Imported lazily so importing this module never requires Alembic
    # at test-collection time (RNF-2).
    from alembic.config import Config

    from alembic import command

    try:
        cfg = Config(str(_ALEMBIC_INI))
        command.upgrade(cfg, "head")
    except Exception as exc:  # noqa: BLE001 - log full cause
        raise MigrationUpgradeError(
            revision="head",
            last_error=f"{type(exc).__name__}: {exc}",
        ) from exc


logger = logging.getLogger("app.core.startup")


async def _probe_postgres_alive() -> bool:
    """Lightweight readiness probe used only at startup.

    The function intentionally mirrors :func:`check_postgres` from the
    infrastructure layer so the readiness signal matches what ``/health``
    would report. Any failure is converted into ``False``; the helper
    does not raise.
    """
    # Imported lazily so importing this module never requires
    # asyncpg/redis at test-collection time.
    from app.infrastructure.probes import check_postgres

    settings = _get_settings_or_cached()
    result = await check_postgres(settings)
    return result.ok


async def _probe_redis_alive() -> bool:
    """Lightweight readiness probe used only at startup (see above)."""
    from app.infrastructure.probes import check_redis

    settings = _get_settings_or_cached()
    result = await check_redis(settings)
    return result.ok


def _get_settings_or_cached():
    """Return the cached `Settings` instance, falling back to a fresh one.

    The wrapper exists so test suites that monkey-patch environment
    variables between imports still see the patched values.
    """
    from app.core.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]
    return get_settings()


async def _wait_for_all(settings) -> None:
    """Wait for PostgreSQL and Redis with the configured schedule (RF-7).

    Raises:
        DependencyUnavailableError: when any dependency never comes
            up. The error identifies the dependency by name and
            records the last observed failure cause.
    """
    await wait_for_dependency(
        "postgres",
        _probe_postgres_alive,
        timeout_seconds=settings.startup_timeout_seconds,
        initial_delay=settings.startup_initial_delay,
        max_delay=settings.startup_max_delay,
        backoff_factor=settings.startup_backoff_factor,
    )
    await wait_for_dependency(
        "redis",
        _probe_redis_alive,
        timeout_seconds=settings.startup_timeout_seconds,
        initial_delay=settings.startup_initial_delay,
        max_delay=settings.startup_max_delay,
        backoff_factor=settings.startup_backoff_factor,
    )


def _configure_logging() -> None:
    """Configure a minimal, line-oriented log format for container logs.

    The backend does not configure logging yet (it stays inside uvicorn
    once we hand off). This entrypoint needs to surface the
    "dependency unavailable" message clearly, which is why we configure
    logging here rather than relying on uvicorn's defaults.
    """
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _exec_uvicorn(settings) -> None:
    """Replace the current process with uvicorn via ``os.execvp``.

    ``exec`` keeps PID 1 in the container, so Docker signals (SIGTERM
    from Compose on shutdown) reach uvicorn directly without an extra
    layer of signal forwarding.
    """
    args = [
        "uvicorn",
        "app.main:app",
        "--host",
        settings.backend_host,
        "--port",
        str(settings.backend_port),
        "--proxy-headers",
    ]
    logger.info("Starting uvicorn on %s:%s", settings.backend_host, settings.backend_port)
    os.execvp(args[0], args)


async def _amain() -> int:
    """Async entrypoint: wait for deps, decide migration, hand off to uvicorn.

    Returns the process exit code (0 on success, non-zero on failure).
    """
    settings = _get_settings_or_cached()
    try:
        await _wait_for_all(settings)
    except DependencyUnavailableError as exc:
        # Log a single line that names the dependency and the last
        # observed failure cause so a developer can act on it (RF-7,
        # RF-8). The message is the contract relied upon by the
        # acceptance criteria of T6.
        logger.error(
            "dependency unavailable: %s after %.1fs (%d attempts); last_error=%s",
            exc.dependency,
            exc.elapsed_seconds,
            exc.attempts,
            exc.last_error,
        )
        return 1

    # Migration step (RF-4, RF-16). The guard reads two booleans from
    # the database (``hasAlembicVersion``, ``hasUserTables``) and
    # decides whether to apply migrations, skip them or abort the
    # start-up. The ``_inspect_db_state`` helper is async (it uses
    # ``asyncpg``); the guard itself is a pure function in the
    # domain layer.
    db_state = await _inspect_db_state(settings)
    action = decideMigrationAction(db_state)

    if action == "abort":
        # The dangerous state: tables without history. RF-16 forbids
        # auto-migration here. Log a single, clear line so the
        # developer knows exactly what to do next ("stamp head" to
        # baseline the schema, or wipe the volume and restart).
        logger.error(
            "refusing to auto-migrate: database has user tables "
            "but no alembic_version; inspect the volume and either "
            "run 'alembic stamp head' to baseline the schema or "
            "drop the conflicting tables before restarting"
        )
        return 2

    if action == "apply":
        # Run Alembic in a worker thread so the synchronous driver
        # does not block the event loop. ``asyncio.to_thread`` keeps
        # the exception chain intact and lets the ``except`` branch
        # below observe the real cause.
        try:
            await asyncio.to_thread(_run_alembic_upgrade, settings)
        except MigrationUpgradeError as exc:
            logger.error(
                "migration failed: alembic upgrade %s; last_error=%s",
                exc.revision,
                exc.last_error,
            )
            return 3
        logger.info("migrations applied successfully")

    # ``action == "skip"`` falls through: there is nothing to do, so
    # uvicorn starts immediately.

    _exec_uvicorn(settings)
    # `os.execvp` does not return on success, so the line below is
    # only reached if the exec itself fails.
    return 0


def main() -> int:
    """Synchronous entrypoint invoked by ``python -m app.core.startup``."""
    _configure_logging()
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
