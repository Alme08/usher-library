"""Annotations and comments.

Revision ID: 0002_annotations_and_comments
Revises: 0001_initial_schema
Create Date: 2026-10-08 00:00:00.000000

This is the **second** migration of the Foundation spec (T8, RF-14).
It builds on the book-core schema created by ``0001_initial_schema``
(T7) and introduces the two social-interaction tables defined in
``docs/architecture/database.md`` §10–§16:

* ``annotations`` — a text range inside a paragraph that a user has
  marked as either a ``highlight`` or a ``note``.
* ``comments`` — discussion threads attached to an annotation.
  Replies are modelled as a self-referencing ``parent_comment_id``
  column on the same table (§15); the spec does not introduce a
  separate ``replies`` table.

Invariants enforced at the database level (§2.7 of database.md):

* **UTF-16 half-open range** (§10, §11). The annotation stores
  ``start_offset`` and ``end_offset`` as integer code-unit indexes
  into the paragraph's UTF-16 representation. The check
  ``start_offset >= 0 AND end_offset > start_offset`` rejects empty
  or backwards ranges, and ``end_offset`` is bounded by the
  application layer against the paragraph's UTF-16 length (database.md
  §12 — the schema cannot look at the paragraph's text on its own).
* **Highlight / note invariant** (§12). A ``highlight`` is a marker
  with no prose; a ``note`` is a marker with prose. The database
  enforces this with a single CHECK that is true for both
  combinations and false for the two invalid ones.
* **No duplicate range per user per paragraph** (§13). The unique
  constraint ``(paragraph_id, user_id, start_offset, end_offset)``
  prevents the same user from annotating the same text range twice.
  Overlapping but different ranges are intentionally allowed.
* **Soft delete** (§18). Both tables keep a nullable ``deleted_at``
  TIMESTAMPTZ; the ``UNIQUE`` constraint is not filtered by
  ``deleted_at`` on purpose: a soft-deleted annotation still counts
  as occupying its range, which preserves the integrity of the
  history.
* **Comment in same annotation as its parent** (§15). The application
  layer is responsible for this invariant; the database cannot
  enforce "parent belongs to same annotation" with a CHECK because
  CHECKs cannot follow a foreign key. This is consistent with §2.7:
  every invariant that the database can express is expressed here.

Foreign keys
------------

``annotations`` and ``comments`` both reference ``users.id``. The
``users`` table is created in T9, not in T7 or T8; the initial
Foundation split (plan §1, §7) puts the social machinery in
follow-up revisions to keep each migration small and reviewable.
PostgreSQL rejects a foreign key to a table that does not exist
yet, so the ``user_id`` column is created here **without** the
``REFERENCES users(id)`` clause. T9 (``0003_users_styles_audit``)
adds the foreign key with ``op.create_foreign_key(...)`` against
the now-existing ``users`` table. The column type (UUID), the
``NOT NULL`` constraint and the indexes that depend on it
(``annotations(user_id, created_at)``, ``comments(user_id, created_at)``)
are introduced here, so T9 only needs the FK definition itself.
This is the same pattern Alembic recommends for "expand → migrate
→ contract" (§26 of database.md).

Indexes
-------

The required indexes from §14 and §16 are added in the same
migration that creates the tables, so the access patterns
documented in §21 are covered as soon as the tables exist:

* ``annotations(paragraph_id)`` — list annotations of a paragraph.
* ``annotations(paragraph_id, start_offset, end_offset)`` — locate
  the annotation that contains a given range.
* ``annotations(user_id, created_at)`` — list a user's annotations
  ordered by recency (paginated, §22).
* ``comments(annotation_id, created_at)`` — list the thread of an
  annotation ordered by time.
* ``comments(user_id, created_at)`` — list a user's comments
  ordered by recency.
* ``comments(parent_comment_id)`` — find the children of a parent
  comment.

Design notes
------------

* **UUID primary keys** (§2.3 of database.md). Same convention as
  T7: ``postgresql.UUID`` with ``server_default=gen_random_uuid()``.
* **Timestamps** (§2.4 of database.md). All timestamps are
  ``TIMESTAMP WITH TIME ZONE`` (``sa.DateTime(timezone=True)``).
  ``created_at`` and ``updated_at`` are set to ``now()`` by default
  so the application does not have to supply them on every insert.
  ``deleted_at`` is left without a default; it is ``NULL`` for live
  rows and set to the deletion time when the row is soft-deleted.
* **Foreign keys** (§18 of database.md). The only FK this migration
  introduces is ``annotations.paragraph_id REFERENCES
  paragraphs(id)`` and ``comments.annotation_id REFERENCES
  annotations(id)``. Both use ``ON DELETE RESTRICT`` to match
  "avoid destructive cascades" (§18). The self-reference on
  ``comments.parent_comment_id`` is also ``ON DELETE RESTRICT``:
  deleting a comment with replies is a soft delete in the
  application layer.
* **No speculative indexes** (§21 of database.md). Only the
  indexes §14 and §16 list are created. The
  ``(paragraph_id, start_offset, end_offset)`` index is intentionally
  not unique: §13 forbids duplicates of the *exact* range per user
  via the table-level ``UNIQUE(paragraph_id, user_id,
  start_offset, end_offset)``, and a non-unique range index is
  enough to look up "the annotations that cover this position".
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_annotations_and_comments"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the annotations and comments tables (T8, RF-14)."""
    # ------------------------------------------------------------------
    # annotations (§10–§14)
    # ------------------------------------------------------------------
    # An annotation is a text range inside a single paragraph. The
    # range is a half-open ``[start_offset, end_offset)`` pair of
    # UTF-16 code-unit indexes (§10–§11). The invariant
    # ``start_offset >= 0 AND end_offset > start_offset`` is enforced
    # by a CHECK; the application is responsible for checking that
    # ``end_offset`` does not exceed the paragraph's UTF-16 length
    # (§12 — the database cannot know the paragraph's length).
    #
    # The ``user_id`` column is intentionally **not** a foreign key:
    # the ``users`` table is created in T9 (see the module docstring
    # for the rationale). The column type and the indexes that
    # depend on it are introduced here so T9 only has to add the
    # ``REFERENCES users(id)`` constraint.
    op.create_table(
        "annotations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "paragraph_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("paragraphs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # ``user_id`` is the application-layer pointer to the
        # application user that owns the annotation. The column is
        # NOT NULL because every annotation must have an owner; the
        # FK to ``users(id)`` is added in T9 once the ``users`` table
        # exists. The application is the authority on which user_id
        # values are valid (database.md §19 — the application is the
        # authorisation authority).
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("selected_text", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        # ``body`` is NULL for highlights and NOT NULL for notes
        # (§12). The invariant is enforced by a CHECK below; the
        # column declaration alone is intentionally permissive so
        # the CHECK can reject the two invalid combinations.
        sa.Column("body", sa.Text(), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # §13: the same user cannot annotate the exact same range
        # twice. Overlapping but different ranges are allowed, so
        # the unique constraint is on the four-tuple, not on the
        # range alone. ``WHERE deleted_at IS NULL`` is intentionally
        # omitted: a soft-deleted annotation still occupies its
        # range, which preserves the integrity of the history
        # (database.md §18, §23).
        sa.UniqueConstraint(
            "paragraph_id",
            "user_id",
            "start_offset",
            "end_offset",
            name="uq_annotations_paragraph_user_range",
        ),
        # §10: ``start_offset >= 0`` (offsets cannot be negative) and
        # ``end_offset > start_offset`` (the range is half-open and
        # must be non-empty).
        sa.CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset",
            name="ck_annotations_offsets_half_open",
        ),
        # §12: the highlight/note invariant. The CHECK rejects the
        # two invalid combinations:
        #   * ``highlight`` with a non-NULL ``body`` (highlights
        #     carry no prose);
        #   * ``note`` with a NULL ``body`` (notes carry prose).
        # The two valid combinations (``highlight`` + NULL body,
        # ``note`` + non-NULL body) leave the CHECK true.
        sa.CheckConstraint(
            "(kind = 'highlight' AND body IS NULL) OR "
            "(kind = 'note' AND body IS NOT NULL)",
            name="ck_annotations_highlight_note_invariant",
        ),
        # §12: ``kind`` is restricted to the two documented values.
        sa.CheckConstraint(
            "kind IN ('highlight', 'note')",
            name="ck_annotations_kind",
        ),
    )
    # §14: required indexes for the documented access patterns.
    op.create_index("ix_annotations_paragraph_id", "annotations", ["paragraph_id"])
    op.create_index(
        "ix_annotations_paragraph_range",
        "annotations",
        ["paragraph_id", "start_offset", "end_offset"],
    )
    op.create_index(
        "ix_annotations_user_created_at",
        "annotations",
        ["user_id", "created_at"],
    )

    # ------------------------------------------------------------------
    # comments (§15–§16)
    # ------------------------------------------------------------------
    # A comment belongs to an annotation. ``parent_comment_id`` is a
    # self-reference that models replies (§15). The application
    # layer enforces "a reply must belong to the same annotation as
    # its parent" (database.md §15): the database cannot follow a
    # foreign key inside a CHECK, and adding a trigger would exceed
    # the "no speculative machinery" guidance of §21.
    #
    # ``user_id`` is again intentionally **not** a foreign key: the
    # ``users`` table is created in T9 (see the module docstring
    # and the matching note on ``annotations.user_id`` above).
    op.create_table(
        "comments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "annotation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("annotations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        # Self-referencing FK for replies. ``ON DELETE RESTRICT``
        # mirrors the convention used elsewhere (§18): a comment
        # with children is not physically deletable from the
        # application; the application soft-deletes it instead.
        sa.Column(
            "parent_comment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("comments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("moderation_status", sa.String(), nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # §15: moderation_status is restricted to the two documented
        # initial values. The CHECK is intentionally permissive for
        # future moderation states; only the two values the spec
        # currently lists are accepted.
        sa.CheckConstraint(
            "moderation_status IN ('visible', 'hidden')",
            name="ck_comments_moderation_status",
        ),
    )
    # §16: required indexes for the documented access patterns.
    op.create_index(
        "ix_comments_annotation_id_created_at",
        "comments",
        ["annotation_id", "created_at"],
    )
    op.create_index(
        "ix_comments_user_id_created_at",
        "comments",
        ["user_id", "created_at"],
    )
    op.create_index("ix_comments_parent_comment_id", "comments", ["parent_comment_id"])

    # ------------------------------------------------------------------
    # T9 will introduce, in a subsequent migration, the rest of the
    # "Initial Schema" of database.md §30:
    #
    # * ``users`` (with FKs to the reference-style tables and a
    #   unique ``keycloak_subject``).
    # * The three reference-style tables (``handwriting_fonts``,
    #   ``ink_styles``, ``paper_textures``).
    # * ``audit_events`` (append-only).
    #
    # Once ``users`` exists, T9 will add the foreign keys from
    # ``annotations.user_id`` and ``comments.user_id`` to
    # ``users.id`` via ``op.create_foreign_key(...)``. The column
    # definitions and the indexes that depend on ``user_id`` are
    # already in place after this migration, so T9 only needs the
    # FK statements themselves.
    # ------------------------------------------------------------------


def downgrade() -> None:
    """Drop the annotations and comments tables (T8, RF-14).

    The drops happen in the reverse order of the creates so foreign
    key constraints are not violated. ``comments`` references
    ``annotations`` (and self-references through
    ``parent_comment_id``); ``annotations`` references ``paragraphs``.
    Dropping children first keeps the foreign keys satisfiable at
    every step.
    """
    op.drop_index("ix_comments_parent_comment_id", table_name="comments")
    op.drop_index("ix_comments_user_id_created_at", table_name="comments")
    op.drop_index("ix_comments_annotation_id_created_at", table_name="comments")
    op.drop_table("comments")

    op.drop_index("ix_annotations_user_created_at", table_name="annotations")
    op.drop_index("ix_annotations_paragraph_range", table_name="annotations")
    op.drop_index("ix_annotations_paragraph_id", table_name="annotations")
    op.drop_table("annotations")
