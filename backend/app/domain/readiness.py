"""Pure readiness aggregation domain function.

This module belongs to the `domain` layer, which must stay free of
FastAPI, SQLAlchemy, Redis and Keycloak imports (constitution, P3).
The function defined here takes already-collected probe results and
turns them into a `ReadinessReport` consumable by the HTTP layer.

Keeping this function pure makes it trivially testable without
infrastructure (RNF-2, RNF-5) and gives us a stable contract for the
`GET /health` endpoint (RF-9).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single connectivity probe.

    Attributes:
        name: Identifier of the probed dependency (e.g. "postgres").
        ok: True when the probe succeeded, False otherwise.
        detail: Optional human-readable explanation of the failure
            (kept when the probe fails; ignored when it succeeds).
    """

    name: str
    ok: bool
    detail: str | None = None


@dataclass(frozen=True)
class ReadinessReport:
    """Aggregated readiness state, ready to be serialized as JSON.

    Attributes:
        ready: True when every probe succeeded (vacuous truth for an
            empty input list).
        checks: The original probe results, in the order they were
            collected.
    """

    ready: bool
    checks: list[CheckResult]


def aggregateReadiness(checks: list[CheckResult]) -> ReadinessReport:
    """Aggregate probe results into a `ReadinessReport`.

    The function is pure: it does not mutate `checks`, does not touch
    any global state, and is deterministic for a given input. The
    readiness signal is the conjunction of every probe's `ok` flag.

    Args:
        checks: Probe results produced by the infrastructure layer.

    Returns:
        A `ReadinessReport` with `ready = all(c.ok for c in checks)`
        and the same `checks` list (defensively copied to keep the
        function side-effect free even if callers mutate later).
    """
    # `list(checks)` keeps the function free of side effects on the
    # caller's list without changing the per-element semantics.
    snapshot = list(checks)
    ready = all(check.ok for check in snapshot)
    return ReadinessReport(ready=ready, checks=snapshot)
