"""Application settings loaded from environment variables.

This module is the single place where configuration values enter the
backend. All other modules read settings through `get_settings()` so
they never reach for `os.environ` directly. This keeps secrets out of
source code and makes the configuration surface auditable (RF-17).

Only non-sensitive, environment-driven configuration lives here. Real
secrets remain in the local `.env` file which is git-ignored.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings.

    Defaults are aligned with the development environment documented
    in `.env.example` so the application can be imported even when
    the environment file is missing. Production overrides are expected
    to be supplied through real environment variables.
    """

    # --- PostgreSQL ---
    postgres_host: str = Field(default="postgres")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="usher_library")
    postgres_user: str = Field(default="usher")
    postgres_password: str = Field(default="change_me_in_local_env")

    # --- Redis ---
    redis_host: str = Field(default="redis")
    redis_port: int = Field(default=6379)
    redis_url: str = Field(default="redis://redis:6379/0")

    # --- Backend (FastAPI) ---
    database_url: str = Field(
        default="postgresql+asyncpg://usher:change_me_in_local_env@postgres:5432/usher_library"
    )
    backend_host: str = Field(default="0.0.0.0")
    backend_port: int = Field(default=8000)

    # --- Health probes ---
    # Short timeout for the connectivity probes. The /health endpoint
    # must respond quickly even when a dependency is hanging.
    probe_timeout_seconds: float = Field(default=1.0, ge=0.0)

    # --- Startup dependency wait (RF-7) ---
    # Total time the backend entrypoint will spend waiting for
    # PostgreSQL and Redis to become reachable before giving up and
    # exiting with a non-zero code. Must be large enough to cover the
    # typical Compose cold start of the database and the cache, while
    # still short enough that a developer notices a misconfiguration
    # within a reasonable wait.
    startup_timeout_seconds: float = Field(default=30.0, gt=0.0)
    startup_initial_delay: float = Field(default=0.5, gt=0.0)
    startup_max_delay: float = Field(default=5.0, gt=0.0)
    startup_backoff_factor: float = Field(default=2.0, gt=1.0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide `Settings` instance.

    The result is cached so the environment is parsed exactly once per
    process. Tests can call `get_settings.cache_clear()` to force a
    re-read after monkey-patching environment variables.
    """
    return Settings()
