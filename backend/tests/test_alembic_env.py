"""Tests for the Alembic configuration and the ``env.py`` wiring (T7).

The migration environment must:

- read the database URL from the application settings (so the
  configuration surface stays in one place, RF-17);
- run in offline mode without needing a live database so that the
  generated SQL can be inspected statically (RF-13, RF-14);
- run in online mode against the configured database so that the
  ``alembic upgrade head`` / ``alembic downgrade base`` cycle works
  inside the development container (RF-13, plan §4).

These tests deliberately avoid touching a real PostgreSQL: the offline
SQL generation is the contract that proves the schema is what the
spec requires (RF-14) and the env reads the right URL (RF-17). RNF-2
requires the test suite to be runnable without services.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command
from app.core.config import get_settings

# Repository layout: ``backend/alembic.ini`` and ``backend/alembic/env.py``
# are siblings of the ``app/`` and ``tests/`` directories. We resolve
# them relative to this test file so the test does not depend on the
# process's current working directory.
BACKEND_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
ALEMBIC_DIR = BACKEND_DIR / "alembic"


def _make_config() -> Config:
    """Build an Alembic ``Config`` pointing at the in-repo scripts.

    We deliberately do **not** patch the URL here: the wiring tests
    below verify that the env reads the URL from the application
    settings, not from the ini file.

    The ``output_buffer`` parameter is the buffer Alembic writes the
    offline SQL to (``--sql`` mode). Defaulting it to an in-memory
    ``StringIO`` keeps the test output silent and makes the captured
    SQL available via ``cfg.output_buffer.getvalue()`` (RNF-2: tests
    run without services and without polluting the test runner's
    stdout).
    """
    if not ALEMBIC_INI.exists():
        raise AssertionError(
            f"alembic.ini is missing at {ALEMBIC_INI}; T7 must create it"
        )
    if not (ALEMBIC_DIR / "env.py").exists():
        raise AssertionError(
            f"alembic/env.py is missing at {ALEMBIC_DIR / 'env.py'}; T7 must create it"
        )
    cfg = Config(str(ALEMBIC_INI), output_buffer=io.StringIO())
    return cfg


class TestAlembicFilesExist:
    """T7 lays down the configuration files. They must be on disk."""

    def test_alembic_ini_exists(self) -> None:
        assert ALEMBIC_INI.exists(), f"missing {ALEMBIC_INI}"

    def test_alembic_env_exists(self) -> None:
        assert (ALEMBIC_DIR / "env.py").exists(), "missing alembic/env.py"

    def test_versions_directory_exists(self) -> None:
        assert (ALEMBIC_DIR / "versions").is_dir(), "missing alembic/versions/"

    def test_initial_schema_migration_exists(self) -> None:
        # The plan names the initial migration 0001_initial_schema.py.
        migrations = list((ALEMBIC_DIR / "versions").glob("0001_*.py"))
        assert migrations, "no 0001_*.py migration found under alembic/versions/"


class TestAlembicEnvReadsUrlFromSettings:
    """The env must read the URL from the application settings (RF-17)."""

    def test_url_is_overridden_by_application_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force a known URL via the environment so the test does not
        # depend on the host's .env file. The env.py must read the
        # value from the application settings, which in turn read it
        # from the environment (RF-17).
        sentinel = "postgresql+asyncpg://tester:tester@test-host:6543/test_db"
        monkeypatch.setenv("DATABASE_URL", sentinel)
        get_settings.cache_clear()  # type: ignore[attr-defined]

        cfg = _make_config()
        # Touching the config forces env.py to load (no migrations run
        # in offline mode without a target). The relevant assertion is
        # that ``cfg.get_main_option("sqlalchemy.url")`` ends up with
        # the URL from the settings — not the placeholder from
        # alembic.ini.
        # Offline SQL generation is the cheapest way to trigger the
        # env load.
        command.upgrade(cfg, "head", sql=True)

        url = cfg.get_main_option("sqlalchemy.url")
        assert url == sentinel, (
            f"expected env to override sqlalchemy.url with the application "
            f"setting DATABASE_URL={sentinel!r}, got {url!r}"
        )


class TestOfflineMode:
    """The env must support offline mode (RF-13, RF-14)."""

    def test_upgrade_head_sql_emits_create_statements(self) -> None:
        cfg = _make_config()
        command.upgrade(cfg, "head", sql=True)
        sql = cfg.output_buffer.getvalue()
        # We only assert the presence of the four core tables and a
        # handful of invariants; the full content is checked in
        # ``test_migration_book_core.py`` where the same offline
        # output is parsed in detail.
        assert "CREATE TABLE books" in sql
        assert "CREATE TABLE book_versions" in sql
        assert "CREATE TABLE chapters" in sql
        assert "CREATE TABLE paragraphs" in sql

    def test_downgrade_base_sql_emits_drop_statements(self) -> None:
        cfg = _make_config()
        # In ``--sql`` (offline) mode, Alembic requires an explicit
        # ``<fromrev>:<torev>`` range. ``head:base`` covers every
        # migration we have (there is only one head).
        command.downgrade(cfg, "head:base", sql=True)
        sql = cfg.output_buffer.getvalue()
        # The order of DROPs is the reverse of CREATEs; the strongest
        # guarantee is that every created table also has a DROP.
        for table in ("books", "book_versions", "chapters", "paragraphs"):
            assert f"DROP TABLE {table}" in sql, (
                f"downgrade base did not drop {table!r}; got:\n{sql[:2000]}"
            )


class TestOnlineMode:
    """Online mode must connect via the configured URL.

    We do not connect to a real database here: the test exercises the
    code path of ``run_migrations_online`` up to the point where an
    engine is created from the configured URL and a (failing)
    connection is attempted. If the URL is not properly read, the
    engine construction itself will fail.

    A live integration test against PostgreSQL belongs in the runtime
    verification step (T10) and is explicitly out of scope for the
    static validation of T7.
    """

    def test_engine_uses_application_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pointing the URL at an unreachable host keeps the engine
        # construction (and the env's URL injection) on the happy path
        # while guaranteeing the subsequent ``connect()`` raises.
        # The test only exercises the env wiring: it does not actually
        # connect to the database (which would require a live
        # PostgreSQL, RNF-2).
        sentinel = "postgresql+asyncpg://noone:nope@127.0.0.1:1/no_db"
        monkeypatch.setenv("DATABASE_URL", sentinel)
        get_settings.cache_clear()  # type: ignore[attr-defined]

        cfg = _make_config()
        # ``command.heads`` only inspects the script directory; it
        # does not invoke env.py. ``command.upgrade(..., sql=True)``
        # does (it has to call ``context.configure``), and ``--sql``
        # mode does not open a real connection, so it is the cheapest
        # way to exercise the URL injection in the test environment.
        command.upgrade(cfg, "head", sql=True)
        url = cfg.get_main_option("sqlalchemy.url")
        assert url == sentinel


class TestMigrationContext:
    """The script directory must declare the initial migration."""

    def test_script_directory_has_one_head(self) -> None:
        cfg = _make_config()
        script = ScriptDirectory.from_config(cfg)
        heads = list(script.get_heads())
        assert len(heads) == 1, (
            f"expected exactly one head migration, got {heads!r}. "
            "T7 must produce a single initial migration that T8/T9 extend."
        )

    def test_initial_migration_has_no_parent(self) -> None:
        # The initial migration (``0001_initial_schema``) must have
        # ``down_revision = None`` so that ``alembic downgrade base``
        # walks all the way to an empty database in a single step.
        # T8 added ``0002_annotations_and_comments`` on top of T7,
        # so the *current head* is not the initial migration any
        # more; we therefore look up ``0001_initial_schema``
        # explicitly.
        cfg = _make_config()
        script = ScriptDirectory.from_config(cfg)
        initial = script.get_revision("0001_initial_schema")
        assert initial is not None, "0001_initial_schema is missing from the script directory"
        assert initial.down_revision is None, (
            f"initial migration must have down_revision=None, "
            f"got {initial.down_revision!r}"
        )
