"""Tests for the connectivity probes used by the `/health` endpoint (RF-9).

These tests verify the *mapping* from connection failures to
`CheckResult` (so the readiness endpoint can identify which
dependency is unavailable, RF-7) without actually opening a socket
to PostgreSQL or Redis. The async clients are monkey-patched so the
tests run offline (RNF-2).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from app.core.config import Settings
from app.domain.readiness import CheckResult
from app.infrastructure.probes import (
    check_postgres,
    check_redis,
    default_probes,
)


class TestPostgresProbe:
    """`check_postgres` must convert connection failures into a `CheckResult`."""

    @pytest.mark.asyncio
    async def test_returns_ok_when_ping_succeeds(self) -> None:
        # Arrange: the mocked asyncpg connection reports success.

        class _FakeConnection:
            async def execute(self, _query: str) -> str:
                return "SELECT 1"

            async def close(self) -> None:
                return None

        async def _fake_connect(**_kwargs: Any) -> _FakeConnection:
            return _FakeConnection()

        settings = Settings(backend_port=8000)

        with patch("app.infrastructure.probes.asyncpg.connect", _fake_connect):
            result = await check_postgres(settings)

        # Assert
        assert result == CheckResult(name="postgres", ok=True, detail=None)

    @pytest.mark.asyncio
    async def test_returns_failed_check_when_connection_refused(self) -> None:
        # Arrange: asyncpg.connect raises as if the port were closed.

        async def _fake_connect(**_kwargs: Any) -> None:
            raise ConnectionRefusedError("connection refused")

        settings = Settings(backend_port=8000)

        with patch("app.infrastructure.probes.asyncpg.connect", _fake_connect):
            result = await check_postgres(settings)

        # Assert: the failure is captured, not propagated (RF-7, RF-9).
        assert result.name == "postgres"
        assert result.ok is False
        assert result.detail is not None
        assert "ConnectionRefusedError" in result.detail
        assert "connection refused" in result.detail

    @pytest.mark.asyncio
    async def test_returns_failed_check_when_query_times_out(self) -> None:
        # Arrange: connection succeeds but the SELECT times out.

        class _FakeConnection:
            async def execute(self, _query: str) -> None:
                raise TimeoutError("query timeout")

            async def close(self) -> None:
                return None

        async def _fake_connect(**_kwargs: Any) -> _FakeConnection:
            return _FakeConnection()

        settings = Settings(backend_port=8000)

        with patch("app.infrastructure.probes.asyncpg.connect", _fake_connect):
            result = await check_postgres(settings)

        assert result.name == "postgres"
        assert result.ok is False
        assert result.detail is not None
        assert "TimeoutError" in result.detail


class TestRedisProbe:
    """`check_redis` must convert connection failures into a `CheckResult`."""

    @pytest.mark.asyncio
    async def test_returns_ok_when_ping_succeeds(self) -> None:
        # Arrange: fake redis client whose ping returns truthy.

        class _FakeRedis:
            async def ping(self) -> bool:
                return True

            async def aclose(self) -> None:
                return None

        def _fake_from_url(*_args: Any, **_kwargs: Any) -> _FakeRedis:
            return _FakeRedis()

        settings = Settings(backend_port=8000)

        with patch(
            "app.infrastructure.probes.redis_async.from_url", _fake_from_url
        ):
            result = await check_redis(settings)

        assert result == CheckResult(name="redis", ok=True, detail=None)

    @pytest.mark.asyncio
    async def test_returns_failed_check_when_client_constructor_raises(
        self,
    ) -> None:
        # Arrange: redis.from_url raises (DNS failure, auth failure, etc.).

        def _fake_from_url(*_args: Any, **_kwargs: Any) -> None:
            raise ConnectionError("dns lookup failed")

        settings = Settings(backend_port=8000)

        with patch(
            "app.infrastructure.probes.redis_async.from_url", _fake_from_url
        ):
            result = await check_redis(settings)

        assert result.name == "redis"
        assert result.ok is False
        assert result.detail is not None
        assert "ConnectionError" in result.detail

    @pytest.mark.asyncio
    async def test_returns_failed_check_when_ping_times_out(self) -> None:
        # Arrange: client constructs fine but ping times out.

        class _FakeRedis:
            async def ping(self) -> None:
                raise TimeoutError("ping timeout")

            async def aclose(self) -> None:
                return None

        def _fake_from_url(*_args: Any, **_kwargs: Any) -> _FakeRedis:
            return _FakeRedis()

        settings = Settings(backend_port=8000)

        with patch(
            "app.infrastructure.probes.redis_async.from_url", _fake_from_url
        ):
            result = await check_redis(settings)

        assert result.name == "redis"
        assert result.ok is False
        assert result.detail is not None
        assert "TimeoutError" in result.detail


class TestDefaultProbes:
    """`default_probes` wires the real probes behind `Probe` callables."""

    def test_default_probes_returns_two_callables(self) -> None:
        probes = default_probes()
        assert len(probes) == 2

    @pytest.mark.asyncio
    async def test_default_probes_callables_return_check_results(self) -> None:
        # Each callable must be awaitable and return a `CheckResult`
        # when invoked. Patching the underlying clients keeps the test
        # offline (RNF-2).

        class _FakeAsyncpgConnection:
            async def execute(self, _query: str) -> str:
                return "SELECT 1"

            async def close(self) -> None:
                return None

        async def _fake_asyncpg_connect(**_kwargs: Any) -> _FakeAsyncpgConnection:
            return _FakeAsyncpgConnection()

        class _FakeRedis:
            async def ping(self) -> bool:
                return True

            async def aclose(self) -> None:
                return None

        def _fake_redis_from_url(
            *_args: Any, **_kwargs: Any
        ) -> _FakeRedis:
            return _FakeRedis()

        probes = default_probes()
        with patch(
            "app.infrastructure.probes.asyncpg.connect", _fake_asyncpg_connect
        ), patch(
            "app.infrastructure.probes.redis_async.from_url",
            _fake_redis_from_url,
        ):
            results = [await probe() for probe in probes]

        names = {result.name for result in results}
        assert names == {"postgres", "redis"}
        assert all(result.ok for result in results)
