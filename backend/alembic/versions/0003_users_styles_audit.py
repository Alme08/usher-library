"""Users, reference style tables and audit events.

Revision ID: 0003_users_styles_audit
Revises: 0002_annotations_and_comments
Create Date: 2026-10-08 00:00:00.000000

This is the **third** migration of the Foundation spec (T9, RF-14).
It builds on the book core (T7, ``0001_initial_schema``) and the
annotations / comments schema (T8, ``0002_annotations_and_comments``)
and closes the "Initial Schema" of ``docs/architecture/database.md``
§30 with the social / identity machinery:

* Three reference-style tables (§5): ``handwriting_fonts``,
  ``ink_styles`` and ``paper_textures``. Each row is one style
  asset the application can offer to readers; the ``slug`` column
  is the deterministic identifier used for stable seeding
  (§5: "Stable slugs should be used for deterministic seeding").
* The ``users`` table (§4) — the application user record. This
  table holds the application-layer identifier (``id``) and the
  external identity mapping (``keycloak_subject``); it does not
  hold any credentials. ``users`` declares foreign keys to each of
  the three style tables, so the style tables must be created
  first.
* ``audit_events`` (§17) — the append-only ledger of administrative
  actions. The table has no ``updated_at`` and no ``deleted_at``
  because audit rows are immutable once written; that is what
  "append-only" means in the schema.

Deferred foreign keys from T8
-----------------------------

T8 (``0002_annotations_and_comments``) created
``annotations.user_id`` and ``comments.user_id`` **without** a
``REFERENCES users(id)`` clause because the ``users`` table did
not exist yet (PostgreSQL rejects a foreign key to a table that
does not exist). T9 now exists, so this migration closes the
deferred FKs with ``op.create_foreign_key(...)``. The columns,
their ``NOT NULL`` and their indexes were introduced in T8; T9
only declares the referential integrity check.

The deferred FKs both use ``ON DELETE RESTRICT`` (§18) to match
the rest of the schema and the "avoid destructive cascades"
rule.

Append-only audit events
------------------------

``audit_events`` is intentionally append-only (§17). Concretely:

* No ``updated_at`` column: a recorded action is not editable.
* No ``deleted_at`` column: a recorded action cannot be soft-
  deleted.
* ``actor_user_id`` is nullable because some events are emitted
  by the system itself (for example, automated moderation
  actions) without a user actor.
* ``metadata`` is a nullable JSONB column for action-specific
  context; it must never contain secrets or authentication
  credentials (§17).

Design notes
------------

* **UUID primary keys** (§2.3 of database.md). The same convention
  as T7 and T8: ``postgresql.UUID`` with
  ``server_default=gen_random_uuid()``.
* **Timestamps** (§2.4 of database.md). ``users`` keeps both
  ``created_at`` and ``updated_at`` (an application user is an
  updatable record). ``audit_events`` keeps only ``created_at``
  because the row is immutable once written.
* **Foreign keys** (§18 of database.md). All FKs use
  ``ON DELETE RESTRICT`` to match "avoid destructive cascades".
  The FKs from ``users`` to the three style tables are inline
  on the column declarations (the style tables exist in this
  same migration). The FKs from ``annotations.user_id`` and
  ``comments.user_id`` to ``users.id`` are added with
  ``op.create_foreign_key`` after ``users`` is created.
* **CHECK constraints** (§2.7 of database.md). ``users.role`` and
  ``users.status`` are restricted to their documented values via
  CHECKs so an out-of-band insert cannot put a user in an
  unrecognised state.
* **Unique constraints** (§4 of database.md). ``keycloak_subject``
  and ``username`` are unique across the table so the external
  identity mapping is unambiguous and the human-facing handle is
  unambiguous.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_users_styles_audit"
down_revision: str | None = "0002_annotations_and_comments"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create users, reference styles, audit_events and close T8 FKs (T9, RF-14)."""
    # ------------------------------------------------------------------
    # Reference style tables (§5)
    # ------------------------------------------------------------------
    # The three tables share the same shape: ``id``, ``slug`` (UNIQUE),
    # ``display_name``, ``asset_path``, ``is_active`` and ``created_at``.
    # ``slug`` is the deterministic identifier used for stable seeding
    # (§5); ``is_active`` lets the application hide a style without
    # deleting its history.
    _create_style_table("handwriting_fonts")
    _create_style_table("ink_styles")
    _create_style_table("paper_textures")

    # ------------------------------------------------------------------
    # users (§4)
    # ------------------------------------------------------------------
    # The application user. ``keycloak_subject`` is the bridge from
    # the Keycloak subject identifier to the application row (§4:
    # "``keycloak_subject`` is the external identity mapping;
    # application foreign keys use ``users.id``"). ``username`` is
    # the human-facing handle. ``role`` and ``status`` are restricted
    # by CHECKs; the FKs to the three style tables are inline on the
    # column declarations (the style tables exist earlier in this
    # same migration).
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("keycloak_subject", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        # The three style FKs are inline because the style tables
        # already exist by this point in the migration body.
        sa.Column(
            "handwriting_font_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("handwriting_fonts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "ink_style_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ink_styles.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "paper_texture_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("paper_textures.id", ondelete="RESTRICT"),
            nullable=True,
        ),
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
        # §4: ``keycloak_subject`` is UNIQUE so the external identity
        # mapping is unambiguous.
        sa.UniqueConstraint(
            "keycloak_subject", name="uq_users_keycloak_subject"
        ),
        # §4: ``username`` is UNIQUE so two users cannot share a
        # human-facing handle.
        sa.UniqueConstraint("username", name="uq_users_username"),
        # §4: ``role`` is restricted to the two documented values.
        sa.CheckConstraint(
            "role IN ('READER', 'ADMIN')", name="ck_users_role"
        ),
        # §4: ``status`` is restricted to the two documented values.
        sa.CheckConstraint(
            "status IN ('active', 'suspended')", name="ck_users_status"
        ),
    )

    # ------------------------------------------------------------------
    # audit_events (§17)
    # ------------------------------------------------------------------
    # Append-only ledger of administrative actions. ``actor_user_id``
    # is nullable (system-originated events have no user actor); the
    # rest of the columns are described in §17. There is no
    # ``updated_at`` and no ``deleted_at``: audit rows are immutable
    # once written.
    op.create_table(
        "audit_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # ``actor_user_id`` is nullable because system actions have
        # no user actor (§17). The FK uses ``ON DELETE RESTRICT``
        # (§18) so an audit record cannot be silently re-parented
        # by deleting the user.
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        # ``metadata`` is a nullable JSONB column for action-
        # specific context (§17). Secrets and authentication
        # credentials must never be stored here; that is enforced
        # at the application layer.
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------
    # Deferred FKs from T8 (§10, §15 — annotations.user_id /
    # comments.user_id -> users.id)
    # ------------------------------------------------------------------
    # T8 created ``annotations.user_id`` and ``comments.user_id``
    # without a ``REFERENCES users(id)`` clause because the
    # ``users`` table did not exist yet. Now that ``users``
    # exists, we add the FKs with ``op.create_foreign_key``.
    # Both use ``ON DELETE RESTRICT`` (§18).
    op.create_foreign_key(
        "fk_annotations_user_id",
        "annotations",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_comments_user_id",
        "comments",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Drop the deferred FKs and the new tables (T9, RF-14).

    The drops happen in the reverse order of the creates so foreign
    key constraints are not violated:

    * Drop the deferred FKs (the T8 columns) before T8's tables,
      so T8's ``downgrade`` can proceed without an unresolved FK.
    * Drop ``audit_events`` before ``users`` (audit_events
      references users).
    * Drop ``users`` before the three style tables (users
      references them).
    * Drop the style tables before T8's tables (T8's tables do
      not depend on the style tables, but dropping the style
      tables here keeps the same FK-safe order as the upgrade).

    The exact order matches the assertions in
    ``test_migration_users_styles_audit.py``.
    """
    # ------------------------------------------------------------------
    # Deferred FKs from T8 (drop them first so the T8 downgrade
    # proceeds without an unresolved FK once T8 runs).
    # ------------------------------------------------------------------
    op.drop_constraint(
        "fk_comments_user_id", "comments", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_annotations_user_id", "annotations", type_="foreignkey"
    )

    # ------------------------------------------------------------------
    # audit_events -> users -> style tables.
    # ------------------------------------------------------------------
    op.drop_table("audit_events")

    op.drop_table("users")

    op.drop_table("handwriting_fonts")
    op.drop_table("ink_styles")
    op.drop_table("paper_textures")


def _create_style_table(table_name: str) -> None:
    """Create one of the three reference-style tables (§5).

    The three reference tables share the same shape. ``slug`` is
    UNIQUE for deterministic seeding (§5); ``is_active`` lets the
    application hide a style without deleting its history;
    ``created_at`` is the canonical timestamp.

    The helper is private to this module: it is not a public API
    and is only meant to keep the three CREATE TABLE blocks
    symmetric and readable.
    """
    op.create_table(
        table_name,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # §5: ``slug UNIQUE``. The unique constraint name follows
        # the project convention ``uq_<table>_<column>`` so a
        # reviewer can locate it from the constraint name alone.
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("asset_path", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("slug", name=f"uq_{table_name}_slug"),
    )
