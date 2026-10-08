"""`GET /health` endpoint (RF-9).

The endpoint runs every registered probe in parallel, aggregates the
results with the pure `aggregateReadiness` domain function, and
returns:

- 200 with `{"status": "ok", "checks": [...]}` when every probe is OK.
- 503 with `{"status": "degraded", "checks": [...]}` when at least
  one probe is down. The failing probe is preserved in the response
  so the developer can identify which dependency is unavailable
  (RF-7, RF-9).

Probes are injected through a FastAPI dependency (`get_probes`) so
tests can substitute fakes without touching the network (RNF-2).
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.domain.readiness import CheckResult, aggregateReadiness
from app.infrastructure.probes import Probe, default_probes

router = APIRouter(tags=["health"])


def get_probes() -> list[Probe]:
    """Dependency that returns the list of probes to run.

    Wrapping the `default_probes` call here keeps the FastAPI
    `Depends(...)` call site simple and gives tests a stable symbol
    to override (`health.get_probes`).
    """
    return default_probes()


def _serialize_check(check: CheckResult) -> dict[str, object]:
    """Render a `CheckResult` as a JSON-safe dict.

    `detail` is always included (as `None` when absent) so the
    response shape is predictable for clients and tests.
    """
    return {
        "name": check.name,
        "ok": check.ok,
        "detail": check.detail,
    }


# The `Annotated` form is the modern FastAPI idiom and silences the
# `B008` lint rule that flags `Depends` calls in argument defaults.
ProbesDependency = Annotated[list[Probe], Depends(get_probes)]


@router.get("/health")
async def health(probes: ProbesDependency) -> JSONResponse:
    """Run every probe and return the aggregated readiness report."""
    results = await asyncio.gather(*(probe() for probe in probes))
    report = aggregateReadiness(list(results))

    body: dict[str, object] = {
        "status": "ok" if report.ready else "degraded",
        "checks": [_serialize_check(check) for check in report.checks],
    }
    http_status = status.HTTP_200_OK if report.ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=http_status, content=body)
