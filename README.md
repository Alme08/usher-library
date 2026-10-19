# Usher Library

Collaborative reading platform centered initially on *The Fall of the House of Usher* by Edgar Allan Poe.
The book is the heart of the experience; social interaction lives around the text, not as an independent feed.

This repository hosts the frontend, backend and infrastructure as a single monorepo, managed with Docker Compose for local development.

## Repository structure

```text
backend/                Python + FastAPI application
frontend/               React + TypeScript + Vite application
infra/                  Docker Compose orchestration and local infrastructure
content/                Source book content (seeded by a later spec)
docs/                   Product, architecture, decisions and SDD specs
```

The full architecture and design constraints live under `docs/architecture/` and `docs/constitution.md`.

## Prerequisites

The development environment runs entirely in containers. The host machine only needs a container runtime.

- **Docker Engine** (24.x or newer recommended)
- **Docker Compose v2** (bundled with recent Docker Engine)

No Python, PostgreSQL, Redis, Keycloak or Node.js runtime is required on the host: everything runs inside the containers started by Compose.

> On Linux, make sure your user can talk to the Docker daemon (member of the `docker` group, or rootless setup).

## Quick start

From a freshly cloned repository:

1. Copy the example environment file (the defaults already work for local development):
   ```bash
   cp .env.example .env
   ```
2. Bring the full environment up with a single command:
   ```bash
   docker compose -f infra/docker-compose.yml up
   ```

On first run Compose will:

- Build the backend and frontend development images.
- Start PostgreSQL, Redis and Keycloak on the internal network.
- Apply pending database migrations automatically on the backend startup.
- Serve the provisional frontend page and expose the backend `/health` endpoint on direct host ports.

Stop the environment with `Ctrl+C`, or in another terminal:

```bash
docker compose -f infra/docker-compose.yml down
```

## Useful commands

All commands below assume `docker compose -f infra/docker-compose.yml` as the base; they are listed here as a reference and will be expanded in later specs.

```bash
# Run backend tests (pytest, inside the backend container)
docker compose -f infra/docker-compose.yml exec backend pytest

# Run frontend tests (node --test, inside the frontend container)
docker compose -f infra/docker-compose.yml exec frontend npm test

# Manual migration cycle (apply / revert / re-apply)
docker compose -f infra/docker-compose.yml exec backend alembic upgrade head
docker compose -f infra/docker-compose.yml exec backend alembic downgrade base
docker compose -f infra/docker-compose.yml exec backend alembic upgrade head
```

## Local verification

The single command that runs the same verification locally as in
the remote CI (RF-9) is:

```bash
./scripts/verify.sh [backend|frontend|database|stack|all]
```

- `backend` — `ruff check . && pytest -q` inside the backend image.
- `frontend` — `npm run lint && npm run typecheck && node --test && npm run build`
  inside the frontend image.
- `database` — disposable PostgreSQL + Redis on a dedicated network,
  with the migration cycle (`alembic upgrade head` →
  `alembic downgrade base` → `alembic upgrade head`) and the
  integration battery after each `upgrade head`.
- `stack` — full recorrido de arranque under its own Compose project
  (`-p usher-verify`), so the recorrido never touches the
  development stack. The verification project uses ports 18000 and
  15173 instead of the dev ports 8000 and 5173, and its network
  and volumes are prefixed `usher-verify_*` (the temporary
  compose file generated inside the script strips the fixed
  `name:` lines from `infra/docker-compose.yml`). The teardown
  inside the script removes only the verification project's
  resources.
- `all` (default) — runs `backend`, `frontend`, `database` and `stack`
  in order. This is the complete project verification: the same
  four jobs the remote CI runs locally in one command.

The script's only resources are the verification project's own.
Concretely:

- the `database` section creates `usher-verify-db` and
  `usher-verify-redis` on the disposable network
  `usher_verify_net`; the script removes them on exit.
- the `stack` section brings up the verification project
  (`usher-verify_*`) on the host ports 18000 and 15173; the
  script removes the project, its network and its volumes on
  exit.

The development project (`usher-library` / `usher_net` /
`usher_postgres_data` / `usher_redis_data` / `usher_keycloak_data`)
is never read, modified or removed by `./scripts/verify.sh`. The
recorrido de arranque can therefore run with the development stack
already up — the verification stack stays strictly inside its own
namespace.

## Configuration

Local configuration is loaded from a `.env` file at the repository root, which is **not** committed (see `.gitignore`). The committed `.env.example` ships only non-sensitive development placeholders; never put real secrets in it.

For the full configuration surface, see `docs/architecture/` and the active spec under `docs/specs/`.

## Documentation

- `AGENTS.md` — operating manual for agents and contributors.
- `MEMORY.md` — short-lived project memory between sessions.
- `docs/constitution.md` — non-negotiable principles.
- `docs/architecture/` — architecture overview, system, database, authentication, security, infrastructure.
- `docs/decisions/` — Architecture Decision Records (ADRs).
- `docs/specs/` — Spec-Driven Development specs, plans and tasks.