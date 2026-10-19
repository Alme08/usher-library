# Infrastructure Architecture

## 1. Purpose

This document defines the container, network and deployment model of
Usher Library. It is the single source of truth for the runtime
topology used by the development environment and the production
topology that mirrors it. The deployment plan is described here but
not executed: continuous delivery is out of scope for the current
spec and is left for the spec that introduces it (RF-11,
`docs/specs/002-foundation-ci/spec.md`).

Related documents:

- `docs/architecture/overview.md` — high-level architecture.
- `docs/architecture/system.md` — runtime components and
  communication.
- `docs/architecture/security.md` — trust boundaries and controls.
- `docs/architecture/authentication.md` — identity and sessions.
- `docs/decisions/ADR-0004-docker-compose.md` — Docker and Compose
  as runtime.
- `docs/decisions/ADR-0007-github-actions.md` — CI platform.

---

## 2. Container Inventory

The runtime is composed of five services declared in
`infra/docker-compose.yml`. Backend and frontend images are built from
the repository itself; the data services come from public images
pinned by tag. All services run on a single bridge network named
`usher_net`. The compose project name (`name: usher-library`) is
declared in `infra/docker-compose.yml`.

| Service    | Image                                  | Build context          | Restart           | Healthcheck                                                                                |
|------------|----------------------------------------|------------------------|-------------------|--------------------------------------------------------------------------------------------|
| `postgres` | `postgres:16-alpine`                   | upstream image         | `unless-stopped`  | `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB` (5 s / 3 s / 20 retries / 20 s start period) |
| `redis`    | `redis:7-alpine`                       | upstream image         | `unless-stopped`  | `redis-cli -p $REDIS_PORT ping \| grep -q PONG` (5 s / 3 s / 20 retries / 10 s start period) |
| `keycloak` | `quay.io/keycloak/keycloak:24.0`       | upstream image         | `unless-stopped`  | TCP connect to `localhost:8080` via `/dev/tcp` (10 s / 5 s / 30 retries / 60 s start period)|
| `backend`  | built from `backend/Dockerfile`        | `backend/`             | `unless-stopped`  | `curl -fsS http://localhost:$BACKEND_PORT/health` (10 s / 5 s / 10 retries / 30 s start period) |
| `frontend` | built from `frontend/Dockerfile`       | `frontend/`            | `unless-stopped`  | `curl -fsS http://localhost:5173/` (10 s / 5 s / 10 retries / 30 s start period)            |

### 2.1 Backend image

The backend development image is built from `backend/Dockerfile`. The
stack is `python:3.12-slim`; the runtime entrypoint is
`python -m app.core.startup`, which waits for PostgreSQL and Redis
with retries, runs the Alembic guard (RF-4, RF-16) and then
`exec`’s uvicorn against `app.main:app`. The image ships
`ruff` and `pytest` via the `[dev]` extras so the suite runs inside
the container (RNF-2 of the spec 002).

### 2.2 Frontend image

The frontend development image is built from `frontend/Dockerfile`
on `node:24-bookworm-slim`. Dependencies install with
`npm ci` against `package-lock.json` (deterministic build,
plan §2.3). The dev server is Vite; the suite uses `node --test`,
`eslint .` and `tsc -b --noEmit`.

### 2.3 Healthchecks

Each service declares a Compose `healthcheck.test`; the other
services depend on it via `depends_on: condition: service_healthy`.
The Keycloak probe is TCP-only because the `ubi9-micro` base image
of Keycloak 24 does not ship `curl` or `wget` (see ADR-0003 and the
`infra/docker-compose.yml` block).

---

## 3. Networks

A single bridge network `usher_net` is declared in
`infra/docker-compose.yml`:

```text
name: usher_net
driver: bridge
```

All five services attach to `usher_net`. Service-to-service
communication uses the service name as the hostname (e.g. the
backend reaches PostgreSQL at `postgres:5432`). No service exposes
its database/cache port to the host in this configuration
(`docker compose` does not publish 5432 or 6379).

The composite-support authentication and API surface are documented in
`docs/architecture/authentication.md` §4 and
`docs/architecture/system.md` §2.

---

## 4. Volumes

Development volumes declared in `infra/docker-compose.yml`:

| Service    | Volume                  | Mount                            |
|------------|-------------------------|----------------------------------|
| `postgres` | `usher_postgres_data`   | `/var/lib/postgresql/data`       |
| `redis`    | `usher_redis_data`      | `/data`                          |
| `keycloak` | `usher_keycloak_data`   | `/opt/keycloak/data`             |
| `keycloak` | `./infra/keycloak/realm-export.json` (read-only) | `/opt/keycloak/data/import/realm-export.json` |

The PostgreSQL volume is the canonical development data store; the
verification suite does **not** use it. The disposable database that
the `database` section of `scripts/verify.sh` spins up lives on a
separate bridge network (`usher_verify_net`, see §8) and is
destroyed on teardown.

---

## 5. Development Topology

In development the backend and frontend publish direct host ports,
without a reverse proxy. The mapping is environment-driven
(`infra/docker-compose.yml`):

| Service    | Host port (default) | Container port |
|------------|---------------------|----------------|
| `backend`  | `${BACKEND_PORT:-8000}` | `${BACKEND_PORT:-8000}` |
| `frontend` | `${FRONTEND_PORT:-5173}` | `5173`             |

PostgreSQL, Redis and Keycloak are not published: they are reachable
only from inside `usher_net`. A developer can connect to the database
via `docker compose exec postgres psql ...`; the host ports of
5432 and 6379 are intentionally not mapped.

This matches `docs/architecture/overview.md` §16 "Development" and
`README.md` "Quick start" (`docker compose -f infra/docker-compose.yml up`).
Caddy is not in this composition: the production proxy is out of
scope for the development environment.

---

## 6. Production Topology

The production topology mirrors the runtime composition but inserts
Caddy as the only Internet-facing entry point. PostgreSQL and Redis
sit on a private network that is unreachable from the public
Internet; Keycloak is reached only through Caddy as well. The shape
is the one `docs/architecture/overview.md` §16 "Production"
captures.

```text
Internet
    ↓ 1
  Caddy (TLS, reverse proxy, routing)
    │  ├─ /            → Frontend (static bundle)
    │  ├─ /api/*       → FastAPI backend
    │  └─ /auth/*      → FastAPI backend (OIDC callbacks)
    ↓
FastAPI backend
    ├── PostgreSQL   (private network, no public port)
    ├── Redis        (private network, no public port)
    └── Keycloak     (private network, no public port)
```

Concretely:

- **TLS termination** is delegated to Caddy. The backend listens on
  HTTP inside the cluster (`BACKEND_HOST=0.0.0.0`,
  `--proxy-headers` in `backend/app/core/startup.py`) and trusts
  forwarded headers from the proxy.
- **Cookies** (`docs/architecture/authentication.md` §11) are
  `Secure`, `HttpOnly`, `SameSite=Lax`. The proxy is responsible for
  the `Strict-Transport-Security` and other security headers, as
  the security architecture delegates that responsibility to the
  edge.
- **Backend and frontend** receive traffic from the proxy only; no
  public port. The frontend is served as a static bundle produced
  by `npm run build` (`tsc -b && vite build`) from `frontend/`.
- **Database and cache** live behind the proxy on a private network;
  no host port mapping.
- **Identity provider**: Keycloak is reachable from the backend
  inside the cluster; only the backend exchanges OIDC codes with it.
  The browser only ever sees the proxy.

The image set in production is the same five images, with the
backend and frontend images rebuilt from the repository tags that the
release workflow promotes. Version pinning of the public images is
the same as in development.

The Caddy configuration file (administrative router, TLS certificates,
HSTS, `Strict-Transport-Security` and other security headers) is
**not** committed in this phase. Introducing it requires an ADR
(principle 1 of `docs/constitution.md`) because Caddy is a new
infrastructure service not listed in
`docs/architecture/overview.md` §20 "Confirmed technology choices".

---

## 7. Deployment

This section describes how the system would be deployed but does not
execute it. Continuous delivery is explicitly out of scope
(`docs/specs/002-foundation-ci/spec.md` §"Fuera de alcance":
"Publicación de imágenes de contenedor, despliegue continuo (CD) y
aprovisionamiento de un entorno de producción real").

The shape of a deployment is:

1. Build the images from the repository: `backend/Dockerfile` and
   `frontend/Dockerfile`. Promote the images with immutable tags.
2. Provision a host (or cluster) with the topology in §6: a Caddy
   proxy, two application containers, three data containers, and the
   private network between them.
3. Inject configuration via environment variables — never bake
   secrets into the image (constitution principle 5 and
   `docs/architecture/security.md` §2.6).
4. Run the database migration cycle
   (`alembic upgrade head`) before serving traffic. The
   `database` section of `scripts/verify.sh` documents the cycle on
   a disposable database.
5. Bring the proxy up and start serving traffic once the backend's
   `GET /health` returns 200.

Pending decisions that the deployment introducing spec must resolve
(out of scope here):

- Where Caddy is provisioned and how its TLS material is managed
  (Let's Encrypt vs. internal CA).
- Whether the deployment target is a single host or an orchestrated
  cluster (and which orchestrator).
- Image registry, tag policy and promotion strategy.
- Backup and restore procedure for the development data volumes.
- Migration strategy on schema changes (currently documented at
  `docs/architecture/database.md` §26 but not yet executed against
  a production database).
- Operational dashboards and log aggregation.

This document records the intended shape; the deployment spec
records the implementation.

---

## 8. Disposable Stack

`scripts/verify.sh` (sections `database` and `stack`) uses a
disposable stack that lives on a separate bridge network and never
touches the development data volumes. The recipe is the canonical
block from `docs/specs/002-foundation-ci/plan.md` §5:

```text
docker network create usher_verify_net
docker run -d --rm --name usher-verify-db --network usher_verify_net \
  -e POSTGRES_USER=usher -e POSTGRES_PASSWORD=verify -e POSTGRES_DB=usher_verify \
  postgres:16-alpine
docker run -d --rm --name usher-verify-redis --network usher_verify_net \
  redis:7-alpine
docker compose -f infra/docker-compose.yml build backend
docker run --rm --network usher_verify_net \
  -e DATABASE_URL=postgresql+asyncpg://usher:verify@usher-verify-db:5432/usher_verify \
  -e REDIS_URL=redis://usher-verify-redis:6379/0 -e USHER_RUN_INTEGRATION=1 \
  usher-library-backend sh -c "alembic upgrade head && pytest -m integration -q"
```

The disposable database carries ephemeral credentials (`usher` /
`verify`) that are not committed to the repository
(spec §RNF-4 / RF-9). On teardown the script removes the
containers and the network.

---

## 9. Verification Flow

### 9.1 Local command

The local verification entry point is `scripts/verify.sh`, with the
sections registered in `main`:

| Section    | What it does                                                                                                                                                                                                                                                                                                  |
|------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `backend`  | Builds the backend image and runs `ruff check . && pytest -q` against it (RF-2).                                                                                                                                                                                                                              |
| `frontend` | Builds the frontend image and runs `npm run lint && npm run typecheck && node --test && npm run build` against it (RF-2, RF-10).                                                                                                                                                                            |
| `database` | Spins up the disposable stack (§8), runs `alembic upgrade head`, then `alembic downgrade base` and a second `alembic upgrade head`, and finally `pytest -m integration -q` to verify the schema after each `upgrade head` (RF-4, RF-5).                                                                       |
| `stack`    | Runs the full recorrido de arranque (§10) under its own Compose project (`-p usher-verify`) so the recorrido never touches the development stack — `down -v`, `up -d --wait`, `GET /health`, Keycloak realm import, `down -v`, re-arranque, port-conflict test (RF-6, RF-7). The verification project uses ports 18000/15173 and its network/volumes are prefixed `usher-verify_*` so they do not collide with the development stack's `usher_net`/`usher_postgres_data`/etc. |
| `all`      | Runs `backend`, `frontend`, `database` and `stack` in order. The default section and the complete project verification.                                                                                                                                                                                       |

The script's exit code is `0` only if all sections succeeded.

### 9.2 Continuous integration

The continuous integration flow lives in
`.github/workflows/ci.yml` (ADR-0007). Four independent jobs run on
`ubuntu-latest`, each invoking one section of `scripts/verify.sh`
and timing out at the values frozen in
`docs/specs/002-foundation-ci/plan.md` §3:

| Job       | Section     | Timeout (minutes) |
|-----------|-------------|-------------------|
| `backend` | `backend`   | 10                |
| `frontend`| `frontend`  | 10                |
| `database`| `database`  | 15                |
| `stack`   | `stack`     | 20                |

Triggers: `on: push` (all branches) and `on: pull_request`
(RF-1). The only third-party action used is `actions/checkout@v4`:
the suites run inside the repository's own images, not in a
language-specific action runner (plan §2.3).

The CI flow is the same as the local flow (RNF-2): a developer can
reproduce every CI job locally by running
`./scripts/verify.sh <section>`.

### 9.3 Closing the loop

A run in green on the host branch of the remote repository is
required to close spec 002 (criterion 1). That step depends on the
user enabling GitHub Actions and publishing the workflow to
`origin/main`; this phase delivers the workflow, the validation
gate is the user's contribution. T12 of
`docs/specs/002-foundation-ci/tasks.md` records that publication.

---

## 10. Stack Recorrido de Arranque

The `stack` section of `scripts/verify.sh` is the automated version
of the "recorrido de arranque" defined in
`docs/specs/002-foundation-ci/spec.md` §"Definiciones". Unlike the
development compose, the recorrido runs under its **own Compose
project** so it can run in parallel with the development stack and
still leave every development resource intact. The shape:

1. The script prepares a temporary compose at
   `${REPO_ROOT}/.verify-stack/docker-compose.yml` (the path lives
   inside the repo so BuildKit sandboxes can follow the
   `build.context: ../backend` and `../frontend` relatives; the
   directory is gitignored). The temporary file is a copy of
   `infra/docker-compose.yml` with these mutations applied via
   `sed`/`awk` (RNF-2: no Python, no `jq` on the host):

   - the top-level `name: usher-library` line is removed so Compose
     uses the `-p` value as the project name;
   - every indented `name: usher_*` line (network and volume
     aliases) is removed so Compose prefixes the resources with
     `<project>_<key>`;
   - every `container_name:` line is removed so the verification
     containers do not collide with the development stack's
     pinned `usher-redis` / `usher-postgres` names;
   - the host-port mapping for the backend is rewritten from
     `${BACKEND_PORT:-8000}:${BACKEND_PORT:-8000}` to
     `${BACKEND_PORT:-18000}:${BACKEND_PORT:-18000}`;
   - the host-port mapping for the frontend is rewritten from
     `${FRONTEND_PORT:-5173}:5173` to
     `${FRONTEND_PORT:-15173}:5173`;
   - the relative bind mount `./keycloak/realm-export.json` is
     rewritten to the absolute path
     `${REPO_ROOT}/infra/keycloak/realm-export.json`;
   - two extra environment variables are appended to the Keycloak
     `environment:` block: `JGROUPS_CLUSTER_NAME: usher-verify`
     and `KC_CACHE: local`. Without `KC_CACHE=local`, the
     verification Keycloak attempts to form a JGroups /
     Infinispan cluster with the development Keycloak on the
     same host and dies with `Sleep interrupted` while opening a
     JDBC_PING connection against the development H2 listener.

2. `docker compose -p usher-verify -f <temp> build` rebuilds the
   two application images so a stale cache does not mask a broken
   change. Image tags come out as `usher-verify-backend` and
   `usher-verify-frontend`.

3. `docker compose -p usher-verify -f <temp> up -d --wait` brings
   the verification stack up; Compose waits for every service to
   reach `healthy` (the same healthchecks declared in §2).

4. `curl -fsS http://localhost:18000/health` must return 200 with
   `status: ok` and the dependency probes reporting `ok: true` for
   `postgres` and `redis` (the verification backend binds to
   `BACKEND_PORT=18000`, not the development `8000`).

5. The Keycloak logs must show `Realm 'usher-library' imported`
   without `UnrecognizedPropertyException`-style errors (RF-6).

6. `docker compose -p usher-verify -f <temp> down -v` clears the
   verification state. The development stack is untouched.

7. `docker compose -p usher-verify -f <temp> up -d --wait`
   re-arranca desde cero (RF-6 "rearranque desde cero lo
   reproduce"). The five services must again reach `healthy`.

8. The port-conflict test occupies the host port `18000` with a
   long-running container based on the **verification project's
   backend image** (`usher-verify-backend`, the same tag the
   step-2 build produced), mapped to `18000:8000`. The next
   `up` must fail with a message that names the port or the
   `backend` service (RF-6 "un conflicto de puerto provocado
   falla con un mensaje que identifica la causa"). Referencing
   `usher-verify-backend` (not the development tag
   `usher-library-backend`) is what makes the test
   self-contained: a CI runner that only ran the `stack` job
   has built the verification image but not the development
   one, and the test must still observe the port as taken.

When `--wait` does not reach healthy, the script lists the
services whose `Health` is not `healthy` by reading
`docker compose ps --all --format '{{.Service}}\t{{.State}}\t{{.Health}}'`
with a `while read` loop, and cross-checks the result against
`docker compose ps --services` so a service hidden by Compose (e.g.
the victim of a cascade failure) is still named; their
`compose logs --tail=80` are dumped before exiting non-zero (RF-7).

The teardown is enforced by a `trap teardown_disposable EXIT INT
TERM ERR` at the top of `scripts/verify.sh`, with a final
`stack_teardown` that the `stack` section runs defensively. The
teardown only touches resources of the verification project
(`usher-verify_*` on the `usher-verify_usher_net` network plus the
`STACK_PORT_HOLDER` container) and the temporary
`.verify-stack/` directory. The development project's
`usher_net`, `usher_postgres_data`, `usher_redis_data`,
`usher_keycloak_data` and the `usher-*` containers are never read,
modified or removed by the `stack` section. Keycloak's entrypoint
writes the realm bind-mount file as `root`; the script removes
`.verify-stack/` via a one-shot container spawned from the
`usher-verify-backend` image (the verification project's own
backend image, so no foreign image has to be pulled) bound-mounted
over the directory so the developer account does not need
elevated privileges to clean up after a CI run.

---

## 11. Container Restart Policy

All services in `infra/docker-compose.yml` declare
`restart: unless-stopped`. This is the default Compose behaviour for
local development and matches the operation described in
`README.md`: bring the stack up, work with it, and let Compose
restart on crash. In production the restart policy belongs to the
orchestrator (the deployment spec will introduce it) — Compose is
the local tool, not the production runtime.

---

## 12. Related Documents

- `docs/architecture/overview.md` §16 (topologies), §20
  (technology choices).
- `docs/architecture/system.md` §2 (runtime components), §21
  (production topology).
- `docs/architecture/security.md` §2 (principles), §3 (trust
  boundaries).
- `docs/architecture/authentication.md` §4 (OIDC client),
  §11 (cookies), §24 (failure handling).
- `docs/architecture/database.md` §26 (migration strategy).
- `docs/decisions/ADR-0001-postgresql.md`,
  `ADR-0002-redis.md`, `ADR-0003-keycloak.md`,
  `ADR-0004-docker-compose.md`,
  `ADR-0005-fastapi.md`, `ADR-0006-react-typescript-vite.md`,
  `ADR-0007-github-actions.md`,
  `ADR-0008-decisiones-menores.md`.
- `docs/specs/002-foundation-ci/spec.md` RF-1, RF-2, RF-6, RF-7,
  RF-9, RF-11.