"""Integration test configuration.

These tests talk to a real PostgreSQL and Redis. They are skipped
unless the runner opts in with ``USHER_RUN_INTEGRATION=1`` so the
default ``pytest -q`` of AGENTS.md keeps running offline (RNF-2):
spec 002 §2.5 / plan §5.

The disposable stack lives outside ``docker compose`` by design
(plan §2.4): no port is published and the developer volume
``usher_postgres_data`` is never touched. The exact recipe lives in
``plan.md`` §5; ``scripts/verify.sh database`` (T3) drives it from
CI while ``USHER_RUN_INTEGRATION=1``.
"""

from __future__ import annotations

import os

import pytest

INTEGRATION_FLAG = "USHER_RUN_INTEGRATION"

_REASON = (
    "integration tests are skipped by default; set "
    f"{INTEGRATION_FLAG}=1 to enable them (spec 002 / plan §5)."
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip every test marked ``integration`` unless the opt-in flag is set.

    The suite is collected (so coverage and collection errors are
    surfaced) but the items are reported as skipped instead of failing
    when the disposable stack is not available — the developer's
    default run never depends on Docker.
    """
    if os.environ.get(INTEGRATION_FLAG) == "1":
        return
    skip_marker = pytest.mark.skip(reason=_REASON)
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)
