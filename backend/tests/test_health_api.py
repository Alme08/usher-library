"""Tests for the `GET /health` endpoint.

The endpoint must report 200 when every dependency probe is OK and 503
when at least one is down, including the failing probe name so the
developer can identify it (RF-9, RF-7).

These tests inject fake probes via FastAPI dependency overrides, so
they run without PostgreSQL, Redis or Keycloak (RNF-2, RNF-5).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import health as health_module
from app.domain.readiness import CheckResult
from app.infrastructure.probes import Probe
from app.main import create_app


def _override_probes_with(results: list[CheckResult]):
    """Build a FastAPI dependency that returns fake probes for `results`.

    The returned callable is used as a `dependency_overrides` target:
    when FastAPI resolves the `get_probes` dependency, it receives
    the prepared list of async probes that yield each `CheckResult`
    in `results`. Capturing `result` via a default argument avoids the
    classic late-binding bug in the loop.
    """
    probes: list[Probe] = []
    for i, result in enumerate(results):
        # Capture `result` via a default-arg trick to avoid late binding.
        async def probe(_r: CheckResult = result) -> CheckResult:
            return _r

        probe.__name__ = f"fake_probe_{i}_{result.name}"
        probes.append(probe)

    def _provider() -> list[Probe]:
        return probes

    return _provider


@pytest.fixture
def app():
    application = create_app()
    yield application
    # No teardown needed; overrides are scoped to the application instance.


def test_health_returns_200_when_all_probes_ok(app) -> None:
    results = [
        CheckResult(name="postgres", ok=True),
        CheckResult(name="redis", ok=True),
    ]
    app.dependency_overrides[health_module.get_probes] = _override_probes_with(results)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ok",
        "checks": [
            {"name": "postgres", "ok": True, "detail": None},
            {"name": "redis", "ok": True, "detail": None},
        ],
    }


def test_health_returns_503_when_a_probe_is_down(app) -> None:
    results = [
        CheckResult(name="postgres", ok=True),
        CheckResult(name="redis", ok=False, detail="connection refused"),
    ]
    app.dependency_overrides[health_module.get_probes] = _override_probes_with(results)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    # The failing probe is preserved in the response so the developer
    # can identify the broken dependency (RF-7, RF-9).
    by_name = {check["name"]: check for check in body["checks"]}
    assert by_name["postgres"]["ok"] is True
    assert by_name["redis"]["ok"] is False
    assert by_name["redis"]["detail"] == "connection refused"


def test_health_response_identifies_every_failing_probe(app) -> None:
    results = [
        CheckResult(name="postgres", ok=False, detail="timeout"),
        CheckResult(name="redis", ok=False, detail="refused"),
    ]
    app.dependency_overrides[health_module.get_probes] = _override_probes_with(results)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    failing = [c for c in body["checks"] if not c["ok"]]
    failing_names = {c["name"] for c in failing}
    assert failing_names == {"postgres", "redis"}


def test_health_endpoint_runs_without_services(app) -> None:
    # Default behavior (no override) must still answer; the production
    # wiring is exercised in T6. For T2 we only assert the endpoint is
    # reachable, so we override with a no-op probe list to avoid any
    # network call.
    app.dependency_overrides[health_module.get_probes] = _override_probes_with([])

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": []}
