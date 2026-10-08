"""Tests for the pure migration guard domain function (RF-16).

The migration guard is the piece of logic that decides what to do when
the backend starts up against a PostgreSQL database that may be in any
of three states:

* **Empty database** — no tables at all. We should ``apply`` migrations
  from scratch (the typical first run on a clean volume).
* **Database already at a known revision** — Alembic's ``alembic_version``
  table exists and records a revision. We should ``apply`` only the
  migrations that are still pending (RF-4).
* **Database with user tables but no ``alembic_version``** — somebody
  provisioned the schema manually (or the volume pre-dates Alembic).
  Applying migrations blindly here would corrupt the schema and possibly
  lose data; the guard must ``abort`` the start-up with a clear message
  (RF-16, criteria 4).

The decision itself must be a **pure** function so the rule can be
unit-tested without touching PostgreSQL (RNF-2). The infrastructure
layer is responsible for *collecting* the inputs (``hasAlembicVersion``
and ``hasUserTables``); the domain layer is responsible for *deciding*
what to do.

The tests in this module cover only the decision function. The I/O
wiring (``alembic upgrade head`` after ``apply``; log + exit non-zero
after ``abort``) is exercised in ``test_startup.py`` with mocks.
"""

from __future__ import annotations

import pytest

from app.domain.migration_guard import (
    DbState,
    decideMigrationAction,
)


class TestDbState:
    """``DbState`` is the input contract for the guard."""

    def test_carries_alembic_version_flag(self) -> None:
        state = DbState(hasAlembicVersion=True, hasUserTables=False)
        assert state.hasAlembicVersion is True

    def test_carries_user_tables_flag(self) -> None:
        state = DbState(hasAlembicVersion=False, hasUserTables=True)
        assert state.hasUserTables is True

    def test_is_immutable(self) -> None:
        # The state captures a snapshot of the database at one point in
        # time; mutating it after the guard has run would be confusing.
        # ``frozen=True`` prevents accidental assignment. We accept
        # either AttributeError or any subclass (FrozenInstanceError
        # is a subclass) so the assertion stays robust against
        # dataclasses versions that might surface a different type.
        state = DbState(hasAlembicVersion=False, hasUserTables=False)
        with pytest.raises((AttributeError, Exception)):
            state.hasAlembicVersion = True  # type: ignore[misc]


class TestDecideMigrationAction:
    """``decideMigrationAction`` covers the three observable states (RF-16)."""

    def test_empty_database_means_apply(self) -> None:
        # A fresh volume (no tables at all) is the expected state on
        # first ``docker compose up`` against an empty data directory.
        # The guard must apply migrations from scratch.
        assert decideMigrationAction(
            DbState(hasAlembicVersion=False, hasUserTables=False)
        ) == "apply"

    def test_database_with_alembic_history_means_apply(self) -> None:
        # An already-migrated database only needs the *pending*
        # revisions applied. The guard's contract for that case is
        # still ``apply`` — what changes is the amount of work
        # Alembic has to do.
        assert decideMigrationAction(
            DbState(hasAlembicVersion=True, hasUserTables=True)
        ) == "apply"

    def test_alembic_history_without_user_tables_is_a_no_op_apply(self) -> None:
        # ``alembic_version`` may exist even when no user tables have
        # been created yet (e.g. a partial migration was rolled back
        # by hand). The guard must not abort this state because
        # Alembic will simply apply whatever is still pending.
        assert decideMigrationAction(
            DbState(hasAlembicVersion=True, hasUserTables=False)
        ) == "apply"

    def test_user_tables_without_alembic_history_means_abort(self) -> None:
        # The dangerous state: there are tables in the schema but
        # Alembic has never recorded a revision. The guard must refuse
        # to auto-migrate (RF-16) so a developer can decide whether
        # to baseline the schema (``alembic stamp head``) or wipe the
        # volume. Applying migrations here would almost certainly
        # collide with the existing objects and lose data.
        assert decideMigrationAction(
            DbState(hasAlembicVersion=False, hasUserTables=True)
        ) == "abort"

    @pytest.mark.parametrize(
        "state, expected",
        [
            # Empty database -> apply.
            (
                DbState(hasAlembicVersion=False, hasUserTables=False),
                "apply",
            ),
            # Has alembic history, no user tables -> apply (pending only).
            (
                DbState(hasAlembicVersion=True, hasUserTables=False),
                "apply",
            ),
            # Has alembic history and user tables -> apply (pending only).
            (
                DbState(hasAlembicVersion=True, hasUserTables=True),
                "apply",
            ),
            # User tables without alembic history -> abort (RF-16).
            (
                DbState(hasAlembicVersion=False, hasUserTables=True),
                "abort",
            ),
        ],
    )
    def test_decision_table(self, state: DbState, expected: str) -> None:
        # The table-driven test makes the contract obvious: only one
        # of the four (hasAlembicVersion, hasUserTables) combinations
        # is forbidden, and the rest must be accepted.
        assert decideMigrationAction(state) == expected

    def test_decision_returns_string_literal(self) -> None:
        # The return type is a ``Literal["apply", "skip", "abort"]``.
        # The runtime value is always one of those three strings so
        # callers can ``match`` on it without an exhaustive default.
        result = decideMigrationAction(
            DbState(hasAlembicVersion=False, hasUserTables=False)
        )
        assert result in {"apply", "skip", "abort"}


class TestMigrationGuardIsPure:
    """``decideMigrationAction`` must not depend on external state."""

    def test_decision_is_deterministic_for_same_input(self) -> None:
        # Pure functions return equal outputs for equal inputs (P3 of
        # the constitution: the domain stays free of framework
        # dependencies and side effects).
        state = DbState(hasAlembicVersion=False, hasUserTables=True)
        first = decideMigrationAction(state)
        second = decideMigrationAction(state)
        assert first == second == "abort"

    def test_decision_does_not_mutate_input(self) -> None:
        # The guard must not poke at the caller's state: returning
        # ``"abort"`` does not flip the flags.
        state = DbState(hasAlembicVersion=False, hasUserTables=True)
        original = DbState(hasAlembicVersion=False, hasUserTables=True)
        decideMigrationAction(state)
        assert state == original
