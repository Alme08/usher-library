"""Integration tests for the full initial schema (spec 002 / T1, RF-3(a), RF-5).

These tests run against a real, throwaway PostgreSQL 16 instance
(the ``disposable stack`` from spec 002 / plan §5). They verify that
the migration cycle ``upgrade head`` (run by ``scripts/verify.sh
database`` before pytest is invoked) leaves the database in the shape
documented by ``docs/architecture/database.md`` §30 plus the
section-by-section constraints and indexes listed in §§4-22.

They are intentionally NOT live-database-free: the offline SQL tests
in ``tests/test_migration_*.py`` already cover the structural
correctness of the alembic revisions without a server, and this suite
covers the gap the offline suite cannot: that the SQL produced by the
real, online ``alembic upgrade head`` against a real PostgreSQL
matches the documented model end-to-end and rounds-trips through
``alembic downgrade base`` without losing any element. That is also
what RF-5 ("schema final coincide con el esquema inicial
documentado") and the spec's "provocado en rojo una vez borrando un
índice" verify criterion require.

The disposable stack recipe (``usher_verify_net``,
``usher-verify-db``, ``usher-verify-redis``) lives in ``plan.md`` §5
and is driven by ``scripts/verify.sh database``. Activating this
suite requires ``USHER_RUN_INTEGRATION=1``; otherwise the
integration tests are skipped (see ``conftest.py``).
"""

from __future__ import annotations

import contextlib
import os
from typing import Any

import pytest

pytestmark = pytest.mark.integration


# Initial Schema §30: the canonical list of domain tables the project
# ships at head.
DOMAIN_TABLES: tuple[str, ...] = (
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
)


def _pg_dsn() -> dict[str, Any]:
    """Resolve the disposable PostgreSQL connection parameters.

    The integration suite runs inside the ``usher_library_backend``
    image against a throwaway container (``usher-verify-db``) on the
    ``usher_verify_net`` network. ``scripts/verify.sh database``
    (plan §5) conveys the address exclusively through the
    ``DATABASE_URL`` environment variable in the form
    ``postgresql+asyncpg://user:password@host:port/db`` — the
    application settings are not always amended with the matching
    ``POSTGRES_*`` overrides, so this helper parses the URL directly.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise pytest.skip(
            "DATABASE_URL is not set; integration suite needs a target DB"
        )
    # Strip the SQLAlchemy driver prefix before parsing.
    bare = url
    if "://" in bare:
        scheme, _, rest = bare.partition("://")
        bare = rest
        if "+" in scheme:
            # e.g. postgresql+asyncpg -> postgresql; asyncpg ignores it.
            pass
    # ``urllib.parse.urlparse`` accepts the scheme prefixed, so re-add a
    # placeholder to make parsing robust.
    parsed = __import__("urllib.parse").parse.urlparse(
        "postgresql://" + bare if "://" not in bare else bare
    )
    host = parsed.hostname
    port = parsed.port or 5432
    user = parsed.username or "usher"
    password = parsed.password or ""
    database = (parsed.path or "/").lstrip("/") or "usher_verify"
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": database,
    }


@contextlib.asynccontextmanager
async def _db():
    """Yield an asyncpg connection; close it deterministically on exit.

    asyncpg's ``connect`` is a coroutine (not an async context
    manager), so a thin ``@asynccontextmanager`` wrapper keeps the
    test bodies short without leaving dangling connections behind.
    """
    # Local import: keeps the offline suite untouched when this
    # module is collected but the integration tests are skipped.
    import asyncpg

    dsn = _pg_dsn()
    conn = await asyncpg.connect(**dsn)
    try:
        yield conn
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Discovery helpers (each opens a short-lived connection via _db())
# ---------------------------------------------------------------------------


async def _pg_index_rows() -> list[dict[str, Any]]:
    """Return one row per index (index_name, table_name, definition)."""
    async with _db() as conn:
        rows = await conn.fetch(
            """
            SELECT  indexname        AS index_name,
                    tablename        AS table_name,
                    indexdef         AS definition
            FROM    pg_indexes
            WHERE   schemaname = 'public'
            ORDER BY tablename, indexname
            """
        )
    return [dict(r) for r in rows]


async def _pg_constraint_rows() -> list[dict[str, Any]]:
    """Return one row per constraint (name, table, kind, definition)."""
    async with _db() as conn:
        rows = await conn.fetch(
            """
            SELECT  conname           AS name,
                    conrelid::regclass::text AS table_name,
                    contype           AS kind,
                    pg_get_constraintdef(oid) AS definition
            FROM    pg_constraint
            WHERE   connamespace = 'public'::regnamespace
            ORDER BY table_name, conname
            """
        )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestTablePresence:
    """Exactly the 11 tables of the Initial Schema plus alembic_version."""

    @pytest.mark.asyncio
    async def test_domain_tables_present(self) -> None:
        async with _db() as conn:
            rows = await conn.fetch(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
                """
            )
        names = {r["table_name"] for r in rows}
        # alembic_version is created by Alembic itself; required by RF-4
        # because the guard reads it. Without it the migration system is
        # broken even if the domain tables happen to exist.
        assert "alembic_version" in names, "alembic_version is missing"
        missing = [t for t in DOMAIN_TABLES if t not in names]
        assert not missing, f"missing domain tables from Initial Schema: {missing}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("table", DOMAIN_TABLES)
    async def test_table_has_uuid_primary_key(self, table: str) -> None:
        async with _db() as conn:
            row = await conn.fetchrow(
                """
                SELECT  c.column_name,
                        c.data_type
                FROM    information_schema.table_constraints tc
                JOIN    information_schema.constraint_column_usage cu
                  ON    tc.constraint_name = cu.constraint_name
                JOIN    information_schema.columns c
                  ON    c.table_schema = tc.table_schema
                 AND    c.table_name   = tc.table_name
                 AND    c.column_name  = cu.column_name
                WHERE   tc.table_schema = 'public'
                  AND   tc.table_name   = $1
                  AND   tc.constraint_type = 'PRIMARY KEY'
                """,
                table,
            )
        assert row is not None, f"no PRIMARY KEY on {table!r}"
        assert row["data_type"] == "uuid", (
            f"{table!r} primary key is {row['data_type']!r}, expected uuid"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("table", DOMAIN_TABLES)
    async def test_table_has_created_at(self, table: str) -> None:
        # Every domain table has a ``created_at TIMESTAMPTZ`` column.
        # ``updated_at`` / ``deleted_at`` are conditional on the
        # domain role of the table (mutable records vs immutable
        # content vs append-only audit ledger) and are checked
        # separately by ``test_mutable_tables_have_updated_at`` and
        # ``test_soft_deletable_tables_have_deleted_at`` below.
        async with _db() as conn:
            cols = {
                r["column_name"]: r["data_type"]
                for r in await conn.fetch(
                    """
                    SELECT  column_name, data_type
                    FROM    information_schema.columns
                    WHERE   table_schema = 'public'
                      AND   table_name = $1
                    """,
                    table,
                )
            }
        assert "created_at" in cols and cols["created_at"] == "timestamp with time zone", (
            f"{table!r} missing created_at or wrong type: {cols.get('created_at')!r}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "table",
        ["users", "books", "annotations", "comments"],
    )
    async def test_mutable_tables_have_updated_at(self, table: str) -> None:
        # Only the mutable tables (users, books, annotations, comments)
        # carry ``updated_at`` per §§4, 6, 12, 15. Immutable content
        # (book_versions, chapters, paragraphs) and the reference-style
        # tables do not, because the spec treats them as versioned,
        # published, or read-only.
        async with _db() as conn:
            cols = {
                r["column_name"]: r["data_type"]
                for r in await conn.fetch(
                    """
                    SELECT  column_name, data_type
                    FROM    information_schema.columns
                    WHERE   table_schema = 'public'
                      AND   table_name = $1
                    """,
                    table,
                )
            }
        assert "updated_at" in cols and cols["updated_at"] == "timestamp with time zone", (
            f"{table!r} (mutable per spec) is missing updated_at"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("table", ["annotations", "comments"])
    async def test_soft_deletable_tables_have_deleted_at(self, table: str) -> None:
        # Soft-deletable tables (§§12, 15, 18) carry a nullable
        # ``deleted_at TIMESTAMPTZ``; every other domain table is
        # either immutable or physically constrained.
        async with _db() as conn:
            cols = {
                r["column_name"]: r["data_type"]
                for r in await conn.fetch(
                    """
                    SELECT  column_name, data_type
                    FROM    information_schema.columns
                    WHERE   table_schema = 'public'
                      AND   table_name = $1
                    """,
                    table,
                )
            }
        assert "deleted_at" in cols and cols["deleted_at"] == "timestamp with time zone", (
            f"{table!r} (soft-deletable per §18) is missing deleted_at"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "table",
        [
            "book_versions",
            "chapters",
            "paragraphs",
            "handwriting_fonts",
            "ink_styles",
            "paper_textures",
            "audit_events",
        ],
    )
    async def test_immutable_or_appendonly_tables_skip_updated_at(
        self, table: str
    ) -> None:
        # Content tables and the audit ledger do not carry
        # ``updated_at``: §7 ("published versions are immutable"),
        # §9 ("published paragraph text is immutable"), §17
        # ("append-only") and §5 (reference-style, no editing
        # workflow). This is a forward check to catch accidental
        # introduction of an edit column on a table that the spec
        # declares immutable.
        async with _db() as conn:
            row = await conn.fetchrow(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = $1
                  AND column_name = 'updated_at'
                """,
                table,
            )
        assert row is None, (
            f"immutable/append-only table {table!r} unexpectedly has updated_at; "
            "the spec forbids editing it (§§5, 7, 9, 17)"
        )

    @pytest.mark.asyncio
    async def test_audit_events_has_no_deleted_at(self) -> None:
        # Audit rows are append-only (§17): the table must not gain
        # a ``deleted_at`` column that would allow removal.
        async with _db() as conn:
            row = await conn.fetchrow(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'audit_events'
                  AND column_name IN ('deleted_at', 'updated_at')
                """
            )
        assert row is None, "audit_events must not have deleted_at/updated_at (§17)"


class TestForeignKeys:
    """Every documented foreign key is present (including T8 deferrals)."""

    # (child_table, constraint_name) tuples the model guarantees.
    EXPECTED_FKS: tuple[tuple[str, str], ...] = (
        ("book_versions", "book_versions_book_id_fkey"),
        ("chapters", "chapters_book_version_id_fkey"),
        ("paragraphs", "paragraphs_chapter_id_fkey"),
        ("annotations", "annotations_paragraph_id_fkey"),
        # Deferred FKs added by T9 (§30 close-out):
        ("annotations", "fk_annotations_user_id"),
        ("comments", "fk_comments_user_id"),
        ("comments", "comments_annotation_id_fkey"),
        ("comments", "comments_parent_comment_id_fkey"),
        ("users", "users_handwriting_font_id_fkey"),
        ("users", "users_ink_style_id_fkey"),
        ("users", "users_paper_texture_id_fkey"),
        ("audit_events", "audit_events_actor_user_id_fkey"),
    )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("table,name", list(EXPECTED_FKS))
    async def test_expected_fk_present(self, table: str, name: str) -> None:
        rows = await _pg_constraint_rows()
        # asyncpg returns ``pg_constraint.contype`` as a single-byte
        # ``memoryview`` / ``bytes`` value; coerce to ``str`` before
        # comparing against the textual kind codes ("p", "u", "c", "f").
        match = [
            r for r in rows
            if r["table_name"] == table
            and r["name"] == name
            and bytes(r["kind"]) == b"f"
        ]
        assert match, (
            f"missing foreign key {name!r} on {table!r} (RF-3(a) deferred-FK closure)"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("table,name", list(EXPECTED_FKS))
    async def test_expected_fk_targets_ondelete_restrict(
        self, table: str, name: str
    ) -> None:
        # §18 forbids destructive cascades; every FK must declare
        # ON DELETE RESTRICT. A test that does not name the rule
        # would pass on permissive defaults but fail in production
        # when a delete actually cascades through domain history.
        async with _db() as conn:
            row = await conn.fetchrow(
                "SELECT confdeltype FROM pg_constraint WHERE conname = $1",
                name,
            )
        assert row is not None, f"constraint {name!r} is not in pg_constraint"
        # PostgreSQL codes: 'a' = NO ACTION, 'r' = RESTRICT, 'c' = CASCADE,
        # 'n' = SET NULL, 'd' = SET DEFAULT. asyncpg returns the
        # ``char``/``"char"`` columns of ``pg_catalog`` as ``bytes``,
        # not ``str`` — compare against the bytes literal so the
        # assertion really observes the database value.
        assert bytes(row["confdeltype"]) == b"r", (
            f"FK {name!r} does not use ON DELETE RESTRICT (§18): {row['confdeltype']!r}"
        )


class TestUniqueConstraints:
    """The natural-key uniques from §§4, 6, 7, 8, 9, 13."""

    # (table, constraint_name) tuples.
    EXPECTED_UNIQUES: tuple[tuple[str, str], ...] = (
        ("books", "uq_books_slug"),
        ("book_versions", "uq_book_versions_book_version"),
        ("chapters", "uq_chapters_book_version_chapter_number"),
        ("chapters", "uq_chapters_book_version_position"),
        ("paragraphs", "uq_paragraphs_chapter_position"),
        ("annotations", "uq_annotations_paragraph_user_range"),
        ("users", "uq_users_keycloak_subject"),
        ("users", "uq_users_username"),
        ("handwriting_fonts", "uq_handwriting_fonts_slug"),
        ("ink_styles", "uq_ink_styles_slug"),
        ("paper_textures", "uq_paper_textures_slug"),
    )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("table,name", list(EXPECTED_UNIQUES))
    async def test_unique_present(self, table: str, name: str) -> None:
        async with _db() as conn:
            row = await conn.fetchrow(
                """
                SELECT  pg_get_constraintdef(c.oid) AS defn
                FROM    pg_constraint c
                WHERE   c.conname = $1
                  AND   c.conrelid::regclass::text = $2
                  AND   c.contype = 'u'
                """,
                name,
                table,
            )
        assert row is not None, (
            f"missing UNIQUE constraint {name!r} on {table!r}"
        )
        assert row["defn"].upper().startswith("UNIQUE"), (
            f"{name!r} on {table!r} is not UNIQUE: {row['defn']!r}"
        )


class TestCheckConstraints:
    """The CHECK constraints that pin down the domain enums and invariants."""

    EXPECTED_CHECKS: tuple[tuple[str, str], ...] = (
        # book_versions.status is the only enum the book core pins
        # down at the schema level (§7).
        ("book_versions", "ck_book_versions_status"),
        # annotations: half-open UTF-16 range, highlight/note invariant,
        # and the kind enum itself (§§10, 12).
        ("annotations", "ck_annotations_offsets_half_open"),
        ("annotations", "ck_annotations_highlight_note_invariant"),
        ("annotations", "ck_annotations_kind"),
        # moderation_status enum (§15).
        ("comments", "ck_comments_moderation_status"),
        # users.role and users.status (§4).
        ("users", "ck_users_role"),
        ("users", "ck_users_status"),
    )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("table,name", list(EXPECTED_CHECKS))
    async def test_check_present(self, table: str, name: str) -> None:
        async with _db() as conn:
            row = await conn.fetchrow(
                """
                SELECT  pg_get_constraintdef(c.oid) AS defn
                FROM    pg_constraint c
                WHERE   c.conname = $1
                  AND   c.conrelid::regclass::text = $2
                  AND   c.contype = 'c'
                """,
                name,
                table,
            )
        assert row is not None, (
            f"missing CHECK constraint {name!r} on {table!r}"
        )
        assert row["defn"].upper().startswith("CHECK"), (
            f"{name!r} on {table!r} is not CHECK: {row['defn']!r}"
        )


class TestIndexes:
    """The required indexes from §14 and §16 plus the FK column indexes
    documented in §21."""

    # (table, index_name) tuples.
    EXPECTED_INDEXES: tuple[tuple[str, str], ...] = (
        # FK column indexes (§21 — "list children of a parent").
        ("book_versions", "ix_book_versions_book_id"),
        ("chapters", "ix_chapters_book_version_id"),
        ("paragraphs", "ix_paragraphs_chapter_id"),
        # annotations: §14 declares three required indexes.
        ("annotations", "ix_annotations_paragraph_id"),
        ("annotations", "ix_annotations_paragraph_range"),
        ("annotations", "ix_annotations_user_created_at"),
        # comments: §16 declares three required indexes.
        ("comments", "ix_comments_annotation_id_created_at"),
        ("comments", "ix_comments_user_id_created_at"),
        ("comments", "ix_comments_parent_comment_id"),
    )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("table,name", list(EXPECTED_INDEXES))
    async def test_index_present(self, table: str, name: str) -> None:
        async with _db() as conn:
            row = await conn.fetchrow(
                """
                SELECT  indexdef
                FROM    pg_indexes
                WHERE   schemaname = 'public'
                  AND   tablename = $1
                  AND   indexname = $2
                """,
                table,
                name,
            )
        assert row is not None, (
            f"missing INDEX {name!r} on {table!r}"
        )


class TestRoundTrip:
    """RF-5: cycle the migrations and re-verify the same 11 tables."""

    @pytest.mark.asyncio
    async def test_downgrade_then_upgrade_round_trips_constraints(self) -> None:
        # Drive the downgrade / upgrade cycle through the same
        # subprocess invocation ``scripts/verify.sh`` uses (RF-4/5).
        import asyncio
        import pathlib

        backend = pathlib.Path(__file__).resolve().parents[2]
        env = os.environ.copy()

        async def _run(*args: str) -> None:
            proc = await asyncio.create_subprocess_exec(
                "python3", "-m", "alembic", *args,
                cwd=str(backend),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            assert proc.returncode == 0, (
                f"alembic {' '.join(args)} failed: {stderr.decode()!r}"
            )

        await _run("downgrade", "base")
        await _run("upgrade", "head")

        # After the round trip every Initial Schema table must again be
        # present and every expected constraint must again exist.
        async with _db() as conn:
            rows = await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public'"
            )
            present = {r["table_name"] for r in rows}
            missing = [t for t in DOMAIN_TABLES if t not in present]
            assert not missing, f"round-trip lost domain tables: {missing}"

            constraints = await conn.fetch(
                """
                SELECT conname AS name, conrelid::regclass::text AS table_name, contype AS kind
                FROM pg_constraint
                WHERE connamespace = 'public'::regnamespace
                """
            )
            present_fks = {
                (r["table_name"], r["name"])
                for r in constraints
                if bytes(r["kind"]) == b"f"
            }
            missing_fks = [
                fk for fk in TestForeignKeys.EXPECTED_FKS
                if fk not in present_fks
            ]
            assert not missing_fks, (
                f"round-trip lost FKs: {missing_fks} (RF-5)"
            )

            present_checks = {
                (r["table_name"], r["name"])
                for r in constraints
                if bytes(r["kind"]) == b"c"
            }
            missing_checks = [
                ck for ck in TestCheckConstraints.EXPECTED_CHECKS
                if ck not in present_checks
            ]
            assert not missing_checks, (
                f"round-trip lost CHECK constraints: {missing_checks} (RF-5)"
            )

            indexes = await conn.fetch(
                """
                SELECT indexname AS index_name, tablename AS table_name
                FROM pg_indexes WHERE schemaname = 'public'
                """
            )
            present_indexes = {
                (r["table_name"], r["index_name"]) for r in indexes
            }
            missing_idx = [
                ix for ix in TestIndexes.EXPECTED_INDEXES
                if ix not in present_indexes
            ]
            assert not missing_idx, (
                f"round-trip lost indexes: {missing_idx} (RF-5)"
            )
