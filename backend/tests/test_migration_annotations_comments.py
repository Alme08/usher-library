"""Tests for the annotations and comments migration ``0002_*.py`` (T8).

These tests verify that the migration is structurally correct and
that the rendered offline SQL contains the tables, columns,
constraints and indexes that ``docs/architecture/database.md``
(§10–§16) prescribes for ``annotations`` and ``comments``. They do
not need a live database (RNF-2): the Alembic offline mode
produces the SQL we assert against.

T8 covers the second slice of the "Initial Schema" (database.md
§30) and depends on the book core created in T7. T9 will add the
remaining tables (``users``, reference styles, ``audit_events``)
and the foreign keys from ``annotations.user_id`` and
``comments.user_id`` to ``users.id``; see the module docstring of
``0002_annotations_and_comments.py`` for the rationale.
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
MIGRATION_FILE = next(iter(VERSIONS_DIR.glob("0002_*.py")), None)
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
    """Render the offline SQL for ``upgrade`` or ``downgrade`` to stdout.

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
        assert MIGRATION_FILE is not None, "0002_*.py migration not found"

    def test_migration_declares_revision_id(self) -> None:
        # The revision id must match the file name so a developer can
        # navigate from one to the other. Alembic stores it as a
        # module-level string.
        assert (
            'revision: str = "0002_annotations_and_comments"' in _MIGRATION_SOURCE
        ), (
            "expected 'revision: str = \"0002_annotations_and_comments\"' "
            "in the migration"
        )

    def test_migration_down_revision_is_initial_schema(self) -> None:
        # T8 must chain on T7. ``down_revision`` is a string here
        # because the migration has a parent.
        assert (
            'down_revision: str | None = "0001_initial_schema"'
            in _MIGRATION_SOURCE
        ), (
            "T8 must declare down_revision = \"0001_initial_schema\" "
            "so it chains on T7 (0001_initial_schema.py)"
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

    def test_migration_documents_users_deferral(self) -> None:
        # T8 leaves ``annotations.user_id`` and ``comments.user_id``
        # without a foreign key because ``users`` is created in T9.
        # The migration must make this explicit so a reviewer knows
        # the FKs are coming in a follow-up revision and not missing
        # by accident.
        assert "T9" in _MIGRATION_SOURCE, (
            "the migration should document that T9 introduces users and "
            "adds the FKs from annotations.user_id / comments.user_id"
        )

    def test_migration_no_user_id_foreign_key(self) -> None:
        # Defensive assertion: T8 must not introduce a ``REFERENCES users``
        # FK because the ``users`` table does not exist yet. The
        # column itself is created; the FK is added in T9.
        # The docstring and inline comments legitimately reference
        # ``users`` (they document the deferral); we therefore
        # assert on the SQL Alembic would actually emit (the
        # offline mode output) rather than on the Python source.
        # The offline SQL is the contract: a reviewer can be sure
        # that the FK is not being declared by reading the
        # generated ``CREATE TABLE`` statement.
        annotations_block = _extract_create_table(_UPGRADE_SQL, "annotations")
        assert "REFERENCES users" not in annotations_block, (
            "annotations.user_id must not declare REFERENCES users in T8; "
            "the FK is added in T9 once the users table exists"
        )
        comments_block = _extract_create_table(_UPGRADE_SQL, "comments")
        assert "REFERENCES users" not in comments_block, (
            "comments.user_id must not declare REFERENCES users in T8; "
            "the FK is added in T9 once the users table exists"
        )

    def test_migration_mentions_highlight_note_invariant(self) -> None:
        # database.md §12: the highlight/note invariant must be
        # documented in the migration. The docstring is enough.
        assert "highlight" in _MIGRATION_SOURCE
        assert "note" in _MIGRATION_SOURCE

    def test_migration_does_not_create_users_or_audit(self) -> None:
        # T8 stops at annotations and comments. T9 introduces
        # ``users`` and ``audit_events``. Asserting their absence
        # prevents an over-eager migration from collapsing T8 and T9
        # into one.
        assert "CREATE TABLE users" not in _MIGRATION_SOURCE
        assert "CREATE TABLE audit_events" not in _MIGRATION_SOURCE


# ---------------------------------------------------------------------------
# Upgrade SQL tests
# ---------------------------------------------------------------------------


class TestUpgradeSqlContainsAnnotations:
    """``alembic upgrade head --sql`` must contain the ``annotations`` table."""

    def test_creates_annotations(self) -> None:
        assert "CREATE TABLE annotations" in _UPGRADE_SQL

    def test_annotations_id_is_uuid_primary_key(self) -> None:
        block = _extract_create_table(_UPGRADE_SQL, "annotations")
        assert "id" in block
        assert "UUID" in block
        assert "PRIMARY KEY" in block

    def test_annotations_references_paragraphs(self) -> None:
        # §10: an annotation must point to a paragraph.
        block = _extract_create_table(_UPGRADE_SQL, "annotations")
        assert "paragraph_id" in block
        assert "REFERENCES paragraphs" in block

    def test_annotations_user_id_is_uuid_not_null_no_fk(self) -> None:
        # T8 keeps ``user_id`` without a FK (users arrives in T9).
        # The column must exist, be NOT NULL, and have a UUID type.
        block = _extract_create_table(_UPGRADE_SQL, "annotations")
        assert "user_id" in block
        assert "UUID" in block
        assert "NOT NULL" in block
        # The FK is added in T9, not in T8.
        assert "REFERENCES users" not in block, (
            "annotations.user_id must not declare REFERENCES users in T8; "
            "the FK is added in T9 once the users table exists"
        )

    def test_annotations_has_offsets_and_selected_text(self) -> None:
        # §12: the offset columns and the denormalised
        # ``selected_text`` snapshot.
        block = _extract_create_table(_UPGRADE_SQL, "annotations")
        assert "start_offset" in block
        assert "end_offset" in block
        assert "selected_text" in block
        # ``selected_text`` is plain TEXT, not VARCHAR.
        assert "TEXT" in block

    def test_annotations_has_kind_and_body(self) -> None:
        # §12: ``kind`` is the kind enum (highlight/note) and
        # ``body`` is the optional prose.
        block = _extract_create_table(_UPGRADE_SQL, "annotations")
        assert "kind" in block
        assert "body" in block

    def test_annotations_has_timestamps_and_soft_delete(self) -> None:
        # §12 + §18: created_at, updated_at and the nullable
        # deleted_at (soft delete).
        block = _extract_create_table(_UPGRADE_SQL, "annotations")
        assert "created_at" in block
        assert "updated_at" in block
        assert "deleted_at" in block
        # §2.4: every timestamp is TIMESTAMP WITH TIME ZONE.
        assert "TIMESTAMP WITH TIME ZONE" in block

    def test_annotations_unique_paragraph_user_range(self) -> None:
        # §13: UNIQUE(paragraph_id, user_id, start_offset, end_offset).
        block = _extract_create_table(_UPGRADE_SQL, "annotations")
        # Alembic renders UNIQUE constraints either as
        # ``UNIQUE (col1, col2, ...)`` or as separate
        # ``CREATE UNIQUE INDEX`` statements. We accept either by
        # checking for the constraint name and the four columns.
        assert "uq_annotations_paragraph_user_range" in block, (
            "the unique constraint must be named "
            "uq_annotations_paragraph_user_range"
        )
        for col in ("paragraph_id", "user_id", "start_offset", "end_offset"):
            assert col in block

    def test_annotations_half_open_offsets_check(self) -> None:
        # §10: start_offset >= 0 AND end_offset > start_offset.
        block = _extract_create_table(_UPGRADE_SQL, "annotations")
        assert "ck_annotations_offsets_half_open" in block
        assert "start_offset >= 0" in block
        assert "end_offset > start_offset" in block

    def test_annotations_highlight_note_invariant_check(self) -> None:
        # §12: highlight → body IS NULL; note → body IS NOT NULL.
        block = _extract_create_table(_UPGRADE_SQL, "annotations")
        assert "ck_annotations_highlight_note_invariant" in block
        assert "highlight" in block
        assert "note" in block
        assert "body IS NULL" in block
        assert "body IS NOT NULL" in block

    def test_annotations_kind_enum_check(self) -> None:
        # §12: kind IN ('highlight', 'note').
        block = _extract_create_table(_UPGRADE_SQL, "annotations")
        assert "ck_annotations_kind" in block
        # ``kind IN ('highlight', 'note')`` — the CHECK renders the
        # literals in the same case.
        assert re.search(r"kind IN \('highlight', 'note'\)", block) is not None

    def test_annotations_paragraph_id_index(self) -> None:
        # §14: INDEX annotations(paragraph_id).
        assert "CREATE INDEX ix_annotations_paragraph_id ON annotations" in _UPGRADE_SQL
        assert "(paragraph_id)" in _UPGRADE_SQL.split(
            "CREATE INDEX ix_annotations_paragraph_id", 1
        )[1].split(";", 1)[0]

    def test_annotations_paragraph_range_index(self) -> None:
        # §14: INDEX annotations(paragraph_id, start_offset, end_offset).
        assert (
            "CREATE INDEX ix_annotations_paragraph_range ON annotations"
            in _UPGRADE_SQL
        )

    def test_annotations_user_created_at_index(self) -> None:
        # §14: INDEX annotations(user_id, created_at).
        assert (
            "CREATE INDEX ix_annotations_user_created_at ON annotations"
            in _UPGRADE_SQL
        )


class TestUpgradeSqlContainsComments:
    """``alembic upgrade head --sql`` must contain the ``comments`` table."""

    def test_creates_comments(self) -> None:
        assert "CREATE TABLE comments" in _UPGRADE_SQL

    def test_comments_id_is_uuid_primary_key(self) -> None:
        block = _extract_create_table(_UPGRADE_SQL, "comments")
        assert "id" in block
        assert "UUID" in block
        assert "PRIMARY KEY" in block

    def test_comments_references_annotations(self) -> None:
        # §15: a comment belongs to an annotation.
        block = _extract_create_table(_UPGRADE_SQL, "comments")
        assert "annotation_id" in block
        assert "REFERENCES annotations" in block

    def test_comments_user_id_is_uuid_not_null_no_fk(self) -> None:
        # Same rationale as annotations.user_id: the FK is added in
        # T9, not in T8.
        block = _extract_create_table(_UPGRADE_SQL, "comments")
        assert "user_id" in block
        assert "UUID" in block
        assert "NOT NULL" in block
        assert "REFERENCES users" not in block, (
            "comments.user_id must not declare REFERENCES users in T8; "
            "the FK is added in T9 once the users table exists"
        )

    def test_comments_parent_comment_id_self_reference(self) -> None:
        # §15: parent_comment_id is a self-referencing FK and may be
        # NULL (top-level comments have no parent).
        block = _extract_create_table(_UPGRADE_SQL, "comments")
        assert "parent_comment_id" in block
        assert "REFERENCES comments" in block
        # The column is nullable (top-level comments).
        # The block contains ``parent_comment_id UUID,`` — the
        # trailing comma followed by another column confirms the
        # column is not the last one and therefore not declared
        # ``PRIMARY KEY`` (which would have implied NOT NULL). A
        # safer check: the FK clause does not have ``NOT NULL``.
        # We rely on the absence of an explicit ``NOT NULL`` on the
        # column declaration by searching for the column name and
        # checking the immediate context.
        # Alembic renders nullable UUID columns as
        # ``parent_comment_id UUID,`` or
        # ``parent_comment_id UUID NULL,`` — both are accepted.
        assert re.search(
            r"parent_comment_id\s+UUID(\s+NULL)?,", block
        ) is not None, "parent_comment_id must be nullable"

    def test_comments_has_body_and_moderation_status(self) -> None:
        # §15: the body and the moderation state.
        block = _extract_create_table(_UPGRADE_SQL, "comments")
        assert "body" in block
        assert "moderation_status" in block

    def test_comments_moderation_status_check(self) -> None:
        # §15: moderation_status IN ('visible', 'hidden').
        block = _extract_create_table(_UPGRADE_SQL, "comments")
        assert "ck_comments_moderation_status" in block
        assert re.search(
            r"moderation_status IN \('visible', 'hidden'\)", block
        ) is not None

    def test_comments_has_timestamps_and_soft_delete(self) -> None:
        # §15 + §18: created_at, updated_at and the nullable
        # deleted_at.
        block = _extract_create_table(_UPGRADE_SQL, "comments")
        assert "created_at" in block
        assert "updated_at" in block
        assert "deleted_at" in block
        assert "TIMESTAMP WITH TIME ZONE" in block

    def test_comments_annotation_id_created_at_index(self) -> None:
        # §16: INDEX comments(annotation_id, created_at).
        assert (
            "CREATE INDEX ix_comments_annotation_id_created_at ON comments"
            in _UPGRADE_SQL
        )

    def test_comments_user_id_created_at_index(self) -> None:
        # §16: INDEX comments(user_id, created_at).
        assert (
            "CREATE INDEX ix_comments_user_id_created_at ON comments"
            in _UPGRADE_SQL
        )

    def test_comments_parent_comment_id_index(self) -> None:
        # §16: INDEX comments(parent_comment_id).
        assert "CREATE INDEX ix_comments_parent_comment_id ON comments" in _UPGRADE_SQL


class TestUpgradeSqlPreservesBookCore:
    """T8 must not regress T7's book core."""

    def test_book_core_still_present(self) -> None:
        # The book core must still be in the SQL after T8 runs.
        for table in ("books", "book_versions", "chapters", "paragraphs"):
            assert f"CREATE TABLE {table}" in _UPGRADE_SQL, (
                f"T8 must not regress T7: {table!r} is missing from the SQL"
            )

    def test_create_order_is_book_core_then_social(self) -> None:
        # T8 must create the book core (T7) before the social
        # tables, because ``annotations.paragraph_id`` references
        # ``paragraphs``. We check the relative position of the
        # paragraphs and annotations CREATE statements.
        idx_paragraphs = _UPGRADE_SQL.find("CREATE TABLE paragraphs")
        idx_annotations = _UPGRADE_SQL.find("CREATE TABLE annotations")
        assert -1 not in (idx_paragraphs, idx_annotations)
        assert idx_paragraphs < idx_annotations, (
            "annotations must be created after paragraphs (FK dependency)"
        )


# ---------------------------------------------------------------------------
# Downgrade SQL tests
# ---------------------------------------------------------------------------


class TestDowngradeSqlRemovesAnnotationsAndComments:
    """``alembic downgrade head:base --sql`` must drop the social tables first."""

    def test_drops_comments(self) -> None:
        assert "DROP TABLE comments" in _DOWNGRADE_SQL

    def test_drops_annotations(self) -> None:
        assert "DROP TABLE annotations" in _DOWNGRADE_SQL

    def test_drops_comments_before_annotations(self) -> None:
        # ``comments`` references ``annotations``; the drop order
        # must respect that.
        idx_comments = _DOWNGRADE_SQL.find("DROP TABLE comments")
        idx_annotations = _DOWNGRADE_SQL.find("DROP TABLE annotations")
        assert -1 not in (idx_comments, idx_annotations)
        assert idx_comments < idx_annotations

    def test_drops_annotations_before_paragraphs(self) -> None:
        # ``annotations`` references ``paragraphs``; the drop order
        # must respect that.
        idx_annotations = _DOWNGRADE_SQL.find("DROP TABLE annotations")
        idx_paragraphs = _DOWNGRADE_SQL.find("DROP TABLE paragraphs")
        assert -1 not in (idx_annotations, idx_paragraphs)
        assert idx_annotations < idx_paragraphs

    def test_drops_comments_indexes(self) -> None:
        # Indexes must be dropped alongside their table. The
        # migration is expected to drop the indexes explicitly so
        # that ``DROP TABLE`` is reversible on a database that
        # tracks index ownership.
        assert "DROP INDEX ix_comments_parent_comment_id" in _DOWNGRADE_SQL
        assert "DROP INDEX ix_comments_user_id_created_at" in _DOWNGRADE_SQL
        assert (
            "DROP INDEX ix_comments_annotation_id_created_at" in _DOWNGRADE_SQL
        )

    def test_drops_annotations_indexes(self) -> None:
        assert "DROP INDEX ix_annotations_user_created_at" in _DOWNGRADE_SQL
        assert "DROP INDEX ix_annotations_paragraph_range" in _DOWNGRADE_SQL
        assert "DROP INDEX ix_annotations_paragraph_id" in _DOWNGRADE_SQL

    def test_full_drop_order(self) -> None:
        # comments → annotations → paragraphs → chapters →
        # book_versions → books.
        order = [
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
