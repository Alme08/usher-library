"""Regression test for the SQLAlchemy ``[asyncio]`` extra declaration.

The Alembic online branch (``alembic upgrade head``) builds an async
engine via ``sqlalchemy.ext.asyncio.async_engine_from_config``, which
since SQLAlchemy 2.1 requires the ``greenlet`` library. Declaring
``sqlalchemy[asyncio]`` in ``pyproject.toml`` is what pulls ``greenlet``
in. Without it, ``alembic upgrade head`` (and therefore the auto-
migration executed by the backend entrypoint, RF-4) crashes with::

    ImportError: The SQLAlchemy asyncio module requires that the
    Python 'greenlet' library is installed.

This module pins the contract at three levels:

1. The dependency manifest **declares** the ``sqlalchemy[asyncio]``
   extra (or an explicit ``greenlet`` dependency), so a developer
   running ``pip install -e .[dev]`` on a clean checkout gets the
   runtime that supports the online Alembic path.
2. The dependency manifest does **not** regress to a bare
   ``sqlalchemy>=2.0`` declaration, which used to ship ``greenlet``
   transitively but no longer does.
3. The online branch of ``alembic/env.py`` imports
   ``sqlalchemy.ext.asyncio`` lazily, so the offline branch (used by
   ``alembic upgrade head --sql`` and the offline tests) does not
   require ``greenlet`` to be installed in test environments that
   only exercise offline mode.

The static checks on the manifest are sufficient for a test that
runs without services (RNF-2): a real ``alembic upgrade head`` needs
a live PostgreSQL, which is exercised in the runtime verification
(checklist item in MEMORY.md), not in this test suite.

Note: the test does NOT call ``import sqlalchemy.ext.asyncio`` directly.
A stale installed copy of SQLAlchemy without ``greenlet`` available
would raise ``ImportError`` at import time and turn the whole test
session red, breaking unrelated tests. The presence/absence of
``greenlet`` in the environment depends on the developer's
``pip install`` history, which is outside the contract this test
guards; the contract is the manifest declaration, which is what the
online path needs to keep working on a fresh install.
"""

from __future__ import annotations

import re
from pathlib import Path

# Repository layout: ``backend/pyproject.toml`` is the manifest we
# are guarding. Resolving it relative to this test file keeps the
# test independent of the caller's working directory.
BACKEND_DIR = Path(__file__).resolve().parent.parent
PYPROJECT_TOML = BACKEND_DIR / "pyproject.toml"


def _read_pyproject() -> str:
    """Return the textual content of ``backend/pyproject.toml``.

    The test inspects the manifest as text rather than going through
    a TOML parser: the contract is a *declaration*, not a parsed AST,
    and a text check is the smallest possible assertion that catches
    a regression without introducing a new dependency on a TOML
    library.
    """
    if not PYPROJECT_TOML.exists():
        raise AssertionError(
            f"pyproject.toml is missing at {PYPROJECT_TOML}; "
            "T2 must create it"
        )
    return PYPROJECT_TOML.read_text(encoding="utf-8")


class TestPyprojectDeclaresSqlalchemyAsyncioExtra:
    """The manifest must declare ``sqlalchemy[asyncio]`` (or an
    explicit ``greenlet`` dependency).

    SQLAlchemy 2.1 stopped shipping ``greenlet`` transitively with the
    bare ``sqlalchemy`` distribution. The online Alembic branch in
    ``alembic/env.py`` uses ``sqlalchemy.ext.asyncio``, which requires
    ``greenlet`` at import time. A developer running ``pip install -e
    .[dev]`` from a clean checkout therefore needs either the
    ``sqlalchemy[asyncio]`` extra or an explicit ``greenlet`` pin to
    make ``alembic upgrade head`` work (RF-4, plan §5.1).
    """

    def test_sqlalchemy_dependency_declares_asyncio_extra(self) -> None:
        """``sqlalchemy[asyncio]`` must appear in ``dependencies``."""
        manifest = _read_pyproject()
        # Look for the literal ``sqlalchemy[asyncio]`` package
        # declaration, allowing any version specifier trailing it.
        # The bracket form is the only one that pulls ``greenlet``
        # in on a fresh install; a bare ``sqlalchemy>=2.0`` does not.
        pattern = r'"sqlalchemy\[asyncio\][^"]*"'
        assert re.search(pattern, manifest), (
            "backend/pyproject.toml must declare 'sqlalchemy[asyncio]' "
            "(or an explicit 'greenlet' dependency) so the Alembic "
            "online branch (RF-4) can import sqlalchemy.ext.asyncio. "
            "The bare 'sqlalchemy>=2.0' pin no longer pulls in "
            "greenlet since SQLAlchemy 2.1."
        )

    def test_no_bare_sqlalchemy_without_asyncio_extra(self) -> None:
        """No bare ``sqlalchemy>=2.0`` regression.

        The pin must use the ``sqlalchemy[asyncio]`` form, not the
        plain ``sqlalchemy>=2.0`` form that silently dropped
        ``greenlet`` from the transitive set in SQLAlchemy 2.1.
        """
        manifest = _read_pyproject()
        # Match a bare ``sqlalchemy`` pin (without the [asyncio]
        # extra) and any version specifier. Allow only entries that
        # already carry the extra.
        bare_pattern = r'"sqlalchemy(?!\[)[^"]*"'
        bare_matches = re.findall(bare_pattern, manifest)
        assert bare_matches == [], (
            f"backend/pyproject.toml still declares a bare SQLAlchemy "
            f"pin without the [asyncio] extra: {bare_matches}. The "
            f"bare pin dropped the 'greenlet' transitive dependency "
            f"in SQLAlchemy 2.1 and breaks the Alembic online branch "
            f"(RF-4). Use 'sqlalchemy[asyncio]>=2.0' instead."
        )

    def test_greenlet_or_asyncio_extra_guarded(self) -> None:
        """At least one of ``sqlalchemy[asyncio]`` or ``greenlet``
        must be declared.

        Either spelling keeps the Alembic online branch working; this
        test allows the explicit ``greenlet`` pin as an alternative
        way to satisfy the contract, in case the team later decides
        to drop the extra in favour of a direct dependency.
        """
        manifest = _read_pyproject()
        has_asyncio_extra = bool(
            re.search(r'"sqlalchemy\[asyncio\][^"]*"', manifest)
        )
        has_greenlet = bool(
            re.search(r'"greenlet[^"]*"', manifest)
        )
        assert has_asyncio_extra or has_greenlet, (
            "backend/pyproject.toml must declare either "
            "'sqlalchemy[asyncio]' or 'greenlet' so the Alembic "
            "online branch (RF-4) can import sqlalchemy.ext.asyncio."
        )


class TestAlembicEnvAsyncioImportIsLazy:
    """``alembic/env.py`` must keep the async import lazy.

    The offline branch (``alembic upgrade head --sql``) and the
    offline test suite must run without requiring ``greenlet`` or
    ``asyncpg`` to be installed. Importing
    ``sqlalchemy.ext.asyncio`` at module top-level would force both
    on every environment that loads ``env.py`` — including the
    ``alembic --sql`` flow that powers the static schema validation
    in this phase (RNF-2, plan §6).
    """

    def test_env_module_defers_async_import_inside_function(self) -> None:
        """The ``sqlalchemy.ext.asyncio`` import must live inside a
        function body, not at module top level."""
        env_path = BACKEND_DIR / "alembic" / "env.py"
        if not env_path.exists():
            raise AssertionError(
                f"alembic/env.py is missing at {env_path}; T7 must create it"
            )
        source = env_path.read_text(encoding="utf-8")

        # The contract is documented in the module docstring: the
        # async SQLAlchemy import must be deferred. We check that
        # the symbol is imported inside the source file at all (it
        # must be: env.py builds an async engine) and that no
        # module-level ``from sqlalchemy.ext.asyncio import`` line
        # exists. The deferred import lives inside
        # ``run_migrations_online_async``.
        assert "sqlalchemy.ext.asyncio" in source, (
            "alembic/env.py must import sqlalchemy.ext.asyncio to "
            "build the async engine for the online branch (RF-4)."
        )
        # The pattern we forbid: a module-level (zero-indent) line
        # importing from sqlalchemy.ext.asyncio.
        module_level_import = re.search(
            r"^from sqlalchemy\.ext\.asyncio import ",
            source,
            flags=re.MULTILINE,
        )
        assert module_level_import is None, (
            "alembic/env.py must defer 'from sqlalchemy.ext.asyncio "
            "import ...' to inside the async online function. A "
            "module-level import forces 'greenlet' on every "
            "environment that loads env.py, breaking the offline "
            "branch and the offline tests (RNF-2)."
        )
