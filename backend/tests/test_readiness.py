"""Tests for the pure readiness aggregation domain function.

The domain layer must remain free of framework dependencies (see
docs/constitution.md, principle 3). These tests therefore import only
the pure `aggregateReadiness` function and its supporting data types.
They must pass without any infrastructure service running.
"""

from __future__ import annotations

import pytest

from app.domain.readiness import (
    CheckResult,
    ReadinessReport,
    aggregateReadiness,
)


class TestAggregateReadiness:
    """Behavior of `aggregateReadiness` per the spec (RF-9)."""

    def test_all_checks_ok_reports_ready(self) -> None:
        checks = [
            CheckResult(name="postgres", ok=True),
            CheckResult(name="redis", ok=True),
        ]
        report = aggregateReadiness(checks)
        assert isinstance(report, ReadinessReport)
        assert report.ready is True
        assert report.checks == checks

    def test_one_check_down_reports_not_ready(self) -> None:
        failing = CheckResult(name="redis", ok=False, detail="connection refused")
        checks = [
            CheckResult(name="postgres", ok=True),
            failing,
        ]
        report = aggregateReadiness(checks)
        assert report.ready is False
        # The failing probe is preserved in the report so the developer
        # can identify which dependency is unavailable (RF-7, RF-9).
        assert report.checks == checks
        assert failing in report.checks

    def test_empty_check_list_is_ready(self) -> None:
        # Vacuous truth: with no checks, there is nothing failing.
        # This keeps the function total and free of edge-case branches.
        report = aggregateReadiness([])
        assert report.ready is True
        assert report.checks == []

    def test_every_check_down_reports_not_ready(self) -> None:
        checks = [
            CheckResult(name="postgres", ok=False, detail="timeout"),
            CheckResult(name="redis", ok=False, detail="timeout"),
        ]
        report = aggregateReadiness(checks)
        assert report.ready is False
        assert all(not check.ok for check in report.checks)

    def test_check_result_with_detail_is_preserved(self) -> None:
        detail = "could not resolve host 'postgres'"
        checks = [CheckResult(name="postgres", ok=False, detail=detail)]
        report = aggregateReadiness(checks)
        assert report.checks[0].detail == detail

    @pytest.mark.parametrize(
        "checks, expected_ready",
        [
            ([CheckResult(name="a", ok=True)], True),
            ([CheckResult(name="a", ok=False)], False),
            (
                [
                    CheckResult(name="a", ok=True),
                    CheckResult(name="b", ok=True),
                    CheckResult(name="c", ok=True),
                ],
                True,
            ),
            (
                [
                    CheckResult(name="a", ok=True),
                    CheckResult(name="b", ok=False),
                    CheckResult(name="c", ok=True),
                ],
                False,
            ),
        ],
    )
    def test_aggregate_readiness_table(
        self, checks: list[CheckResult], expected_ready: bool
    ) -> None:
        # Table-driven check covering common combinations.
        report = aggregateReadiness(checks)
        assert report.ready is expected_ready

    def test_readiness_report_is_pure_data(self) -> None:
        # The function is pure: calling it twice with the same input
        # must produce equal (not just equal-by-attribute) results, and
        # must not mutate the input list.
        checks = [
            CheckResult(name="postgres", ok=True),
            CheckResult(name="redis", ok=True),
        ]
        original_snapshot = list(checks)
        first = aggregateReadiness(checks)
        second = aggregateReadiness(checks)
        assert first == second
        assert first is not second  # a fresh object every call
        assert checks == original_snapshot
