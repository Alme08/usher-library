"""Integration tests for the real connectivity probes (spec 002 / T2, RF-3(b)).

These tests exercise :func:`app.infrastructure.probes.check_postgres`
and :func:`app.infrastructure.probes.check_redis` against the
throwaway stack documented in ``plan.md`` §5
(``usher_verify_net``, ``usher-verify-db``, ``usher-verify-redis``),
not against fakes. The unit suite ``tests/test_probes.py`` already
covers the *behaviour* of the probes (translation from exception to
``CheckResult``) with doubles; the value of running the probes here is
that the real asyncpg and redis-py code paths are exercised against
real servers, and the failure cases prove that the dependency name
("postgres" / "redis") is preserved when the dependency is down — the
same contract the readiness endpoint and the entrypoint rely on to
identify the broken dependency (RF-7, RF-9).

The disposable stack recipe lives in ``plan.md`` §5 and is driven by
``scripts/verify.sh database``. Activating this suite requires
``USHER_RUN_INTEGRATION=1``; otherwise the integration tests are
skipped (see ``conftest.py``).
"""

from __future__ import annotations

import os
import urllib.parse

import pytest

from app.core.config import Settings
from app.domain.readiness import CheckResult
from app.infrastructure.probes import check_postgres, check_redis

pytestmark = pytest.mark.integration


def _disposable_pg_settings() -> Settings:
    """Build a ``Settings`` instance pointing at ``usher-verify-db``.

    ``scripts/verify.sh database`` conveys the address only through the
    ``DATABASE_URL`` environment variable in the form
    ``postgresql+asyncpg://user:password@host:port/db``. The probes
    connect with the per-field settings, so we parse the URL once and
    project it onto a fresh ``Settings`` whose other fields fall back
    to their development defaults.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise pytest.skip(
            "DATABASE_URL is not set; the probe suite needs a target DB"
        )
    bare = url
    if "://" in bare:
        bare = bare.split("://", 1)[1]
    parsed = urllib.parse.urlparse("postgresql://" + bare)
    return Settings(
        postgres_host=parsed.hostname or "usher-verify-db",
        postgres_port=parsed.port or 5432,
        postgres_user=parsed.username or "usher",
        postgres_password=parsed.password or "",
        postgres_db=(parsed.path or "/").lstrip("/") or "usher_verify",
        database_url=url,
    )


def _disposable_redis_settings() -> Settings:
    """Build a ``Settings`` instance pointing at ``usher-verify-redis``.

    ``scripts/verify.sh database`` sets ``REDIS_URL`` to the address of
    the disposable Redis container. The probe consumes
    ``settings.redis_url`` directly, so we only need to mirror that
    single field onto the settings; everything else keeps its default.
    """
    url = os.environ.get("REDIS_URL")
    if not url:
        raise pytest.skip(
            "REDIS_URL is not set; the probe suite needs a target Redis"
        )
    return Settings(redis_url=url)


# ---------------------------------------------------------------------------
# Real disposable services: postgres + redis must report ``ok=True``.
# ---------------------------------------------------------------------------


class TestPostgresProbeAgainstDisposable:
    """``check_postgres`` against the throwaway PostgreSQL 16."""

    @pytest.mark.asyncio
    async def test_check_postgres_returns_ok_against_disposable_db(self) -> None:
        result = await check_postgres(_disposable_pg_settings())
        assert result == CheckResult(name="postgres", ok=True, detail=None), (
            f"check_postgres against the disposable DB should be OK, "
            f"got {result!r}"
        )

    @pytest.mark.asyncio
    async def test_check_postgres_failure_names_the_dependency(self) -> None:
        # Negative case: a port with no listener. The probe must NOT
        # raise and must return a ``CheckResult`` whose ``name`` is
        # exactly "postgres" — that is the contract the readiness
        # endpoint and the entrypoint rely on (RF-7, RF-9).
        # 127.0.0.1:1 is reserved and never accepts connections on the
        # CI runner, so the connect call returns ECONNREFUSED almost
        # immediately, well within ``probe_timeout_seconds``.
        settings = Settings(
            postgres_host="127.0.0.1",
            postgres_port=1,
            postgres_user="usher",
            postgres_password="verify",
            postgres_db="usher_verify",
            probe_timeout_seconds=1.0,
        )
        result = await check_postgres(settings)
        assert result.name == "postgres", (
            "the failing probe must still name 'postgres' so RF-7 can "
            "identify the broken dependency"
        )
        assert result.ok is False, (
            f"a connect refused failure must surface as ok=False, got {result!r}"
        )
        assert result.detail is not None and result.detail, (
            "a failing probe must carry a non-empty detail"
        )


class TestRedisProbeAgainstDisposable:
    """``check_redis`` against the throwaway Redis 7."""

    @pytest.mark.asyncio
    async def test_check_redis_returns_ok_against_disposable_redis(self) -> None:
        result = await check_redis(_disposable_redis_settings())
        assert result == CheckResult(name="redis", ok=True, detail=None), (
            f"check_redis against the disposable Redis should be OK, "
            f"got {result!r}"
        )

    @pytest.mark.asyncio
    async def test_check_redis_failure_names_the_dependency(self) -> None:
        # Negative case: a port with no listener. The probe must NOT
        # raise and must return a ``CheckResult`` whose ``name`` is
        # exactly "redis" — same contract as above (RF-7, RF-9).
        settings = Settings(
            redis_url="redis://127.0.0.1:1/0",
            probe_timeout_seconds=1.0,
        )
        result = await check_redis(settings)
        assert result.name == "redis", (
            "the failing probe must still name 'redis' so RF-7 can "
            "identify the broken dependency"
        )
        assert result.ok is False, (
            f"a connect refused failure must surface as ok=False, got {result!r}"
        )
        assert result.detail is not None and result.detail, (
            "a failing probe must carry a non-empty detail"
        )
