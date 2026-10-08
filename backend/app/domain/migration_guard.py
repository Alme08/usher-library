"""Pure migration-guard domain function (RF-16).

This module belongs to the ``domain`` layer, which must stay free of
FastAPI, SQLAlchemy, Alembic and PostgreSQL imports (constitution, P3).
The function defined here is the decision rule the backend uses when it
boots against a database whose history is unknown:

* **Empty database** — no tables at all. The guard returns
  ``"apply"`` so Alembic creates the full Initial Schema on first run
  (RF-14).
* **Database with ``alembic_version``** — Alembic has been here
  before. The guard returns ``"apply"`` and Alembic applies only the
  revisions that are still pending (RF-4, RF-15).
* **Database with user tables but no ``alembic_version``** — somebody
  provisioned the schema by hand, or the volume pre-dates Alembic.
  Applying migrations blindly here would collide with the existing
  objects and risk losing data, so the guard returns ``"abort"`` and
  the entrypoint logs a clear message and exits non-zero (RF-16).

The ``"skip"`` literal exists for completeness so the function's
signature covers every observable terminal state of an Alembic run
("nothing to do" is a valid, if currently unused, outcome that the
infrastructure layer may report if it inspects the database after the
decision and finds no pending revisions).

Keeping this function pure makes the rule trivially unit-testable
without any infrastructure (RNF-2, RNF-5) and gives the entrypoint a
stable contract for what to do at start-up time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# A database state ready for the guard. The flags describe what the
# infrastructure layer has already observed about the live database.
@dataclass(frozen=True)
class DbState:
    """Snapshot of the database before the guard runs.

    Attributes:
        hasAlembicVersion: True when the ``alembic_version`` table
            exists in the current schema. ``True`` means Alembic has
            already been used against this database.
        hasUserTables: True when at least one table outside the
            Alembic bookkeeping tables (``alembic_version``) exists
            in the current schema. ``True`` means there is some
            application data in the database, regardless of whether
            Alembic knows about it.
    """

    hasAlembicVersion: bool
    hasUserTables: bool


# A migration action is one of three values. The infrastructure layer
# matches on it to decide whether to invoke ``alembic upgrade head``
# (apply), do nothing (skip) or refuse to start (abort).
MigrationAction = Literal["apply", "skip", "abort"]


def decideMigrationAction(dbState: DbState) -> MigrationAction:
    """Decide what the entrypoint should do with the database state.

    The rule (RF-16, plan §2):

    * Empty database (``hasUserTables=False``) → ``"apply"``.
      This is the typical first ``docker compose up`` against a fresh
      data volume; Alembic creates the full Initial Schema.
    * ``alembic_version`` present (``hasAlembicVersion=True``) →
      ``"apply"``. The function does not care whether pending
      revisions exist; that question is for Alembic to answer at
      upgrade time. Returning ``"apply"`` here is the safe default:
      when there is nothing to do Alembic is a no-op.
    * User tables present *and* no Alembic history
      (``hasAlembicVersion=False`` and ``hasUserTables=True``) →
      ``"abort"``. The entrypoint logs a clear message and exits
      non-zero without modifying schema or data (RF-16).

    Args:
        dbState: Snapshot of the database collected by the
            infrastructure layer.

    Returns:
        One of ``"apply"``, ``"skip"`` or ``"abort"``.
    """
    # Tables exist but Alembic has never recorded a revision: refuse
    # to start. This is the only "dangerous" state and the entire
    # reason the guard exists. Putting it first keeps the early-return
    # branch obvious to a reader skimming the code.
    if dbState.hasUserTables and not dbState.hasAlembicVersion:
        return "abort"

    # Everything else is a state Alembic can safely reason about:
    # either the database is empty (Alembic will create the schema)
    # or Alembic has been here before (Alembic will apply whatever is
    # still pending).
    return "apply"
