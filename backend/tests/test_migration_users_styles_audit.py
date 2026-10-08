"""Tests for the users / reference styles / audit_events migration ``0003_*.py`` (T9).

These tests verify that the third Foundation migration is structurally
correct and that the rendered offline SQL contains the tables, columns,
constraints and indexes that ``docs/architecture/database.md`` (§4, §5,
§17) prescribes for the social / identity machinery of the application:

* ``handwriting_fonts``, ``ink_styles``, ``paper_textures`` (§5) — the
  three reference-style tables.
* ``users`` (§4) — the application user, with FKs into the three style
  tables and a unique ``keycloak_subject`` mapping the external identity
  to the application row.
* ``audit_events`` (§17) — the append-only ledger of administrative
  actions.

The migration also closes a debt left by T8
(``0002_annotations_and_comments``): the ``user_id`` columns on
``annotations`` and ``comments`` were created without an FK because
``users`` did not exist yet. T9 adds the two FKs via
``op.create_foreign_key`` so the database enforces referential integrity
on the application user.

The tests do not need a live database (RNF-2): Alembic's offline mode
produces the SQL we assert against.

T9 closes the "Initial Schema" of ``docs/architecture/database.md``
§30: every table in that list is present in ``alembic upgrade head
--sql`` after T9.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

# Repository layout: the migrations live under
# ``backend/alembic/versions/``.
BACKEND_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
VERSIONS_DIR = BACKEND_DIR / "alembic" / "versions"
MIGRATION_FILE = next(iter(VERSIONS_DIR.glob("0003_*.py")), None)
# Read the migration file once at module import time so the file-shape
# tests do not depend on a class-scoped fixture (deprecated in
# pytest-asyncio for instance methods, see PytestRemovedIn10Warning).
_MIGRATION_SOURCE = (
    MIGRATION_FILE.read_text(encoding="utf-8") if MIGRATION_FILE else ""
)


def _make_config() -> Config:
    """Build an Alembic ``Config`` pointing at the in-repo scripts.

    The ``output_buffer`` parameter is the buffer Alembic writes the
    offline SQL to (``--sql`` mode). Defaulting it to an in-memory
    ``StringIO`` keeps the test output silent and makes the captured
    SQL available via ``cfg.output_buffer.getvalue()`` (RNF-2).
    """
    cfg = Config(str(ALEMBIC_INI), output_buffer=io.StringIO())
    return cfg


def _offline_sql(revision: str = "head", target: str = "upgrade") -> str:
    """Render the offline SQL for ``upgrade`` or ``downgrade``.

    The function returns the SQL captured in ``cfg.output_buffer`` so
    the tests can assert on the statements Alembic would emit against
    a real database without ever connecting to one.
    """
    cfg = _make_config()
    if target == "upgrade":
        command.upgrade(cfg, revision, sql=True)
    else:
        command.downgrade(cfg, revision, sql=True)
    return cfg.output_buffer.getvalue()


# Module-level SQL captures avoid class-scoped fixtures while still
# caching the rendered SQL so the assertion classes are cheap to run.
_UPGRADE_SQL = _offline_sql("head", "upgrade")
_DOWNGRADE_SQL = _offline_sql("head:base", "downgrade")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_create_table(sql: str, table_name: str) -> str:
    """Return the slice of ``sql`` that defines ``CREATE TABLE <table_name>``.

    The helper locates the opening ``CREATE TABLE <table_name>`` and
    returns the SQL up to (but not including) the next ``CREATE TABLE``
    or the end of the buffer. This is enough to assert on column,
    constraint and index clauses emitted by Alembic for a single
    table without pulling in a full SQL parser.
    """
    needle = f"CREATE TABLE {table_name}"
    start = sql.find(needle)
    if start < 0:
        pytest.fail(f"CREATE TABLE for {table_name!r} not found in offline SQL")
    # Walk forward to the closing ``);`` that ends the CREATE TABLE.
    depth = 0
    for i in range(start, len(sql)):
        ch = sql[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                # Include the trailing newline so the slice is self-
                # contained.
                end = sql.find("\n", i)
                if end < 0:
                    end = len(sql)
                return sql[start:end]
    pytest.fail(f"unterminated CREATE TABLE for {table_name!r} in offline SQL")


# ---------------------------------------------------------------------------
# File-shape tests
# ---------------------------------------------------------------------------


class TestMigrationFileShape:
    """The migration file must have a stable, predictable shape."""

    def test_migration_file_exists(self) -> None:
        assert MIGRATION_FILE is not None, "0003_*.py migration not found"

    def test_migration_declares_revision_id(self) -> None:
        # The revision id must match the file name so a developer can
        # navigate from one to the other.
        assert (
            'revision: str = "0003_users_styles_audit"' in _MIGRATION_SOURCE
        ), (
            "expected 'revision: str = \"0003_users_styles_audit\"' "
            "in the migration"
        )

    def test_migration_down_revision_is_t8(self) -> None:
        # T9 chains on T8 (``0002_annotations_and_comments``).
        assert (
            'down_revision: str | None = "0002_annotations_and_comments"'
            in _MIGRATION_SOURCE
        ), (
            "T9 must declare down_revision = \"0002_annotations_and_comments\" "
            "so it chains on T8"
        )

    def test_migration_has_upgrade_and_downgrade(self) -> None:
        assert "def upgrade() -> None:" in _MIGRATION_SOURCE
        assert "def downgrade() -> None:" in _MIGRATION_SOURCE

    def test_migration_uses_op_create_table(self) -> None:
        # Alembic is a thin wrapper over ``op.*``; we expect every
        # CREATE to be expressed through ``op.create_table`` so the
        # migration is reversible.
        assert "op.create_table" in _MIGRATION_SOURCE
        assert "op.drop_table" in _MIGRATION_SOURCE

    def test_migration_uses_op_create_foreign_key(self) -> None:
        # The deferred FKs from T8 (``annotations.user_id`` and
        # ``comments.user_id``) are added here with
        # ``op.create_foreign_key`` because the column already exists
        # (T8 created it) and the ``users`` table is now available.
        assert "op.create_foreign_key" in _MIGRATION_SOURCE, (
            "T9 must add the FKs deferred from T8 via op.create_foreign_key"
        )

    def test_migration_documents_t8_fk_debt(self) -> None:
        # The migration should make the T8 FK debt explicit so a
        # reviewer knows the ALTER TABLE statements are closing a
        # previously documented decision (the docstring of T8 says so).
        # We accept the rationale being in either the docstring or
        # the upgrade body, but at minimum the words must appear.
        text = _MIGRATION_SOURCE
        assert "T8" in text, (
            "the migration should reference T8 because it closes the FK debt "
            "from 0002_annotations_and_comments"
        )
        assert (
            "annotations.user_id" in text or "annotations\\.user_id" in text
        ), "the migration should mention annotations.user_id"
        assert (
            "comments.user_id" in text or "comments\\.user_id" in text
        ), "the migration should mention comments.user_id"


# ---------------------------------------------------------------------------
# Upgrade SQL: reference style tables (§5)
# ---------------------------------------------------------------------------


class TestUpgradeSqlContainsReferenceStyleTables:
    """``alembic upgrade head --sql`` must contain the three style tables."""

    @pytest.mark.parametrize(
        "table",
        ["handwriting_fonts", "ink_styles", "paper_textures"],
    )
    def test_creates_style_table(self, table: str) -> None:
        assert f"CREATE TABLE {table}" in _UPGRADE_SQL, (
            f"expected CREATE TABLE {table} in offline SQL (database.md §5)"
        )

    @pytest.mark.parametrize(
        "table",
        ["handwriting_fonts", "ink_styles", "paper_textures"],
    )
    def test_style_table_id_is_uuid_primary_key(self, table: str) -> None:
        block = _extract_create_table(_UPGRADE_SQL, table)
        assert "id" in block
        assert "UUID" in block
        assert "PRIMARY KEY" in block

    @pytest.mark.parametrize(
        "table",
        ["handwriting_fonts", "ink_styles", "paper_textures"],
    )
    def test_style_table_slug_unique_not_null(self, table: str) -> None:
        # §5: ``slug UNIQUE``. The constraint name follows the
        # project's ``uq_<table>_<column>`` convention.
        block = _extract_create_table(_UPGRADE_SQL, table)
        assert "slug" in block, f"{table}: slug column missing"
        assert "UNIQUE" in block, f"{table}: UNIQUE constraint missing"
        assert "NOT NULL" in block, f"{table}: slug NOT NULL missing"
        assert (
            f"uq_{table}_slug" in block
        ), f"{table}: expected unique constraint name uq_{table}_slug"

    @pytest.mark.parametrize(
        "table",
        ["handwriting_fonts", "ink_styles", "paper_textures"],
    )
    def test_style_table_required_columns(self, table: str) -> None:
        # §5: display_name, asset_path, is_active, created_at are
        # all listed in the spec. ``is_active`` is a boolean that the
        # application toggles; ``created_at`` is a TIMESTAMPTZ.
        block = _extract_create_table(_UPGRADE_SQL, table)
        assert "display_name" in block
        assert "asset_path" in block
        assert "is_active" in block
        assert "created_at" in block
        assert "TIMESTAMP WITH TIME ZONE" in block


# ---------------------------------------------------------------------------
# Upgrade SQL: users (§4)
# ---------------------------------------------------------------------------


class TestUpgradeSqlContainsUsers:
    """``alembic upgrade head --sql`` must contain the ``users`` table."""

    def test_creates_users(self) -> None:
        assert "CREATE TABLE users" in _UPGRADE_SQL

    def test_users_id_is_uuid_primary_key(self) -> None:
        block = _extract_create_table(_UPGRADE_SQL, "users")
        assert "id" in block
        assert "UUID" in block
        assert "PRIMARY KEY" in block

    def test_users_keycloak_subject_unique_not_null(self) -> None:
        # §4: ``keycloak_subject`` is the bridge from Keycloak's
        # subject identifier to the application row. It is UNIQUE
        # and NOT NULL.
        block = _extract_create_table(_UPGRADE_SQL, "users")
        assert "keycloak_subject" in block
        assert "NOT NULL" in block
        assert "uq_users_keycloak_subject" in block, (
            "expected unique constraint name uq_users_keycloak_subject"
        )

    def test_users_username_unique_not_null(self) -> None:
        # §4: ``username`` is the human-facing handle. UNIQUE and
        # NOT NULL.
        block = _extract_create_table(_UPGRADE_SQL, "users")
        assert "username" in block
        assert "NOT NULL" in block
        assert "uq_users_username" in block, (
            "expected unique constraint name uq_users_username"
        )

    def test_users_display_name_not_null(self) -> None:
        # §4: ``display_name`` is the user-visible name.
        block = _extract_create_table(_UPGRADE_SQL, "users")
        assert "display_name" in block
        assert "NOT NULL" in block

    def test_users_role_check(self) -> None:
        # §4: ``role`` is restricted to ``READER`` and ``ADMIN``.
        block = _extract_create_table(_UPGRADE_SQL, "users")
        assert "role" in block
        assert "ck_users_role" in block
        assert re.search(
            r"role IN \('READER', 'ADMIN'\)", block
        ) is not None

    def test_users_status_check(self) -> None:
        # §4: ``status`` is restricted to ``active`` and
        # ``suspended``.
        block = _extract_create_table(_UPGRADE_SQL, "users")
        assert "status" in block
        assert "ck_users_status" in block
        assert re.search(
            r"status IN \('active', 'suspended'\)", block
        ) is not None

    def test_users_references_handwriting_fonts(self) -> None:
        # §4 / §5: ``handwriting_font_id`` references
        # ``handwriting_fonts.id``.
        block = _extract_create_table(_UPGRADE_SQL, "users")
        assert "handwriting_font_id" in block
        assert "REFERENCES handwriting_fonts" in block

    def test_users_references_ink_styles(self) -> None:
        block = _extract_create_table(_UPGRADE_SQL, "users")
        assert "ink_style_id" in block
        assert "REFERENCES ink_styles" in block

    def test_users_references_paper_textures(self) -> None:
        block = _extract_create_table(_UPGRADE_SQL, "users")
        assert "paper_texture_id" in block
        assert "REFERENCES paper_textures" in block

    def test_users_has_timestamps(self) -> None:
        # §4: created_at and updated_at.
        block = _extract_create_table(_UPGRADE_SQL, "users")
        assert "created_at" in block
        assert "updated_at" in block
        assert "TIMESTAMP WITH TIME ZONE" in block


# ---------------------------------------------------------------------------
# Upgrade SQL: audit_events (§17)
# ---------------------------------------------------------------------------


class TestUpgradeSqlContainsAuditEvents:
    """``alembic upgrade head --sql`` must contain the ``audit_events`` table."""

    def test_creates_audit_events(self) -> None:
        assert "CREATE TABLE audit_events" in _UPGRADE_SQL

    def test_audit_events_id_is_uuid_primary_key(self) -> None:
        block = _extract_create_table(_UPGRADE_SQL, "audit_events")
        assert "id" in block
        assert "UUID" in block
        assert "PRIMARY KEY" in block

    def test_audit_events_actor_user_id_nullable_fk(self) -> None:
        # §17: ``actor_user_id`` is nullable and references ``users``.
        block = _extract_create_table(_UPGRADE_SQL, "audit_events")
        assert "actor_user_id" in block
        assert "REFERENCES users" in block
        # Nullable: the column declaration does not include
        # ``NOT NULL``. We accept either an unadorned ``UUID`` or a
        # ``UUID NULL``.
        assert re.search(
            r"actor_user_id\s+UUID(\s+NULL)?,", block
        ) is not None, "actor_user_id must be nullable"

    def test_audit_events_has_required_columns(self) -> None:
        # §17: ``action`` and ``target_type`` are NOT NULL strings,
        # ``target_id`` is a nullable UUID, ``metadata`` is a
        # nullable JSONB, ``created_at`` is a TIMESTAMPTZ.
        block = _extract_create_table(_UPGRADE_SQL, "audit_events")
        assert "action" in block
        assert "NOT NULL" in block
        assert "target_type" in block
        assert "target_id" in block
        # ``target_id`` is nullable (system actions have no target).
        assert re.search(
            r"target_id\s+UUID(\s+NULL)?,", block
        ) is not None, "target_id must be nullable"
        assert "metadata" in block
        # JSONB column type.
        assert "JSONB" in block
        assert "created_at" in block
        assert "TIMESTAMP WITH TIME ZONE" in block

    def test_audit_events_is_append_only(self) -> None:
        # §17: audit_events are append-only. No ``updated_at`` and
        # no ``deleted_at``: once an event is recorded, it cannot be
        # edited or removed through the schema.
        block = _extract_create_table(_UPGRADE_SQL, "audit_events")
        assert "updated_at" not in block, (
            "audit_events must not have updated_at: append-only"
        )
        assert "deleted_at" not in block, (
            "audit_events must not have deleted_at: append-only"
        )


# ---------------------------------------------------------------------------
# Deferred FKs from T8 (annotations.user_id, comments.user_id -> users.id)
# ---------------------------------------------------------------------------


class TestUpgradeSqlAddsDeferredForeignKeys:
    """T9 closes the FK debt T8 left behind because ``users`` did not exist."""

    def test_annotations_user_id_foreign_key_added(self) -> None:
        # The FK is added with ``op.create_foreign_key`` so the SQL
        # is an ``ALTER TABLE annotations ADD CONSTRAINT ... FOREIGN
        # KEY(user_id) REFERENCES users``.
        assert re.search(
            r"ALTER TABLE annotations\s+ADD CONSTRAINT \S+\s+"
            r"FOREIGN KEY\(user_id\)\s+REFERENCES users",
            _UPGRADE_SQL,
        ) is not None, (
            "T9 must add the FK from annotations.user_id to users.id"
        )

    def test_comments_user_id_foreign_key_added(self) -> None:
        assert re.search(
            r"ALTER TABLE comments\s+ADD CONSTRAINT \S+\s+"
            r"FOREIGN KEY\(user_id\)\s+REFERENCES users",
            _UPGRADE_SQL,
        ) is not None, (
            "T9 must add the FK from comments.user_id to users.id"
        )

    def test_annotations_user_id_foreign_key_uses_restrict(self) -> None:
        # §18: avoid destructive cascades. The deferred FK must use
        # ``ON DELETE RESTRICT`` like the rest of the schema.
        match = re.search(
            r"ALTER TABLE annotations\s+ADD CONSTRAINT \S+\s+"
            r"FOREIGN KEY\(user_id\)\s+REFERENCES users \(id\)\s+ON DELETE RESTRICT",
            _UPGRADE_SQL,
        )
        assert match is not None, (
            "annotations.user_id FK must use ON DELETE RESTRICT"
        )

    def test_comments_user_id_foreign_key_uses_restrict(self) -> None:
        match = re.search(
            r"ALTER TABLE comments\s+ADD CONSTRAINT \S+\s+"
            r"FOREIGN KEY\(user_id\)\s+REFERENCES users \(id\)\s+ON DELETE RESTRICT",
            _UPGRADE_SQL,
        )
        assert match is not None, (
            "comments.user_id FK must use ON DELETE RESTRICT"
        )


# ---------------------------------------------------------------------------
# Initial Schema completeness (§30)
# ---------------------------------------------------------------------------


class TestUpgradeSqlCompletesInitialSchema:
    """After T9, every table in §30 of ``database.md`` must exist."""

    @pytest.mark.parametrize(
        "table",
        [
            "users",
            "handwriting_fonts",
            "ink_styles",
            "paper_textures",
            "books",
            "book_versions",
            "chapters",
            "paragraphs",
            "annotations",
            "comments",
            "audit_events",
        ],
    )
    def test_initial_schema_table_present(self, table: str) -> None:
        assert f"CREATE TABLE {table}" in _UPGRADE_SQL, (
            f"database.md §30 requires CREATE TABLE {table} after T9"
        )

    def test_create_order_respects_fk_dependencies(self) -> None:
        # Style tables come first (no FKs), then ``users`` (FKs to
        # the style tables), then ``audit_events`` (FK to ``users``).
        order = [
            "handwriting_fonts",
            "ink_styles",
            "paper_textures",
            "users",
            "audit_events",
        ]
        last = -1
        for table in order:
            idx = _UPGRADE_SQL.find(f"CREATE TABLE {table}")
            assert idx > last, (
                f"create order broken: CREATE TABLE {table} (last seen at "
                f"{last}, found at {idx}). Style tables must precede "
                f"``users``; ``users`` must precede ``audit_events``."
            )
            last = idx


# ---------------------------------------------------------------------------
# Downgrade SQL
# ---------------------------------------------------------------------------


class TestDowngradeSqlRevertsT9:
    """``alembic downgrade head:base --sql`` must drop the new tables and FKs."""

    def test_drops_audit_events(self) -> None:
        assert "DROP TABLE audit_events" in _DOWNGRADE_SQL

    def test_drops_users(self) -> None:
        assert "DROP TABLE users" in _DOWNGRADE_SQL

    @pytest.mark.parametrize(
        "table",
        ["handwriting_fonts", "ink_styles", "paper_textures"],
    )
    def test_drops_style_tables(self, table: str) -> None:
        assert f"DROP TABLE {table}" in _DOWNGRADE_SQL, (
            f"downgrade must drop {table}"
        )

    def test_drops_audit_events_before_users(self) -> None:
        # ``audit_events`` references ``users``.
        idx_audit = _DOWNGRADE_SQL.find("DROP TABLE audit_events")
        idx_users = _DOWNGRADE_SQL.find("DROP TABLE users")
        assert -1 not in (idx_audit, idx_users)
        assert idx_audit < idx_users, (
            "audit_events must be dropped before users (FK dependency)"
        )

    def test_drops_users_before_style_tables(self) -> None:
        # ``users`` references the three style tables. In the
        # downgrade, ``users`` must be dropped before the style
        # tables so PostgreSQL does not reject the drop of a
        # referenced table.
        for table in ("handwriting_fonts", "ink_styles", "paper_textures"):
            idx_users = _DOWNGRADE_SQL.find("DROP TABLE users")
            idx_table = _DOWNGRADE_SQL.find(f"DROP TABLE {table}")
            assert -1 not in (idx_users, idx_table)
            assert idx_users < idx_table, (
                f"users must be dropped before {table} (users depends on it)"
            )

    def test_drops_annotations_user_id_fk(self) -> None:
        # The deferred FK from T8 must be dropped in the T9 downgrade
        # so T8's downgrade can proceed without an unresolved FK.
        assert re.search(
            r"ALTER TABLE annotations\s+DROP CONSTRAINT \S+",
            _DOWNGRADE_SQL,
        ) is not None, (
            "downgrade must drop the FK from annotations.user_id"
        )

    def test_drops_comments_user_id_fk(self) -> None:
        assert re.search(
            r"ALTER TABLE comments\s+DROP CONSTRAINT \S+",
            _DOWNGRADE_SQL,
        ) is not None, (
            "downgrade must drop the FK from comments.user_id"
        )

    def test_full_drop_order_top_to_bottom(self) -> None:
        # The new tables are dropped before the T8 tables, in FK-
        # safe order:
        # audit_events -> users -> {styles} -> comments ->
        # annotations -> paragraphs -> chapters -> book_versions ->
        # books.
        #
        # ``{styles}`` are the three reference-style tables; we only
        # check that they are dropped after ``users`` and before
        # ``comments``.
        order = [
            "DROP TABLE audit_events",
            "DROP TABLE users",
            "DROP TABLE handwriting_fonts",
            "DROP TABLE ink_styles",
            "DROP TABLE paper_textures",
            "DROP TABLE comments",
            "DROP TABLE annotations",
            "DROP TABLE paragraphs",
            "DROP TABLE chapters",
            "DROP TABLE book_versions",
            "DROP TABLE books",
        ]
        last = -1
        for stmt in order:
            idx = _DOWNGRADE_SQL.find(stmt)
            assert idx > last, (
                f"drop order broken: {stmt!r} appeared before the previous "
                f"expected drop (last seen at {last}, found at {idx})"
            )
            last = idx
