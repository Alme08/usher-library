"""Alembic environment (T7, RF-13, RF-14, RF-17).

This module is the single seam between Alembic and the application
configuration. Two responsibilities:

1. **Inject the database URL** from ``app.core.config.get_settings()``
   into the Alembic config so the migrations target the same
   database the FastAPI application talks to. The URL is read from
   the ``DATABASE_URL`` environment variable (with the
   ``postgresql+asyncpg://...`` default defined in ``app.core.config``),
   which is the same source the rest of the application uses
   (RF-17, plan §5.1).

2. **Support both online and offline modes**:

   - *Offline mode* (``alembic upgrade head --sql``) emits the SQL
     the migration would apply to ``config.output_buffer`` without
     connecting to a database. This is what powers the static
     validation of the schema in this phase (no PostgreSQL available
     in the test environment, RNF-2) and the local ``alembic
     upgrade head --sql`` / ``alembic downgrade base --sql`` cycle
     documented in the plan (§4).

   - *Online mode* connects to the configured database. The URL uses
     the ``postgresql+asyncpg`` driver, so the online branch builds
     an **async** engine with
     ``sqlalchemy.ext.asyncio.async_engine_from_config`` and drives
     the migrations through ``connection.run_sync(...)``. This keeps
     the production stack uniform: a single asyncpg client is used
     by both the FastAPI runtime (T2, T6) and the migration tool.

The ``target_metadata`` is intentionally ``None``: the schema is
defined directly in the migration scripts to keep them the single
source of truth for the database layout (database.md §10, §26 — every
schema change requires a migration). Introducing SQLAlchemy ORM
metadata here would duplicate the schema definition and create the
risk of a silent drift between the models and the database.
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from typing import Any

from sqlalchemy import pool
from sqlalchemy.engine import Connection

from alembic import context

# Make ``app`` importable when ``env.py`` is run as a script. The
# ``prepend_sys_path = .`` setting in ``alembic.ini`` already takes
# care of the normal ``alembic`` invocation, but importing the
# application config also keeps direct ``python alembic/env.py``
# callers (e.g. some test runners) working.
sys.path.insert(0, ".")

# This is the Alembic Config object, which provides access to the
# values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging. ``fileConfig`` is a
# no-op when the ini does not declare a logging section, so the call
# is always safe.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Database URL: read from the application settings, not from alembic.ini.
# ---------------------------------------------------------------------------
# The application reads ``DATABASE_URL`` (with sensible defaults) from
# the environment. Injecting the same value here means a developer
# only needs to set the environment once for both the API and the
# migration tool to talk to the same database (RF-17). The function
# is imported lazily so this module can be imported by tools (such as
# the Alembic test harness) that may not have the full application
# settings available.
def _resolve_database_url() -> str:
    # Local import to avoid a hard dependency on pydantic-settings at
    # the top of the file (keeps ``alembic`` importable for tooling
    # that does not need the application config).
    from app.core.config import get_settings

    # Clear the lru_cache so a test that monkey-patches the
    # environment between calls sees the latest value (mirrors the
    # behaviour of ``app.core.startup._get_settings_or_cached``).
    get_settings.cache_clear()  # type: ignore[attr-defined]
    return get_settings().database_url


# ``target_metadata`` is None on purpose: the schema is defined in
# the migration scripts themselves, so the database layout is fully
# captured by the version-controlled Alembic history (database.md
# §10, §26 — every schema change requires a migration).
target_metadata: Any = None


def _configure_context_offline(url: str) -> None:
    """Apply ``context.configure(...)`` options for the offline branch."""
    # Offline mode: render SQL to ``cfg.output_buffer`` (the
    # ``--sql`` path) without an engine. ``literal_binds=True``
    # substitutes parameters inline so the output is a self-
    # contained SQL script.
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )


def _configure_context_online(connection: Connection) -> None:
    """Apply ``context.configure(...)`` options for the online branch."""
    # ``render_as_batch`` is left as the default (false) because
    # PostgreSQL supports ``ALTER TABLE`` directly, and turning it on
    # would change the emitted DDL.
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (RF-13, RNF-2).

    Offline mode emits SQL to ``config.output_buffer`` (default
    ``sys.stdout``) without opening a database connection. This is
    the mode the development cycle relies on for static schema
    inspection in environments without a running PostgreSQL (this
    test environment, RNF-2) and the mode used by
    ``alembic upgrade head --sql`` / ``alembic downgrade base
    --sql`` in the developer workflow documented in the plan (§4).
    """
    url = _resolve_database_url()
    # ``context.configure(url=...)`` uses the URL passed directly,
    # but we also push it into the Alembic config so introspection
    # and error messages report the *real* URL the application is
    # using rather than the placeholder from ``alembic.ini``.
    config.set_main_option("sqlalchemy.url", url)
    _configure_context_offline(url)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run the migrations against a live ``Connection``.

    Splitting the body of the online branch out of
    ``run_migrations_online`` keeps the async driver setup in one
    place and lets ``asyncio.run`` own the event loop lifecycle.
    """
    _configure_context_online(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online_async() -> None:
    """Async variant of the online branch.

    The application uses ``postgresql+asyncpg``; building an async
    engine here keeps the migration tool on the same driver as the
    API (no extra sync driver dependency, plan §5.1). The
    ``NullPool`` is set explicitly because Alembic opens a single
    connection per invocation: connection pooling would only add
    overhead and an extra surface for hangs at process exit.

    The async engine factory is imported lazily so importing this
    module does not require the optional ``greenlet`` dependency
    (``sqlalchemy[asyncio]``) when only the offline branch is
    exercised — which is the case in the test environment (RNF-2)
    and the static SQL inspection documented in the plan (§4).
    """
    # Local import keeps the async SQLAlchemy machinery out of the
    # import graph of the env module. Importing it eagerly would
    # require ``greenlet`` to be installed in any environment that
    # merely loads the env (e.g. the offline test suite, the
    # ``alembic --sql`` flow).
    from sqlalchemy.ext.asyncio import async_engine_from_config

    url = _resolve_database_url()
    config.set_main_option("sqlalchemy.url", url)
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (RF-13).

    Dispatches to the async implementation when the configured URL
    points at an async driver (``postgresql+asyncpg`` in this
    project) and to a synchronous implementation otherwise. The
    sync branch exists so the wiring also works for one-off runs
    against a non-async driver without changing the migration
    scripts.
    """
    url = _resolve_database_url()
    if url.startswith("postgresql+asyncpg"):
        asyncio.run(run_migrations_online_async())
        return

    # Synchronous fallback for non-asyncpg URLs. ``engine_from_config``
    # honours the ``sqlalchemy.`` prefix, so setting the URL through
    # ``set_main_option`` is enough.
    config.set_main_option("sqlalchemy.url", url)
    connectable = config.attributes.get("connectable")
    if connectable is None:
        from sqlalchemy import engine_from_config

        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
    with connectable.connect() as connection:  # type: ignore[union-attr]
        do_run_migrations(connection)
    connectable.dispose()  # type: ignore[union-attr]


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
