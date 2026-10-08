"""FastAPI application factory.

The factory pattern lets tests instantiate an isolated application
with dependency overrides (see `tests/test_health_api.py`). Production
entry points call `create_app()` to obtain the configured instance
and `uvicorn` runs it.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.health import router as health_router


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Only the health router is mounted for T2; the rest of the API
    surface lands in later tasks. Keeping the mount explicit here
    means the dependency graph of the application stays auditable.
    """
    application = FastAPI(
        title="Usher Library API",
        version="0.1.0",
        # The health endpoint is the only one shipped in T2; mounting
        # the router keeps `/health` discoverable in the OpenAPI docs.
    )
    application.include_router(health_router)
    return application


# Module-level instance for `uvicorn app.main:app` in production. The
# factory above remains the source of truth; this binding just gives
# the ASGI server a stable import path.
app = create_app()
