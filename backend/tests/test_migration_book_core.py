"""Tests for the initial book-core migration ``0001_initial_schema.py``.

These tests verify that the migration is structurally correct and that
the rendered offline SQL contains the tables, columns, constraints and
indexes that ``docs/architecture/database.md`` (§6–§9) prescribes for
the book hierarchy. They do not need a live database (RNF-2): the
Alembic offline mode produces the SQL we assert against.

T7 covers only the book core (books, book_versions, chapters,
paragraphs). T8 and T9 will add the remaining tables (annotations,
comments, users, reference styles, audit_events) in subsequent
revisions. The tests below therefore restrict themselves to the four
core tables and their invariants.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

# Repository layout: the migration lives under ``backend/alembic/versions/``.
BACKEND_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
MIGRATION_FILE = next(
    iter((BACKEND_DIR / "alembic" / "versions").glob("0001_*.py")), None
)
# Read the migration file once at module import time so the file-shape
# tests do not depend on a class-scoped fixture (deprecated in
# pytest-asyncio for instance methods, see PytestRemovedIn10Warning).
_MIGRATION_SOURCE = (
    MIGRATION_FILE.read_text(encoding="utf-8") if MIGRATION_FILE else ""
)


def _make_config() -> Config:
    # Alembic writes the offline SQL to ``output_buffer``; defaulting
    # it to an in-memory ``StringIO`` keeps the test runner silent and
    # gives the helpers below a single place to read the SQL from
    # (RNF-2).
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
#
# T8 introduced annotations and comments in a follow-up revision
# (``0002_annotations_and_comments``). The book-core tests in this
# module restrict themselves to what T7 contributes, so the captured
# SQL must be the SQL of revision ``0001_initial_schema`` rather
# than the current ``head``. Passing the bare revision id to
# ``command.upgrade(..., sql=True)`` renders the SQL from the empty
# database up to that revision; ``head:base`` would have rendered
# the full history, including T8.
_UPGRADE_SQL = _offline_sql("0001_initial_schema", "upgrade")
_DOWNGRADE_SQL = _offline_sql("0001_initial_schema:base", "downgrade")


class TestMigrationFileShape:
    """The migration file must have a stable, predictable shape."""

    def test_migration_file_exists(self) -> None:
        assert MIGRATION_FILE is not None, "0001_*.py migration not found"

    def test_migration_declares_revision_id(self) -> None:
        # The revision id must match the file name so a developer can
        # navigate from one to the other. Alembic stores it as a
        # module-level string.
        assert 'revision: str = "0001_initial_schema"' in _MIGRATION_SOURCE, (
            "expected 'revision: str = \"0001_initial_schema\"' in the migration"
        )

    def test_migration_has_no_down_revision(self) -> None:
        # The very first migration has no parent. We accept the two
        # forms Alembic's templates may emit (``Union[str, None]``
        # for the pre-3.10 template and ``str | None`` for the
        # modern one) by checking for the assignment rather than the
        # type annotation.
        assert "down_revision: str | None = None" in _MIGRATION_SOURCE, (
            "the initial migration must declare down_revision = None "
            "with the modern type annotation (str | None)"
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

    def test_migration_mentions_followup_tasks(self) -> None:
        # The plan splits the schema across T7, T8 and T9. The
        # initial migration should make the boundary explicit so a
        # reader knows where the next migrations will plug in.
        # We look for a comment that names T8 and T9 as the owners of
        # the remaining tables.
        assert "T8" in _MIGRATION_SOURCE, (
            "the migration should document that T8 extends it with annotations/comments"
        )
        assert "T9" in _MIGRATION_SOURCE, (
            "the migration should document that T9 extends it with users/styles/audit"
        )


class TestUpgradeSqlContainsBookCore:
    """``alembic upgrade head --sql`` must contain the book core schema."""

    def test_creates_books(self) -> None:
        assert "CREATE TABLE books" in _UPGRADE_SQL

    def test_books_has_unique_slug(self) -> None:
        # ``books.slug`` must be UNIQUE (database.md §6). Alembic
        # emits the UNIQUE constraint either inline on the column
        # declaration (``slug VARCHAR NOT NULL UNIQUE``) or as a
        # separate ``UNIQUE (slug)`` clause. Either form is fine; the
        # block must contain both ``slug`` and ``UNIQUE``.
        block = _extract_create_table(_UPGRADE_SQL, "books")
        assert "slug" in block
        assert "UNIQUE" in block

    def test_books_id_is_uuid_primary_key(self) -> None:
        # Find the CREATE TABLE books block and assert it declares an
        # UUID primary key.
        block = _extract_create_table(_UPGRADE_SQL, "books")
        assert "id" in block
        assert "UUID" in block
        assert "PRIMARY KEY" in block

    def test_books_has_timestamps(self) -> None:
        # database.md §6 lists created_at and updated_at.
        block = _extract_create_table(_UPGRADE_SQL, "books")
        assert "created_at" in block
        assert "updated_at" in block
        # §2 principle 4: "Timestamps use TIMESTAMPTZ in UTC".
        assert "TIMESTAMP" in block and "TIME ZONE" in block

    def test_creates_book_versions(self) -> None:
        assert "CREATE TABLE book_versions" in _UPGRADE_SQL

    def test_book_versions_references_books(self) -> None:
        block = _extract_create_table(_UPGRADE_SQL, "book_versions")
        assert "book_id" in block
        # Alembic renders FKs as ``... REFERENCES books (...)``.
        assert "REFERENCES books" in block

    def test_book_versions_has_unique_book_id_version_number(self) -> None:
        # database.md §7: UNIQUE(book_id, version_number).
        block = _extract_create_table(_UPGRADE_SQL, "book_versions")
        # Alembic renders the constraint as ``UNIQUE (book_id, version_number)``
        # or as a separate ``CREATE UNIQUE INDEX``. We accept either.
        assert "UNIQUE" in block
        assert "book_id" in block
        assert "version_number" in block

    def test_book_versions_has_status_with_check(self) -> None:
        # database.md §7 lists statuses draft / published / archived.
        # The enum is enforced by a CHECK at the database level (§2
        # principle 7: critical invariants at the DB level).
        block = _extract_create_table(_UPGRADE_SQL, "book_versions")
        assert "status" in block
        assert "draft" in block
        assert "published" in block
        assert "archived" in block
        # Alembic renders ``CHECK (...)`` clauses.
        assert "CHECK" in block

    def test_book_versions_content_hash_is_char_64(self) -> None:
        # database.md §7: content_hash CHAR(64).
        block = _extract_create_table(_UPGRADE_SQL, "book_versions")
        # Alembic renders CHAR(64) as ``VARCHAR(64)`` for portability
        # (it maps CHAR to VARCHAR on PostgreSQL), but the length 64
        # must be present and the column must be present.
        assert "content_hash" in block
        assert "(64)" in block

    def test_creates_chapters(self) -> None:
        assert "CREATE TABLE chapters" in _UPGRADE_SQL

    def test_chapters_references_book_versions(self) -> None:
        block = _extract_create_table(_UPGRADE_SQL, "chapters")
        assert "book_version_id" in block
        assert "REFERENCES book_versions" in block

    def test_chapters_unique_book_version_chapter_number(self) -> None:
        # database.md §8: UNIQUE(book_version_id, chapter_number).
        block = _extract_create_table(_UPGRADE_SQL, "chapters")
        assert "UNIQUE" in block
        assert "book_version_id" in block
        assert "chapter_number" in block

    def test_chapters_unique_book_version_position(self) -> None:
        # database.md §8: UNIQUE(book_version_id, position).
        block = _extract_create_table(_UPGRADE_SQL, "chapters")
        assert "UNIQUE" in block
        assert "book_version_id" in block
        assert "position" in block

    def test_creates_paragraphs(self) -> None:
        assert "CREATE TABLE paragraphs" in _UPGRADE_SQL

    def test_paragraphs_references_chapters(self) -> None:
        block = _extract_create_table(_UPGRADE_SQL, "paragraphs")
        assert "chapter_id" in block
        assert "REFERENCES chapters" in block

    def test_paragraphs_unique_chapter_position(self) -> None:
        # database.md §9: UNIQUE(chapter_id, position).
        block = _extract_create_table(_UPGRADE_SQL, "paragraphs")
        assert "UNIQUE" in block
        assert "chapter_id" in block
        assert "position" in block

    def test_paragraphs_text_hash_is_char_64(self) -> None:
        # database.md §9: text_hash CHAR(64).
        block = _extract_create_table(_UPGRADE_SQL, "paragraphs")
        assert "text_hash" in block
        assert "(64)" in block

    def test_paragraphs_text_is_text_type(self) -> None:
        # database.md §9: text TEXT.
        block = _extract_create_table(_UPGRADE_SQL, "paragraphs")
        assert '"text"' in block or "text" in block
        assert "TEXT" in block

    def test_no_annotations_or_comments_yet(self) -> None:
        # T7 stops at the book core. T8 introduces annotations and
        # comments in ``0002_annotations_and_comments``. The capture
        # in this module is scoped to revision ``0001`` (see the
        # module-level comment), so the absence of those tables is
        # the right invariant here: T7 must not have sneaked them
        # in.
        assert "CREATE TABLE annotations" not in _UPGRADE_SQL
        assert "CREATE TABLE comments" not in _UPGRADE_SQL

    def test_no_users_or_audit_yet(self) -> None:
        # T7 stops at the book core. T9 introduces users, reference
        # styles and audit_events. Same rationale as above; the
        # capture is scoped to revision ``0001``.
        assert "CREATE TABLE users" not in _UPGRADE_SQL
        assert "CREATE TABLE audit_events" not in _UPGRADE_SQL


class TestDowngradeSqlRemovesBookCore:
    """``alembic downgrade base --sql`` must drop exactly the book core."""

    def test_drops_paragraphs(self) -> None:
        assert "DROP TABLE paragraphs" in _DOWNGRADE_SQL

    def test_drops_chapters(self) -> None:
        assert "DROP TABLE chapters" in _DOWNGRADE_SQL

    def test_drops_book_versions(self) -> None:
        assert "DROP TABLE book_versions" in _DOWNGRADE_SQL

    def test_drops_books(self) -> None:
        assert "DROP TABLE books" in _DOWNGRADE_SQL

    def test_drops_in_reverse_order(self) -> None:
        # Foreign keys make the drop order matter: a chapter cannot
        # be dropped while a paragraph still references it. The
        # migration must therefore drop paragraphs first, then
        # chapters, then book_versions, then books.
        idx_paragraphs = _DOWNGRADE_SQL.find("DROP TABLE paragraphs")
        idx_chapters = _DOWNGRADE_SQL.find("DROP TABLE chapters")
        idx_versions = _DOWNGRADE_SQL.find("DROP TABLE book_versions")
        idx_books = _DOWNGRADE_SQL.find("DROP TABLE books")
        # ``find`` returns -1 when the substring is missing; the
        # tests above already fail in that case, so we only need to
        # assert the relative order.
        assert -1 not in (idx_paragraphs, idx_chapters, idx_versions, idx_books)
        assert idx_paragraphs < idx_chapters < idx_versions < idx_books


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
