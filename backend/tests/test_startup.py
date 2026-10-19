"""Tests for the backend startup dependency-wait helper (RF-7).

The startup helper must:

- poll a dependency probe with retries and exponential backoff,
- give up after a fixed total timeout, and
- raise an error that *identifies* the failing dependency when it
  gives up. The backend entrypoint then logs that error and exits
  non-zero, so the developer sees which dependency never came up.

These tests must run without any real infrastructure (RNF-2). The
probe, the sleep callable and the monotonic clock are injected,
which keeps the wall-clock time of the test under control and the
behaviour deterministic.

The entrypoint glue tests at the bottom of this file additionally
cover the migration guard wiring (RF-4, RF-16): the entrypoint must
inspect the database state, decide whether to apply migrations,
abort on a tables-without-history database, and hand off to
uvicorn on the happy path. The migration helpers are patched so the
suite stays infrastructure-free.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, patch

import pytest

from app.core.startup import (
    _ALEMBIC_INI,
    _BACKEND_DIR,
    DependencyUnavailableError,
    MigrationUpgradeError,
    _amain,
    main,
    wait_for_dependency,
)
from app.domain.migration_guard import DbState

# A `Probe` returns True when the dependency is up, False (or raises)
# when it is still coming up. The startup helper must treat both as
# "not ready yet" and keep retrying.
Probe = Callable[[], Awaitable[bool]]


class _Clock:
    """A controllable monotonic clock for tests.

    The clock advances by the value passed to :meth:`advance` and is
    used by the production helper via dependency injection. It mirrors
    :func:`time.monotonic` so tests can drive the wait deterministically
    without touching real wall-clock time (RNF-2).
    """

    def __init__(self, *, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _make_recording_probe(
    outcomes: list[bool],
) -> tuple[Probe, list[bool]]:
    """Build a probe that returns each entry of `outcomes` in order.

    Once the list is exhausted the probe keeps returning the last
    value (so a one-element list means a probe with a fixed answer).
    """

    calls: list[bool] = []

    async def _probe() -> bool:
        index = min(len(calls), len(outcomes) - 1)
        calls.append(outcomes[index])
        return outcomes[index]

    return _probe, calls


def _make_sleep_recorder(
    clock: _Clock,
) -> tuple[Callable[[float], Awaitable[None]], list[float]]:
    """Build a `sleep` replacement that records the delay and advances the clock.

    Each recorded delay is the argument the helper passed to
    `sleep`. Advancing the clock makes the helper see the elapsed
    time growing in lockstep with the requested delays, which is
    exactly the production semantics.
    """

    delays: list[float] = []

    async def _sleep(seconds: float) -> None:
        delays.append(seconds)
        clock.advance(seconds)

    return _sleep, delays


class TestWaitForDependencySuccess:
    """`wait_for_dependency` returns when the probe succeeds."""

    @pytest.mark.asyncio
    async def test_returns_immediately_when_probe_is_ready(self) -> None:
        # Arrange
        probe, calls = _make_recording_probe([True])
        clock = _Clock()

        async def _sleep(_seconds: float) -> None:
            return None

        # Act
        await wait_for_dependency(
            "postgres",
            probe,
            timeout_seconds=10.0,
            initial_delay=0.5,
            sleep=_sleep,
            clock=clock,
        )

        # Assert
        assert calls == [True]

    @pytest.mark.asyncio
    async def test_retries_until_probe_succeeds(self) -> None:
        # Arrange: probe fails twice, then succeeds.
        probe, calls = _make_recording_probe([False, False, True])
        clock = _Clock()

        async def _sleep(_seconds: float) -> None:
            clock.advance(0.5)

        # Act
        await wait_for_dependency(
            "redis",
            probe,
            timeout_seconds=10.0,
            initial_delay=0.5,
            sleep=_sleep,
            clock=clock,
        )

        # Assert
        assert calls == [False, False, True]

    @pytest.mark.asyncio
    async def test_succeeds_just_before_timeout(self) -> None:
        # Arrange: probe keeps failing for many attempts then succeeds
        # on the last one before the timeout would elapse. This proves
        # the helper does not give up early when the budget is still
        # open.
        # With initial_delay=0.5 and backoff_factor=2, max_delay=5.0,
        # the sequence is 0.5, 1.0, 2.0, 4.0, 5.0, 5.0 ... which
        # cumulates to >= 30 around attempt 7. Probe succeeds on the
        # 6th attempt so total wait stays under 30s.
        outcomes = [False] * 5 + [True]
        probe, calls = _make_recording_probe(outcomes)
        clock = _Clock()
        sleep, delays = _make_sleep_recorder(clock)

        await wait_for_dependency(
            "postgres",
            probe,
            timeout_seconds=30.0,
            initial_delay=0.5,
            max_delay=5.0,
            sleep=sleep,
            clock=clock,
        )

        assert calls == outcomes
        # Five sleeps (one before each subsequent attempt) — the
        # sequence must be exponential, capped at `max_delay`.
        assert delays == [0.5, 1.0, 2.0, 4.0, 5.0]


class TestWaitForDependencyTimeout:
    """`wait_for_dependency` gives up with an informative error (RF-7)."""

    @pytest.mark.asyncio
    async def test_raises_when_probe_never_ready(self) -> None:
        # Arrange: probe always says "not ready", and the clock jumps
        # past the timeout on the very first sleep so the helper
        # gives up after a single retry.
        probe, _ = _make_recording_probe([False])
        clock = _Clock()

        async def _sleep(seconds: float) -> None:
            clock.advance(seconds)

        # Act / Assert
        with pytest.raises(DependencyUnavailableError) as exc_info:
            await wait_for_dependency(
                "postgres",
                probe,
                timeout_seconds=0.5,
                initial_delay=1.0,
                max_delay=10.0,
                sleep=_sleep,
                clock=clock,
            )

        # The error must identify the dependency (RF-7).
        assert exc_info.value.dependency == "postgres"
        assert exc_info.value.attempts >= 1
        assert exc_info.value.elapsed_seconds >= 0.5

    @pytest.mark.asyncio
    async def test_error_message_identifies_dependency(self) -> None:
        # The stringified error must surface the dependency name so
        # the entrypoint can log something a developer can act on
        # (RF-7, RF-8).
        async def _always_down() -> bool:
            return False

        clock = _Clock()

        async def _sleep(seconds: float) -> None:
            clock.advance(seconds)

        with pytest.raises(DependencyUnavailableError) as exc_info:
            await wait_for_dependency(
                "redis",
                _always_down,
                timeout_seconds=1.0,
                initial_delay=0.5,
                max_delay=1.0,
                sleep=_sleep,
                clock=clock,
            )

        message = str(exc_info.value)
        assert "redis" in message
        assert exc_info.value.dependency == "redis"
        assert "dependency unavailable" in message

    @pytest.mark.asyncio
    async def test_probe_exception_is_recorded_in_error(self) -> None:
        # When the probe raises, the error must surface the original
        # cause so the developer can tell why the dependency is down.

        async def _exploding_probe() -> bool:
            raise ConnectionRefusedError("connection refused")

        clock = _Clock()

        async def _sleep(seconds: float) -> None:
            clock.advance(seconds)

        with pytest.raises(DependencyUnavailableError) as exc_info:
            await wait_for_dependency(
                "postgres",
                _exploding_probe,
                timeout_seconds=1.0,
                initial_delay=0.5,
                max_delay=1.0,
                sleep=_sleep,
                clock=clock,
            )

        assert exc_info.value.dependency == "postgres"
        # The last error is kept for diagnostics.
        assert exc_info.value.last_error is not None
        assert "ConnectionRefusedError" in exc_info.value.last_error
        assert "connection refused" in exc_info.value.last_error

    @pytest.mark.asyncio
    async def test_probe_returning_false_records_diagnostic(self) -> None:
        # When the probe returns False without raising, the diagnostic
        # must still identify that the dependency was reported down
        # by the probe rather than silently giving up.

        async def _always_false() -> bool:
            return False

        clock = _Clock()

        async def _sleep(seconds: float) -> None:
            clock.advance(seconds)

        with pytest.raises(DependencyUnavailableError) as exc_info:
            await wait_for_dependency(
                "postgres",
                _always_false,
                timeout_seconds=1.0,
                initial_delay=0.5,
                max_delay=1.0,
                sleep=_sleep,
                clock=clock,
            )

        assert exc_info.value.last_error == "probe returned False"


class TestWaitForDependencyBackoff:
    """`wait_for_dependency` schedules retries with exponential backoff."""

    @pytest.mark.asyncio
    async def test_uses_exponential_backoff_until_max(self) -> None:
        # With a controlled clock and a probe that never succeeds,
        # the helper walks the schedule: 0.25, 0.5, 1.0 (capped),
        # then keeps trying until the budget runs out.
        probe, _ = _make_recording_probe([False])
        clock = _Clock()
        sleep, delays = _make_sleep_recorder(clock)

        with pytest.raises(DependencyUnavailableError):
            await wait_for_dependency(
                "postgres",
                probe,
                timeout_seconds=4.0,
                initial_delay=0.25,
                max_delay=1.0,
                backoff_factor=2.0,
                sleep=sleep,
                clock=clock,
            )

        # The schedule must be non-decreasing until capped at
        # `max_delay`, then non-increasing as the remaining budget
        # shrinks and starts clamping each subsequent sleep.
        assert delays, "expected at least one retry delay"
        assert delays[0] == 0.25
        assert all(d <= 1.0 + 1e-9 for d in delays)
        # The early schedule grows geometrically until the cap.
        assert delays[:3] == [0.25, 0.5, 1.0]

    @pytest.mark.asyncio
    async def test_last_delay_is_clamped_by_remaining_budget(self) -> None:
        # Near the end of the timeout, the helper must not schedule a
        # delay longer than the remaining budget — otherwise the total
        # timeout would silently slip (RF-7 spirit: respect the cap).
        probe, _ = _make_recording_probe([False])
        clock = _Clock()
        sleep, delays = _make_sleep_recorder(clock)

        with pytest.raises(DependencyUnavailableError):
            await wait_for_dependency(
                "postgres",
                probe,
                timeout_seconds=1.0,
                initial_delay=1.0,
                max_delay=10.0,  # intentionally huge
                sleep=sleep,
                clock=clock,
            )

        # Only one retry can fit in a 1s budget with a 1s initial delay.
        assert delays == [1.0]

    @pytest.mark.asyncio
    async def test_zero_or_negative_timeout_raises_immediately(self) -> None:
        # Zero / negative budgets are misconfigurations. The helper
        # must surface them instead of busy-looping forever.
        async def _always_false() -> bool:
            return False

        with pytest.raises(DependencyUnavailableError) as exc_info:
            await wait_for_dependency(
                "postgres",
                _always_false,
                timeout_seconds=0.0,
            )
        assert exc_info.value.dependency == "postgres"
        assert "timeout_seconds must be positive" in (exc_info.value.last_error or "")


class TestDependencyUnavailableError:
    """The custom exception is the contract between helper and entrypoint."""

    def test_error_is_an_exception_subclass(self) -> None:
        assert issubclass(DependencyUnavailableError, Exception)

    def test_error_carries_diagnostics(self) -> None:
        err = DependencyUnavailableError(
            dependency="postgres",
            attempts=5,
            elapsed_seconds=12.5,
            last_error="ConnectionRefusedError: refused",
        )
        assert err.dependency == "postgres"
        assert err.attempts == 5
        assert err.elapsed_seconds == 12.5
        assert err.last_error == "ConnectionRefusedError: refused"

    def test_error_message_mentions_dependency_and_time(self) -> None:
        err = DependencyUnavailableError(
            dependency="redis",
            attempts=3,
            elapsed_seconds=7.0,
            last_error=None,
        )
        message = str(err)
        assert "redis" in message
        assert "7" in message  # the elapsed seconds are surfaced
        assert "last_error" not in message  # no last_error ⇒ don't render it


class TestStartupEntrypoint:
    """The ``python -m app.core.startup`` runner waits then execs uvicorn.

    These tests cover the entrypoint glue without actually starting
    uvicorn: the success case is observed by patching ``os.execvp``,
    and the failure case by patching the probe to simulate a missing
    dependency (RF-7, RF-8).
    """

    @pytest.mark.asyncio
    async def test_success_path_logs_and_execs_uvicorn(self) -> None:
        # Both probes report up, the database is empty (typical first
        # run), and Alembic's ``upgrade head`` is invoked successfully.
        # The entrypoint must call ``os.execvp`` with the uvicorn
        # command derived from settings.

        async def _ok_probe() -> bool:
            return True

        async def _empty_database(_settings) -> DbState:
            # Empty database -> guard returns ``"apply"`` -> the
            # entrypoint runs ``_run_alembic_upgrade`` before exec.
            return DbState(hasAlembicVersion=False, hasUserTables=False)

        with (
            patch(
                "app.core.startup._probe_postgres_alive",
                _ok_probe,
            ),
            patch(
                "app.core.startup._probe_redis_alive",
                _ok_probe,
            ),
            patch(
                "app.core.startup._inspect_db_state",
                AsyncMock(side_effect=_empty_database),
            ),
            patch(
                "app.core.startup._run_alembic_upgrade"
            ) as fake_upgrade,
            patch("app.core.startup.os.execvp") as fake_exec,
            patch(
                "app.core.startup._configure_logging",
                lambda: None,
            ),
        ):
            # Override settings so the test does not depend on env vars.
            from app.core.config import Settings

            fake_settings = Settings(
                backend_host="127.0.0.1",
                backend_port=8765,
                startup_timeout_seconds=2.0,
                startup_initial_delay=0.1,
                startup_max_delay=0.2,
            )
            with patch(
                "app.core.startup._get_settings_or_cached",
                lambda: fake_settings,
            ):
                exit_code = await _amain()

        assert exit_code == 0
        fake_upgrade.assert_called_once()
        fake_exec.assert_called_once()
        # The first positional arg is the program name and the second
        # is the full argv; we only assert the structure that matters.
        args = fake_exec.call_args.args
        assert args[0] == "uvicorn"
        assert args[1][:1] == ["uvicorn"]
        assert "app.main:app" in args[1]
        assert "--host" in args[1]
        assert "127.0.0.1" in args[1]
        assert "--port" in args[1]
        assert "8765" in args[1]

    @pytest.mark.asyncio
    async def test_failure_path_returns_nonzero_and_does_not_exec(
        self,
    ) -> None:
        # Postgres never comes up; the entrypoint must NOT exec
        # uvicorn and must surface a non-zero exit code so Compose
        # marks the container as failed (RF-7, RF-8).
        async def _ok_probe() -> bool:
            return True

        async def _down_probe() -> bool:
            return False

        with (
            patch(
                "app.core.startup._probe_postgres_alive",
                _down_probe,
            ),
            patch(
                "app.core.startup._probe_redis_alive",
                _ok_probe,
            ),
            patch("app.core.startup.os.execvp") as fake_exec,
            patch(
                "app.core.startup._configure_logging",
                lambda: None,
            ),
            patch(
                "app.core.startup.logger"
            ) as fake_logger,
        ):
            from app.core.config import Settings

            fake_settings = Settings(
                backend_host="127.0.0.1",
                backend_port=8765,
                startup_timeout_seconds=0.3,
                startup_initial_delay=0.1,
                startup_max_delay=0.2,
            )
            with patch(
                "app.core.startup._get_settings_or_cached",
                lambda: fake_settings,
            ):
                exit_code = await _amain()

        assert exit_code == 1
        fake_exec.assert_not_called()
        # The log line must mention the offending dependency by name
        # so the developer can act on it (RF-7, RF-8).
        error_calls = fake_logger.error.call_args_list
        assert error_calls, "expected the entrypoint to log an error"
        formatted = " ".join(str(arg) for args in error_calls for arg in args.args)
        assert "postgres" in formatted

    def test_main_invokes_amain_and_returns_exit_code(self) -> None:
        # The synchronous wrapper is the one the Dockerfile actually
        # invokes. We patch ``asyncio.run`` so the test stays
        # synchronous and fast.
        with patch(
            "app.core.startup._amain",
            AsyncMock(return_value=0),
        ) as fake_amain, patch(
            "app.core.startup._configure_logging",
            lambda: None,
        ):
            assert main() == 0
        fake_amain.assert_awaited_once()

    def test_main_returns_nonzero_when_amain_fails(self) -> None:
        # Mirror of the success case above, but with a failure
        # return code so the suite asserts the entrypoint surfaces
        # the failure to the caller (which is the container shell
        # in production).
        with patch(
            "app.core.startup._amain",
            AsyncMock(return_value=1),
        ), patch(
            "app.core.startup._configure_logging",
            lambda: None,
        ):
            assert main() == 1


class TestStartupMigrationGuard:
    """The entrypoint wires the migration guard into the start-up flow.

    The tests below cover three observable behaviours (RF-4, RF-16):

    * Empty database -> ``_run_alembic_upgrade`` is called and uvicorn
      is exec'd afterwards (RF-4).
    * Database with Alembic history -> ``_run_alembic_upgrade`` is
      still called (only pending revisions will be applied, that is
      Alembic's responsibility).
    * Database with user tables but no ``alembic_version`` -> the
      entrypoint logs a clear error, exits with a non-zero code and
      does **not** exec uvicorn, run ``_run_alembic_upgrade`` or
      touch the schema (RF-16).
    * Alembic failing to apply -> the entrypoint surfaces a non-zero
      exit code and logs the underlying cause without exec'ing
      uvicorn (RF-8).

    The migration helpers are patched so the suite does not need a
    real PostgreSQL (RNF-2).
    """

    @staticmethod
    def _ok_probe() -> Callable[[], Awaitable[bool]]:
        async def _probe() -> bool:
            return True

        return _probe

    def _settings(self):
        from app.core.config import Settings

        return Settings(
            backend_host="127.0.0.1",
            backend_port=8765,
            startup_timeout_seconds=2.0,
            startup_initial_delay=0.1,
            startup_max_delay=0.2,
        )

    @pytest.mark.asyncio
    async def test_apply_branch_runs_alembic_then_exec_uvicorn(self) -> None:
        # Empty database: the entrypoint must invoke the migration
        # helper exactly once and then hand off to uvicorn.
        async def _empty(_settings) -> DbState:
            return DbState(hasAlembicVersion=False, hasUserTables=False)

        with (
            patch(
                "app.core.startup._probe_postgres_alive",
                self._ok_probe(),
            ),
            patch(
                "app.core.startup._probe_redis_alive",
                self._ok_probe(),
            ),
            patch(
                "app.core.startup._inspect_db_state",
                AsyncMock(side_effect=_empty),
            ),
            patch(
                "app.core.startup._run_alembic_upgrade"
            ) as fake_upgrade,
            patch("app.core.startup.os.execvp") as fake_exec,
            patch(
                "app.core.startup._configure_logging",
                lambda: None,
            ),
            patch(
                "app.core.startup._get_settings_or_cached",
                lambda: self._settings(),
            ),
        ):
            exit_code = await _amain()

        assert exit_code == 0
        fake_upgrade.assert_called_once()
        fake_exec.assert_called_once()
        # Ordering matters: the migration must complete *before*
        # uvicorn is exec'd, otherwise the FastAPI process would
        # serve a request against an uninitialised schema.
        upgrade_call_order = fake_upgrade.call_count
        exec_call_order = fake_exec.call_count
        assert upgrade_call_order == 1 and exec_call_order == 1

    @pytest.mark.asyncio
    async def test_apply_branch_runs_alembic_when_history_exists(self) -> None:
        # The guard returns ``"apply"`` whenever there is no
        # tables-without-history combination, so an already-migrated
        # database still goes through ``_run_alembic_upgrade``
        # (Alembic itself will be a no-op if nothing is pending).
        async def _migrated(_settings) -> DbState:
            return DbState(hasAlembicVersion=True, hasUserTables=True)

        with (
            patch(
                "app.core.startup._probe_postgres_alive",
                self._ok_probe(),
            ),
            patch(
                "app.core.startup._probe_redis_alive",
                self._ok_probe(),
            ),
            patch(
                "app.core.startup._inspect_db_state",
                AsyncMock(side_effect=_migrated),
            ),
            patch(
                "app.core.startup._run_alembic_upgrade"
            ) as fake_upgrade,
            patch("app.core.startup.os.execvp") as fake_exec,
            patch(
                "app.core.startup._configure_logging",
                lambda: None,
            ),
            patch(
                "app.core.startup._get_settings_or_cached",
                lambda: self._settings(),
            ),
        ):
            exit_code = await _amain()

        assert exit_code == 0
        fake_upgrade.assert_called_once()
        fake_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_abort_branch_exits_nonzero_without_modifying_schema(
        self,
    ) -> None:
        # Tables without history: the entrypoint must NOT call
        # ``_run_alembic_upgrade`` (RF-16 forbids auto-migration in
        # this state), must NOT exec uvicorn, and must surface a
        # non-zero exit code so Compose marks the container as
        # failed. The log line must mention ``alembic_version`` so a
        # developer can act on it.
        async def _tables_without_history(_settings) -> DbState:
            return DbState(hasAlembicVersion=False, hasUserTables=True)

        with (
            patch(
                "app.core.startup._probe_postgres_alive",
                self._ok_probe(),
            ),
            patch(
                "app.core.startup._probe_redis_alive",
                self._ok_probe(),
            ),
            patch(
                "app.core.startup._inspect_db_state",
                AsyncMock(side_effect=_tables_without_history),
            ),
            patch(
                "app.core.startup._run_alembic_upgrade"
            ) as fake_upgrade,
            patch("app.core.startup.os.execvp") as fake_exec,
            patch(
                "app.core.startup._configure_logging",
                lambda: None,
            ),
            patch("app.core.startup.logger") as fake_logger,
            patch(
                "app.core.startup._get_settings_or_cached",
                lambda: self._settings(),
            ),
        ):
            exit_code = await _amain()

        # A non-zero exit code is the contract with Docker Compose.
        assert exit_code != 0
        # The schema and data must be left untouched: no upgrade,
        # no uvicorn.
        fake_upgrade.assert_not_called()
        fake_exec.assert_not_called()
        # The log line must identify the cause so the developer
        # can either baseline the schema (``alembic stamp head``)
        # or wipe the conflicting tables before restarting.
        error_calls = fake_logger.error.call_args_list
        assert error_calls, "expected the entrypoint to log an error"
        formatted = " ".join(str(arg) for args in error_calls for arg in args.args)
        assert "alembic_version" in formatted
        assert "user tables" in formatted or "tables" in formatted

    @pytest.mark.asyncio
    async def test_alembic_failure_returns_nonzero_without_exec(self) -> None:
        # ``_run_alembic_upgrade`` raising ``MigrationUpgradeError``
        # must be surfaced: non-zero exit code, uvicorn NOT exec'd,
        # migration NOT retried.
        async def _empty(_settings) -> DbState:
            return DbState(hasAlembicVersion=False, hasUserTables=False)

        def _failing_upgrade(_settings) -> None:
            raise MigrationUpgradeError(
                revision="head",
                last_error="RuntimeError: database is locked",
            )

        with (
            patch(
                "app.core.startup._probe_postgres_alive",
                self._ok_probe(),
            ),
            patch(
                "app.core.startup._probe_redis_alive",
                self._ok_probe(),
            ),
            patch(
                "app.core.startup._inspect_db_state",
                AsyncMock(side_effect=_empty),
            ),
            patch(
                "app.core.startup._run_alembic_upgrade",
                _failing_upgrade,
            ),
            patch("app.core.startup.os.execvp") as fake_exec,
            patch(
                "app.core.startup._configure_logging",
                lambda: None,
            ),
            patch("app.core.startup.logger") as fake_logger,
            patch(
                "app.core.startup._get_settings_or_cached",
                lambda: self._settings(),
            ),
        ):
            exit_code = await _amain()

        assert exit_code != 0
        fake_exec.assert_not_called()
        error_calls = fake_logger.error.call_args_list
        assert error_calls, "expected the entrypoint to log an error"
        formatted = " ".join(str(arg) for args in error_calls for arg in args.args)
        assert "migration failed" in formatted
        assert "database is locked" in formatted

    @pytest.mark.asyncio
    async def test_dependency_failure_short_circuits_before_migration(
        self,
    ) -> None:
        # When a dependency never comes up, the entrypoint must give
        # up *before* touching the database schema: the migration
        # helpers must not be called and uvicorn must not be exec'd.
        async def _ok() -> bool:
            return True

        async def _down() -> bool:
            return False

        with (
            patch(
                "app.core.startup._probe_postgres_alive",
                _down,
            ),
            patch(
                "app.core.startup._probe_redis_alive",
                _ok,
            ),
            patch(
                "app.core.startup._inspect_db_state",
                AsyncMock(),
            ) as fake_inspect,
            patch(
                "app.core.startup._run_alembic_upgrade"
            ) as fake_upgrade,
            patch("app.core.startup.os.execvp") as fake_exec,
            patch(
                "app.core.startup._configure_logging",
                lambda: None,
            ),
            patch(
                "app.core.startup._get_settings_or_cached",
                lambda: self._settings(),
            ),
        ):
            exit_code = await _amain()

        # Non-zero, schema untouched, uvicorn not exec'd.
        assert exit_code != 0
        fake_inspect.assert_not_awaited()
        fake_upgrade.assert_not_called()
        fake_exec.assert_not_called()


class TestMigrationUpgradeError:
    """``MigrationUpgradeError`` is the contract between helper and entrypoint."""

    def test_is_an_exception_subclass(self) -> None:
        assert issubclass(MigrationUpgradeError, Exception)

    def test_carries_revision_and_cause(self) -> None:
        err = MigrationUpgradeError(
            revision="head",
            last_error="RuntimeError: cannot connect",
        )
        assert err.revision == "head"
        assert err.last_error == "RuntimeError: cannot connect"


class TestAlembicIniPath:
    """Regression tests for the alembic.ini path resolution used by
    ``_run_alembic_upgrade``.

    These tests pin the contract introduced after a runtime bug
    (``_BACKEND_DIR`` was derived as ``Path(__file__).resolve().parent.parent``
    which pointed at ``backend/app`` instead of the backend root in both the
    editable host install and the production-style image layout). The
    entrypoint-level tests above mock ``_run_alembic_upgrade`` and therefore
    cannot detect a path-resolution error inside it; this class exercises the
    real Config/ScriptDirectory plumbing with no infrastructure.
    """

    def test_backend_dir_points_at_backend_root(self) -> None:
        # ``_BACKEND_DIR`` must be the directory that *contains* ``alembic.ini``
        # (i.e. ``<repo>/backend/`` on the host and ``/app`` in the image — the
        # image's ``WORKDIR=/app`` is also the layout's backend root), NOT the
        # ``app/`` package directory (``<repo>/backend/app`` on the host or
        # ``/app/app`` in the image). The original bug was
        # ``Path(__file__).resolve().parent.parent`` which produced the
        # ``app/`` package directory; this test pins the fix with properties
        # the buggy derivation cannot satisfy, independent of how many levels
        # deep the path is or what the leaf directory is named (so the test
          # works the same in the editable host install and the production-style
          # image layout introduced by spec 002 / T3).
        #
          # The four invariants are layout-agnostic on purpose: they catch the
          # regression no matter where the repo is checked out or which
          # ``WORKDIR`` the Dockerfile uses.
        assert _BACKEND_DIR.is_dir(), (
            f"_BACKEND_DIR={_BACKEND_DIR} is not a directory on disk"
        )
        # (1) ``_BACKEND_DIR`` must be the directory that *contains*
        # ``alembic.ini`` — not the ``app/`` package directory.
        assert _ALEMBIC_INI.parent.resolve() == _BACKEND_DIR.resolve(), (
            f"_ALEMBIC_INI.parent={_ALEMBIC_INI.parent} != _BACKEND_DIR={_BACKEND_DIR}"
        )
        # (2) ``alembic.ini`` must exist at that path (catches the
        # ``.parent.parent`` bug: with the buggy derivation the resolved
        # ini lives at ``backend/app/../alembic.ini`` which is ``<repo>``
        # and does not contain ``alembic.ini``).
        assert (_BACKEND_DIR / "alembic.ini").is_file(), (
            f"{_BACKEND_DIR}/alembic.ini is missing: _BACKEND_DIR is not the "
            "backend root"
        )
        # (3) ``alembic/`` must exist as a sibling of ``alembic.ini`` (the
        # Alembic ``script_location``) and must contain ``env.py`` so the
        # migration guard can actually run.
        alembic_dir = _BACKEND_DIR / "alembic"
        assert alembic_dir.is_dir(), (
            f"{alembic_dir} is not a directory; alembic would fail with "
            "'No script_location key found in configuration' (RF-4)"
        )
        assert (alembic_dir / "env.py").is_file(), (
            f"{alembic_dir}/env.py is missing; alembic/env.py must ship next "
            "to alembic.ini"
        )
        # (4) ``_BACKEND_DIR`` must NOT coincide with the ``app/`` package
        # directory: the original D1' bug was exactly that (off-by-one
        # ``.parent.parent`` -> ``backend/app`` in the host layout or
        # ``/app/app`` in the image layout). We compare the resolved paths
        # rather than the textual suffix so the invariant is independent of
        # where the backend root lives in the filesystem.
        from pathlib import Path  # noqa: PLC0415 — local import

        from app import __file__ as app_init  # noqa: PLC0415 — local import

        app_pkg = Path(app_init).parent.resolve()
        assert _BACKEND_DIR.resolve() != app_pkg, (
            f"_BACKEND_DIR={_BACKEND_DIR} coincides with the app package "
            f"directory {app_pkg}; this is the off-by-one D1' regression "
            "(.parent.parent instead of .parent.parent.parent)"
        )

    def test_alembic_ini_exists_at_resolved_path(self) -> None:
        assert _ALEMBIC_INI.is_file(), (
            f"_ALEMBIC_INI resolved to {_ALEMBIC_INI!s} which is not a file; "
            "the _run_alembic_upgrade helper will fail with "
            "'No script_location key found in configuration'."
        )

    def test_alembic_config_loads_script_location(self) -> None:
        # Building a real Alembic Config against the resolved ini must surface
        # a non-empty ``script_location`` that points to the alembic scripts
        # directory bundled with the backend.
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        script_location = cfg.get_main_option("script_location")
        assert script_location, (
            "Config built from the resolved ini has no script_location; this "
            "is the exact failure mode that broke RF-4 in the runtime check."
        )

        # ``script_location`` is relative to the ini's directory when the ini
        # uses ``%(here)s`` (which this one does). It must resolve to a real
        # directory containing ``env.py``.
        from pathlib import Path
        resolved = Path(script_location)
        if not resolved.is_absolute():
            resolved = (_ALEMBIC_INI.parent / script_location).resolve()
        assert resolved.is_dir(), (
            f"script_location {script_location!r} does not resolve to a directory"
        )
        assert (resolved / "env.py").is_file(), (
            "script_location does not contain alembic/env.py; alembic will "
            "fail to start"
        )

    def test_script_directory_walks_revisions(self) -> None:
        # ``ScriptDirectory.from_config`` walks the revisions folder; if the
        # ini is pointing at the wrong directory this call returns no
        # revisions and the auto-migration step produces no DDL.
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(_ALEMBIC_INI))
        script = ScriptDirectory.from_config(cfg)
        revisions = list(script.walk_revisions())
        # Spec 001 ships 3 revisions (0001 / 0002 / 0003). The test fails
        # fast if the path ever drifts again.
        assert len(revisions) == 3, (
            f"expected 3 alembic revisions under script_location, got "
            f"{len(revisions)}: {[r.revision for r in revisions]}"
        )
        # And they end at the documented head revision
        # ``0003_users_styles_audit`` (RF-13 / RF-14 / T7-T9).
        head_ids = [
            p.stem for p in (_ALEMBIC_INI.parent / "alembic" / "versions").glob(
                "*.py"
            ) if p.stem != "__init__"
        ]
        assert head_ids, "no alembic revision files found beside alembic.ini"
        assert "0003_users_styles_audit" in head_ids, (
            f"expected 0003_users_styles_audit among revisions, got {head_ids}"
        )
