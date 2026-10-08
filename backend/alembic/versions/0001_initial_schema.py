"""Initial schema: book core.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-08 00:00:00.000000

This is the **first** migration of the Foundation spec (T7). It
creates the four core tables of the book hierarchy
(``docs/architecture/database.md`` §6–§9):

* ``books``
* ``book_versions``
* ``chapters``
* ``paragraphs``

with their constraints (UNIQUE on the natural keys, CHECK on the
``book_versions.status`` enum) and the foreign keys that link them.
The schema is rendered in dependency order: parent tables come
first so child tables can reference them.

Following the spec, this is the **base** of the initial schema:

* T8 (RF-14) will introduce ``annotations`` and ``comments`` in a
  follow-up revision that ``down_revision``s this one. They depend
  on the book core being in place.
* T9 (RF-14) will introduce ``users``, the three reference-style
  tables (``handwriting_fonts``, ``ink_styles``, ``paper_textures``)
  and ``audit_events`` in another follow-up revision. ``users`` has
  foreign keys into the style tables, which is why the style tables
  are part of T9 and not of T7.

The split follows the plan for the Foundation spec: the spec's
"Initial Schema" (§30 of database.md) is implemented across three
migrations so each task remains small and reviewable, and so
``alembic downgrade -1`` after T8 / T9 leaves a coherent state
(the book core, without the social machinery).

Why we do not use ``op.create_table(..., *[Column(...)])`` with a
``sa.ForeignKey('other.id')`` and rely on Alembic's order inference:
Alembic emits ``CREATE TABLE`` statements in the order they appear
in the migration body, which is what we want (parents before
children). The ``downgrade`` drops them in the reverse order, which
is what PostgreSQL needs because of the foreign keys.

Design notes
------------

* **UUID primary keys** (§2.3 of database.md). We use
  ``postgresql.UUID`` with ``server_default=gen_random_uuid()`` so
  raw ``INSERT``s into these tables work without the application
  having to mint UUIDs. ``gen_random_uuid`` is built into
  PostgreSQL 13+ and we target PostgreSQL 16.
* **Timestamps** (§2.4 of database.md). Every timestamp column uses
  ``TIMESTAMP WITH TIME ZONE`` (``sa.DateTime(timezone=True)``) and
  is stored in UTC. The application layer is responsible for
  rendering times in a presentation timezone; the database never
  assumes a local time.
* **Foreign keys** (§18 of database.md). All FKs use
  ``ON DELETE RESTRICT`` to match the "avoid destructive cascades"
  rule. Restricting deletes keeps historical book structure coherent
  even when content is re-ingested.
* **CHECK constraints** (§2.7 of database.md). Critical invariants
  live in the database. The only enum the book core introduces is
  ``book_versions.status``; the values ``draft`` / ``published`` /
  ``archived`` are enforced by a CHECK constraint.
* **Hashes** are stored as ``CHAR(64)`` so the schema matches the
  spec exactly and any application code that assumes SHA-256 hex
  strings sees the right width.
* **No speculative indexes** (§21 of database.md). The only
  additional indexes are the ones that mirror the documented
  access pattern: book → version → chapter → paragraph. Foreign
  key columns are indexed explicitly so the "list children of a
  parent" access pattern does not have to fall back on a
  sequential scan.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the book-core schema (RF-14, database.md §6–§9)."""
    # ------------------------------------------------------------------
    # books (§6)
    # ------------------------------------------------------------------
    # One book per row. The schema supports multiple books even though
    # the initial deployment only seeds one (database.md §6).
    op.create_table(
        "books",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("license", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("slug", name="uq_books_slug"),
    )

    # ------------------------------------------------------------------
    # book_versions (§7)
    # ------------------------------------------------------------------
    # One row per canonical version of a book. ``content_hash`` is the
    # SHA-256 of the normalized content; ``status`` is constrained to
    # the three values documented in §7. Published versions are
    # immutable (§7) — that is enforced by application code in
    # later tasks; the schema cannot prevent in-place updates on
    # its own.
    op.create_table(
        "book_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "book_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_hash", postgresql.CHAR(64), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "book_id", "version_number", name="uq_book_versions_book_version"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_book_versions_status",
        ),
    )
    # Access pattern "list versions of a book" (database.md §21).
    op.create_index(
        "ix_book_versions_book_id", "book_versions", ["book_id"]
    )

    # ------------------------------------------------------------------
    # chapters (§8)
    # ------------------------------------------------------------------
    # Chapters belong to a book version. ``position`` is the canonical
    # ordering; ``chapter_number`` is the human-facing number (1, 2,
    # 3, ...). Both are UNIQUE per book_version for the same reason:
    # a book version cannot have two chapters at the same position or
    # with the same number.
    op.create_table(
        "chapters",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "book_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("book_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("chapter_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "book_version_id",
            "chapter_number",
            name="uq_chapters_book_version_chapter_number",
        ),
        sa.UniqueConstraint(
            "book_version_id", "position", name="uq_chapters_book_version_position"
        ),
    )
    # Access pattern "list chapters of a book version" (§21).
    op.create_index(
        "ix_chapters_book_version_id", "chapters", ["book_version_id"]
    )

    # ------------------------------------------------------------------
    # paragraphs (§9)
    # ------------------------------------------------------------------
    # Paragraphs are the canonical unit of text the annotations point
    # at. ``text`` stores plain text (no HTML) and ``text_hash`` is
    # SHA-256 of the text in hex. Published paragraph text is
    # immutable (§9) — enforced at the application layer; the schema
    # cannot prevent in-place updates on its own.
    op.create_table(
        "paragraphs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "chapter_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chapters.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", postgresql.CHAR(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("chapter_id", "position", name="uq_paragraphs_chapter_position"),
    )
    # Access pattern "list paragraphs of a chapter" (§21).
    op.create_index("ix_paragraphs_chapter_id", "paragraphs", ["chapter_id"])

    # ------------------------------------------------------------------
    # T8 and T9 will introduce, in subsequent migrations, the rest of
    # the "Initial Schema" of database.md §30:
    #
    # * T8 — annotations and comments (children of paragraphs).
    # * T9 — users, the three reference-style tables
    #   (handwriting_fonts, ink_styles, paper_textures) and
    #   audit_events.
    #
    # The split keeps each task small and reviewable; the book core
    # is intentionally left free of those concerns here.
    # ------------------------------------------------------------------


def downgrade() -> None:
    """Drop the book-core schema.

    The drops happen in the reverse order of the creates so foreign
    key constraints are not violated. ``paragraphs`` references
    ``chapters``, which references ``book_versions``, which references
    ``books``; dropping parents first would fail.
    """
    op.drop_index("ix_paragraphs_chapter_id", table_name="paragraphs")
    op.drop_table("paragraphs")

    op.drop_index("ix_chapters_book_version_id", table_name="chapters")
    op.drop_table("chapters")

    op.drop_index("ix_book_versions_book_id", table_name="book_versions")
    op.drop_table("book_versions")

    op.drop_table("books")
