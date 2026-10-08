"""Connectivity probes for the `/health` endpoint.

This module is the only place allowed to know *how* to reach
PostgreSQL and Redis. The domain layer must stay free of any client
library (constitution, P3), so the rest of the application only sees
the `CheckResult` produced here.

The probes are exposed as async callables returning a `CheckResult`
so the HTTP layer can `await` them in parallel. The probe list is
injected into the health endpoint through a FastAPI dependency, which
is the seam tests use to substitute fakes without touching the
network (RNF-2).

Every probe is intentionally *non-raising*: any failure (connection
refused, DNS error, timeout, authentication failure...) is captured
and rendered as a `CheckResult` with ``ok=False`` and a short human
readable ``detail``. That contract is what lets the readiness
endpoint identify *which* dependency is down (RF-7, RF-9).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

import asyncpg
import redis.asyncio as redis_async
from redis import exceptions as redis_exceptions

from app.core.config import Settings, get_settings
from app.domain.readiness import CheckResult

# A `Probe` is an awaitable that produces a `CheckResult`. Defining
# the type alias here keeps the public API of the module self-explanatory.
Probe = Callable[[], Awaitable[CheckResult]]


# Errors that the probes must catch and translate into a `CheckResult`
# rather than propagating. Anything outside this set is a bug and is
# intentionally allowed to surface during tests.
_POSTGRES_TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    asyncio.TimeoutError,
    TimeoutError,
    asyncpg.PostgresError,
)


_REDIS_TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    asyncio.TimeoutError,
    TimeoutError,
    redis_exceptions.RedisError,
)


def _format_detail(exc: BaseException) -> str:
    """Render an exception as a short, JSON-safe diagnostic string.

    The string deliberately avoids newlines and embeds the exception
    type so the developer can tell at a glance whether the failure
    is a connection refused, a DNS error, an auth failure or a query
    timeout (RF-7, RF-8).
    """
    message = str(exc).strip() or "(no message)"
    # Collapse newlines to spaces so the JSON response stays on one line.
    message = message.replace("\n", " ").replace("\r", " ")
    return f"{type(exc).__name__}: {message}"


async def check_postgres(settings: Settings) -> CheckResult:
    """Probe PostgreSQL connectivity with a short timeout (RF-9).

    The probe opens an ``asyncpg`` connection, executes ``SELECT 1``
    and closes the connection. Any failure (DNS, auth, timeout, server
    error) is converted to a ``CheckResult(name="postgres", ok=False,
    detail=...)`` so the readiness endpoint can identify the broken
    dependency (RF-7). The connection timeout is taken from
    ``settings.probe_timeout_seconds`` so a hanging server cannot stall
    the response.
    """
    timeout = settings.probe_timeout_seconds
    try:
        connection = await asyncpg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            user=settings.postgres_user,
            password=settings.postgres_password,
            database=settings.postgres_db,
            timeout=timeout,
        )
    except _POSTGRES_TRANSIENT_ERRORS as exc:
        return CheckResult(name="postgres", ok=False, detail=_format_detail(exc))

    try:
        await asyncio.wait_for(connection.execute("SELECT 1"), timeout=timeout)
    except _POSTGRES_TRANSIENT_ERRORS as exc:
        return CheckResult(name="postgres", ok=False, detail=_format_detail(exc))
    finally:
        # Closing a probe connection must never poison the result;
        # the SELECT already produced the authoritative answer.
        with contextlib.suppress(_POSTGRES_TRANSIENT_ERRORS):
            await connection.close()

    return CheckResult(name="postgres", ok=True)


async def check_redis(settings: Settings) -> CheckResult:
    """Probe Redis connectivity with a short timeout (RF-9).

    The probe constructs an async Redis client from the configured URL
    and issues a ``PING``. Any failure (DNS, connection refused, auth) is
    converted to a ``CheckResult(name="redis", ok=False, detail=...)``
    so the readiness endpoint can identify the broken dependency
    (RF-7). The client is closed on every path to avoid leaks across
    repeated health checks.
    """
    timeout = settings.probe_timeout_seconds
    try:
        client = redis_async.from_url(
            settings.redis_url,
            socket_connect_timeout=timeout,
            socket_timeout=timeout,
        )
    except _REDIS_TRANSIENT_ERRORS as exc:
        return CheckResult(name="redis", ok=False, detail=_format_detail(exc))

    try:
        try:
            await asyncio.wait_for(client.ping(), timeout=timeout)
        except _REDIS_TRANSIENT_ERRORS as exc:
            return CheckResult(name="redis", ok=False, detail=_format_detail(exc))
    finally:
        # Closing the client must never mask the result of the
        # ping; the ping already produced the authoritative answer.
        with contextlib.suppress(_REDIS_TRANSIENT_ERRORS):
            await client.aclose()

    return CheckResult(name="redis", ok=True)


def default_probes() -> list[Probe]:
    """FastAPI dependency that returns the production probe list.

    Tests override this dependency to inject fakes. Keeping the
    default construction here means the production wiring stays
    explicit and discoverable from a single place.
    """
    settings = get_settings()
    return [
        lambda: check_postgres(settings),
        lambda: check_redis(settings),
    ]
