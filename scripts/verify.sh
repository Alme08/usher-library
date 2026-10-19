#!/usr/bin/env bash
# scripts/verify.sh — single-command local verification (spec 002 / RF-9).
#
# Sections:
#   backend   build the backend image and run ``ruff check . && pytest -q``
#             inside it. The container carries the dev extras (pytest,
#             ruff) so the same command runs locally and in CI (RNF-2).
#             Covers RF-2 backend half + RNF-2.
#   frontend  build the frontend image and run
#             ``npm run lint && npm run typecheck && node --test && npm run build``
#             inside it. ``npm run build`` is part of the suite so the
#             frontend compilation is checked on every run (RF-2 frontend
#             half, RF-10). The container carries the devDependencies so
#             no setup-node is needed in CI (RNF-2).
#             Covers RF-2 frontend half + RNF-2 + RF-10.
#   database  spin up the disposable PostgreSQL + Redis pair on the
#             ``usher_verify_net`` network (plan §5), drive the
#             ``alembic upgrade head`` then ``alembic downgrade base``
#             then ``alembic upgrade head`` cycle on a fresh database
#             and run ``pytest -m integration`` after the first and
#             the last ``upgrade``. The integration battery is the
#             same one T1 introduced; running it after the cycle is
#             what proves that the schema after the round trip still
#             matches the documented model (RF-4, RF-5).
#   stack     recorrido de arranque completo (RF-6, RF-7). Runs the
#             compose project under its own isolated namespace
#             (``-p usher-verify``) on ports distinct from the
#             development stack (``BACKEND_PORT=18000``,
#             ``FRONTEND_PORT=15173``) so a developer with the dev
#             stack running in parallel is not disturbed. A temporary
#             compose file (``${REPO_ROOT}/.verify-stack/docker-compose.yml``)
#             strips the fixed ``name:`` declarations from
#             ``infra/docker-compose.yml`` so the network and the
#             volumes are prefixed with the project (``usher-verify_*``)
#             instead of the global ``usher_net``/``usher_postgres_data``
#             names that the development compose pins. The teardown
#             only touches resources of the verification project.
#   all       run ``backend`` then ``frontend`` then ``database`` then
#             ``stack``. The default section. This is the complete
#             verification of the project (RF-9): ``all`` no longer
#             skips the recorrido de arranque.
#
# Exit codes:
#   0  every section passed
#   !=0  at least one section failed
#
# RNF-2: no extra tooling beyond the container runtime and a shell.
# RNF-4: no secrets baked in — the disposable database credentials
#        (``usher`` / ``verify``) live only inside the disposable
#        containers and are destroyed at teardown.

set -u

# Resolve the directory holding verify.sh so the script works regardless
# of the caller's CWD. ``BASH_SOURCE[0]`` is the path used at invocation;
# ``cd -P`` follows symlinks (developers sometimes symlink the script).
SCRIPT_DIR="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -P -- "${SCRIPT_DIR}/.." && pwd)"

COMPOSE_FILE="${REPO_ROOT}/infra/docker-compose.yml"
DOCKER_NETWORK="usher_verify_net"
VERIFY_DB="usher-verify-db"
VERIFY_REDIS="usher-verify-redis"
DATABASE_URL_VERIFY="postgresql+asyncpg://usher:verify@${VERIFY_DB}:5432/usher_verify"
REDIS_URL_VERIFY="redis://${VERIFY_REDIS}:6379/0"

# Stack section: dedicated compose project so the recorrido never touches
# the development stack's containers, network or volumes. The ``name:``
# lines in ``infra/docker-compose.yml`` are stripped from the temporary
# copy so Compose can prefix the network/volumes with ``usher-verify_``.
#
# The temporary compose file lives under ``${REPO_ROOT}/.verify-stack``
# (not under ``/tmp``) so its ``build.context: ../backend`` and
# ``../frontend`` relative paths still resolve into the repository.
# BuildKit sandboxes refuse to follow symlinks or escape ``/tmp``.
STACK_PROJECT="usher-verify"
STACK_PORT_HOLDER="usher-verify-port-holder"
VERIFY_TMP_DIR="${REPO_ROOT}/.verify-stack"
VERIFY_COMPOSE_FILE="${VERIFY_TMP_DIR}/docker-compose.yml"
# Backend and frontend host ports for the verification project. Distinct
# from the development defaults (``8000`` / ``5173``) so the recorrido
# can run with the dev stack already up.
STACK_BACKEND_PORT="${STACK_BACKEND_PORT:-18000}"
STACK_FRONTEND_PORT="${STACK_FRONTEND_PORT:-15173}"
export BACKEND_PORT="${STACK_BACKEND_PORT}"
export FRONTEND_PORT="${STACK_FRONTEND_PORT}"

# Track overall success so the caller sees the union of every section.
FAIL_COUNT=0
SKIP_TEARDOWN=0

# ---------------------------------------------------------------------------
# Teardown: only the resources that *this* script owns. Keeps this
# function narrow so Ctrl-C, mid-suite crashes and explicit failures
# never leave orphans AND never touch the development project
# (``usher_net``, ``usher_postgres_data``, ``usher_redis_data``,
# ``usher_keycloak_data`` or the ``usher-*`` containers).
# ---------------------------------------------------------------------------
teardown_disposable() {
    if [ "${SKIP_TEARDOWN}" = "1" ]; then
        return
    fi
    # Disposable database containers that the ``database`` section
    # created on the disposable network. ``--force`` and ``|| true``
    # make the teardown idempotent when nothing was ever started.
    docker rm -f "${VERIFY_DB}" "${VERIFY_REDIS}" >/dev/null 2>&1 || true
    docker network rm "${DOCKER_NETWORK}" >/dev/null 2>&1 || true
    # Stack section placeholder (port-conflict test). Project-scoped
    # container, no ``-p`` flag because it sits outside the compose
    # project.
    docker rm -f "${STACK_PORT_HOLDER}" >/dev/null 2>&1 || true
    # Verification compose project: ``down -v`` removes the project
    # containers, network and volumes (``usher-verify_*``) in one
    # call. Guarded by ``|| true`` because the project may not
    # exist yet (no ``stack`` section ran, or the temporary compose
    # file was never written) and ``docker compose`` returns non
    # zero when the project is unknown.
    if [ -f "${VERIFY_COMPOSE_FILE}" ]; then
        docker compose -p "${STACK_PROJECT}" -f "${VERIFY_COMPOSE_FILE}" \
            down -v >/dev/null 2>&1 || true
    fi
    # The stack project's network and volumes live under the
    # ``usher-verify_*`` prefix (the temporary compose file removed
    # the fixed ``name:`` lines from ``infra/docker-compose.yml``).
    # Compose ``down -v`` already removes them; the defensive
    # explicit rm only catches what a crash may have left behind.
    docker network rm "${STACK_PROJECT}_usher_net" \
        >/dev/null 2>&1 || true
    docker volume rm "${STACK_PROJECT}_postgres_data" \
        "${STACK_PROJECT}_redis_data" "${STACK_PROJECT}_keycloak_data" \
        >/dev/null 2>&1 || true
    # Remove the temporary compose directory. Keycloak's
    # entrypoint writes the realm bind-mount file as ``root`` so a
    # plain ``rm -rf`` from the developer account fails (no
    # privilege on the file). Spawning a one-shot root container
    # bound-mounting the directory is the cheapest way to clear
    # the root-owned bind-mount copy without requiring ``sudo``
    # on the host. We use the **verification project's own
    # backend image** (``usher-verify-backend``) as the one-shot
    # root container: it is guaranteed to be present (the
    # ``stack`` section just ran ``docker compose build
    # backend``), it carries GNU coreutils (``/usr/bin/rm`` in
    # the ``python:3.12-slim`` base) and no foreign image has
    # to be pulled. Plan §2.9 asks for "no foreign image
    # download"; reusing the verification image satisfies that
    # without depending on a base image from elsewhere. The
    # ``|| true`` keeps the teardown idempotent if the container
    # fails to start (we would simply leave a root-owned file
    # behind, which is no worse than the previous behaviour
    # and never blocks CI).
    if [ -d "${VERIFY_TMP_DIR}" ]; then
        docker run --rm \
            -v "${VERIFY_TMP_DIR}:/v" \
            --entrypoint sh \
            "${STACK_PROJECT}-backend" \
            -c 'rm -rf /v/*' >/dev/null 2>&1 || true
        # Belt-and-braces: the developer-owned shell can also
        # clean whatever the root container could not.
        chmod -R a+rwX "${VERIFY_TMP_DIR}" 2>/dev/null || true
        rm -rf "${VERIFY_TMP_DIR}" 2>/dev/null || true
    fi
}

# Always teardown on exit (signal-safe). ERR/EXIT/INT/TERM guarantee
# the cleanup runs after a Ctrl-C, after a failed section and on a
# normal exit.
trap teardown_disposable EXIT INT TERM ERR

# ---------------------------------------------------------------------------
# Disposable helpers (only meaningful for the ``database`` section).
# ---------------------------------------------------------------------------
start_disposable() {
    section "Starting disposable PostgreSQL + Redis on ${DOCKER_NETWORK}"
    docker network create "${DOCKER_NETWORK}" >/dev/null 2>&1 || true
    docker run -d --rm --name "${VERIFY_DB}" \
        --network "${DOCKER_NETWORK}" \
        -e POSTGRES_USER=usher \
        -e POSTGRES_PASSWORD=verify \
        -e POSTGRES_DB=usher_verify \
        postgres:16-alpine >/dev/null
    docker run -d --rm --name "${VERIFY_REDIS}" \
        --network "${DOCKER_NETWORK}" \
        redis:7-alpine >/dev/null

    # Wait for PostgreSQL: pg_isready exits 0 only when the server is
    # accepting authenticated connections. 60 s ceiling matches the
    # per-dependency budget in plan §3.
    local waited=0
    while ! docker exec "${VERIFY_DB}" \
            pg_isready -U usher -d usher_verify >/dev/null 2>&1; do
        waited=$((waited + 1))
        if [ "${waited}" -ge 60 ]; then
            echo "ERROR: ${VERIFY_DB} did not become ready within 60s" >&2
            return 1
        fi
        sleep 1
    done
    echo "disposable PostgreSQL ready after ${waited}s"
}

# ---------------------------------------------------------------------------
# Section helpers.
# ---------------------------------------------------------------------------
section() {
    # Print a clear section header so the developer can tell apart the
    # backend/frontend/database blocks while watching the output.
    printf '\n=== %s ===\n' "$1"
}

run_section_backend() {
    section "backend: build image and run lint+tests (RF-2 backend, RNF-2)"
    # Propagate build failures: a cached image can mask a broken
    # ``backend/Dockerfile`` (plan §2.3 "the image cache can be
    # stale") and T3 requires "exit ≠ 0 if any section fails".
    docker compose -f "${COMPOSE_FILE}" build backend || return 1
    # ``docker compose run --rm --no-deps`` is the canonical way to
    # launch the image without its dependency services (postgres,
    # keycloak...). The plain ``docker run`` form rejects ``--no-deps``.
    docker compose -f "${COMPOSE_FILE}" run --rm --no-deps backend \
        sh -c "ruff check . && pytest -q" || return 1
}

run_section_frontend() {
    section "frontend: build image and run lint+typecheck+tests+build (RF-2 frontend, RF-10, RNF-2)"
    docker compose -f "${COMPOSE_FILE}" build frontend || return 1
    # ``npm run build`` is part of the suite so the frontend
    # compilation is checked on every run (plan §3 / §5, RF-10).
    docker compose -f "${COMPOSE_FILE}" run --rm --no-deps frontend \
        sh -c "npm run lint && npm run typecheck && node --test && npm run build" \
        || return 1
}

run_section_database() {
    section "database: disposable stack + migration cycle + integration tests (RF-4, RF-5, RF-9)"
    start_disposable || return 1
    docker compose -f "${COMPOSE_FILE}" build backend || return 1

    # First upgrade: empty DB -> head. Then run the integration battery
    # to confirm the schema matches the documented model (RF-4 first half).
    docker run --rm --network "${DOCKER_NETWORK}" \
        -e DATABASE_URL="${DATABASE_URL_VERIFY}" \
        -e REDIS_URL="${REDIS_URL_VERIFY}" \
        -e USHER_RUN_INTEGRATION=1 \
        usher-library-backend \
        sh -c "alembic upgrade head && pytest -m integration -q" || return 1

    # Downgrade to base then upgrade back to head on the SAME empty DB
    # (RF-4 cycle). The T1 battery is the same one the first upgrade ran
    # against; running it again after the round trip is what closes
    # RF-5: if a constraint or index was lost in the downgrade the
    # last upgrade's test run reports it.
    docker run --rm --network "${DOCKER_NETWORK}" \
        -e DATABASE_URL="${DATABASE_URL_VERIFY}" \
        -e REDIS_URL="${REDIS_URL_VERIFY}" \
        -e USHER_RUN_INTEGRATION=1 \
        usher-library-backend \
        sh -c "alembic downgrade base && alembic upgrade head && pytest -m integration -q" \
        || return 1
}

# ---------------------------------------------------------------------------
# Stack section helpers (RF-6, RF-7).
# ---------------------------------------------------------------------------
#
# The stack section exercises the recorrido de arranque documented in
# plan §5, but under its own compose project (``-p usher-verify``)
# so the recorrido — including the ``down -v`` that RF-6 demands —
# never touches the development stack's containers, network or
# volumes. A developer with the dev stack already up can run
# ``./scripts/verify.sh stack`` (or ``all``) without disturbing it.
#
# Isolation mechanism:
#
# 1. The development compose file (``infra/docker-compose.yml``) pins
#    the project, network and volume names with explicit ``name:``
#    declarations. With those pinned, two compose projects using the
#    same file would still collide on the global ``usher_net``,
#    ``usher_postgres_data``, etc.
# 2. The section builds a temporary copy at
#    ``${REPO_ROOT}/.verify-stack/docker-compose.yml`` that drops every
#    ``name:`` line. Compose then prefixes the network and the
#    volumes with the project name (``usher-verify_usher_net``,
#    ``usher-verify_postgres_data``, …). The verification project is
#    fully independent of the development project.
# 3. Host port mapping is overridden via ``BACKEND_PORT=18000`` and
#    ``FRONTEND_PORT=15173`` (exported at the top of the script) so
#    the verification backend does not collide with the dev backend on
#    ``8000`` either.
#
# Teardown discipline: ``stack_teardown`` (and the script-level
# ``teardown_disposable`` trap) only touch resources that belong to
# the verification project. The development project's ``usher_net``,
# ``usher_postgres_data``, ``usher_redis_data``,
# ``usher_keycloak_data`` and ``usher-*`` containers are never
# removed by this script.

BACKEND_PORT="${STACK_BACKEND_PORT}"

# ``STACK_PROJECT``, ``STACK_PORT_HOLDER``, ``VERIFY_TMP_DIR`` and
# ``VERIFY_COMPOSE_FILE`` are declared at the top of the script
# alongside the disposable-section names. They are the single
# source of truth for the stack section — the only place the
# verification project name, placeholder container, temporary
# directory and prepared compose file are defined.

stack_prepare_compose() {
    # Build the temporary compose file used by every ``stack_compose``
    # invocation. The file lives at
    # ``${REPO_ROOT}/.verify-stack/docker-compose.yml`` and is a copy
    # of ``infra/docker-compose.yml`` with four mutations:
    #
    #   1. Every ``name:`` line (top-level project, network and
    #      volumes) is dropped, so Compose auto-names the network and
    #      the volumes as ``<project>_<key>``. That is what isolates
    #      the verification project from the development project.
    #   2. Every ``container_name:`` line is dropped so the
    #      verification containers do not collide with the
    #      development stack's pinned ``usher-redis`` /
    #      ``usher-postgres`` names.
    #   3. Host port mappings for the backend and frontend are
    #      remapped to the dedicated verification ports (18000 and
    #      15173) so the verification backend does not collide with
    #      the dev backend on 8000.
    #   4. The bind mount for the Keycloak realm export is rewritten
    #      to an absolute path. The development compose uses the
    #      relative ``./keycloak/realm-export.json`` which would
    #      resolve to ``${REPO_ROOT}/.verify-stack/keycloak/...``
    #      and fail. Rewriting to the absolute path keeps the realm
    #      reproducible on every arranque.
    #   5. The verification Keycloak gets a project-scoped JGroups
    #      cluster name so the dev and the verification stacks do
    #      not try to form a single Infinispan cluster when both
    #      are running on the same host.
    if [ -d "${VERIFY_TMP_DIR}" ]; then
        find "${VERIFY_TMP_DIR}" -depth -type f -delete 2>/dev/null || true
        find "${VERIFY_TMP_DIR}" -depth -type d -empty -delete 2>/dev/null || true
    fi
    mkdir -p "${VERIFY_TMP_DIR}"
    # Materialise the temporary compose with sed/awk — no Python
    # dependency (RNF-2: "solo el runtime de contenedores y un
    # script de shell del repositorio"). The substitutions are
    # line-based, which is robust because the development
    # ``infra/docker-compose.yml`` uses a stable indentation. The
    # final two substitutions (JGROUPS_CLUSTER_NAME, KC_CACHE)
    # are anchored to the existing ``KEYCLOAK_REALM:`` line so the
    # block of extra environment variables stays under the
    # ``environment:`` key.
    sed \
        -e '/^name: usher-library[[:space:]]*$/d' \
        -e '/^    name: usher_/d' \
        -e '/^    container_name:[[:space:]]/d' \
        -e 's|"${BACKEND_PORT:-8000}:${BACKEND_PORT:-8000}"|"${BACKEND_PORT:-18000}:${BACKEND_PORT:-18000}"|' \
        -e 's|"${FRONTEND_PORT:-5173}:5173"|"${FRONTEND_PORT:-15173}:5173"|' \
        -e "s|\\./keycloak/realm-export\\.json|${REPO_ROOT}/infra/keycloak/realm-export.json|" \
        "${COMPOSE_FILE}" > "${VERIFY_COMPOSE_FILE}"
    # Append the verification-only env vars to the keycloak
    # ``environment:`` block. Inserting after the
    # ``KEYCLOAK_REALM:`` line keeps the YAML valid (it stays
    # inside the indented environment mapping).
    awk -v project="${STACK_PROJECT}" '
        /^      KEYCLOAK_REALM:[[:space:]]/ {
            print
            print "      JGROUPS_CLUSTER_NAME: " project
            print "      KC_CACHE: local"
            next
        }
        { print }
    ' "${VERIFY_COMPOSE_FILE}" > "${VERIFY_COMPOSE_FILE}.tmp" \
        && mv "${VERIFY_COMPOSE_FILE}.tmp" "${VERIFY_COMPOSE_FILE}"
}

stack_compose() {
    # Thin wrapper: pinned project + dedicated compose file. Every
    # call lands in the ``usher-verify`` namespace so the development
    # ``usher-library`` project is untouched.
    docker compose -p "${STACK_PROJECT}" -f "${VERIFY_COMPOSE_FILE}" "$@"
}

stack_teardown() {
    # Idempotent cleanup: bring the verification project down with
    # ``-v`` so the recorrido reproducibility check starts from a
    # clean slate. ``|| true`` keeps the function safe when the
    # stack was never started or was already torn down by a previous
    # run. The development project (``usher-library``) is never
    # touched by this function.
    stack_compose down -v >/dev/null 2>&1 || true
    docker rm -f "${STACK_PORT_HOLDER}" >/dev/null 2>&1 || true
}

stack_wait_or_dump() {
    # ``up -d --wait`` exits non-zero when any service does not reach
    # the ``healthy`` state within the healthcheck budget (plan §2.7).
    # When that happens, name every non-healthy service and dump its
    # logs so the developer can identify the offender (RF-7). The
    # outer caller decides whether to fail the section; this function
    # returns 0 when every service is healthy and 1 otherwise.
    local up_output
    up_output="$(stack_compose up -d --wait 2>&1)" || {
        echo "${up_output}" | tail -n 20 >&2
        section "stack: services failed to reach healthy (RF-7)"
        # Discover services that did not reach ``healthy``. The Go
        # template format
        # ``{{.Service}}\t{{.State}}\t{{.Health}}`` gives one
        # tab-separated row per service, e.g.
        # ``backend<TAB>running<TAB>healthy``. We use ``--all`` so
        # a service that died (``State=exited``) still appears;
        # the default ``ps`` omits exited containers and the
        # negative contract (RF-7: "name the service that did not
        # reach healthy") would silently miss them.
        #
        # Cross-check against ``ps --services``: in Compose v2
        # ``ps --services`` enumerates every service that currently
        # has a container in the project, so a service whose
        # container was skipped (a victim of a cascade failure,
        # never started) may not appear there even when the
        # cascading cause does. The union of the two lists
        # surfaces every such victim alongside its cause.
        local ps_rows services_list unhealthy=""
        ps_rows="$(stack_compose ps --all --format $'{{.Service}}\\t{{.State}}\\t{{.Health}}' 2>/dev/null || true)"
        services_list="$(stack_compose ps --services 2>/dev/null || true)"
        # Parse rows of "service<TAB>state<TAB>health": only
        # ``State=running`` AND ``Health=healthy`` is acceptable.
        # ``Health`` is the empty string for services that have
        # no healthcheck (Compose leaves it blank); in that case
        # the State alone is the contract (a healthy state, no
        # healthcheck).
        while IFS=$'\t' read -r svc state health; do
            [ -z "${svc}" ] && continue
            if [ "${state}" != "running" ] || [ "${health}" != "healthy" ]; then
                unhealthy="${unhealthy:+${unhealthy}${IFS}}${svc}"
            fi
        done <<EOF
${ps_rows}
EOF
        # Any declared service missing from ps_rows is, by
        # definition, not running and must be surfaced. ``xargs``
        # turns the newline-separated list into positional
        # arguments; ``-n1`` reads them one at a time so a service
        # name that contains spaces would still be handled (the
        # development compose does not use any, but defensive
        # parsing is cheap).
        if [ -n "${services_list}" ]; then
            while IFS= read -r svc; do
                [ -z "${svc}" ] && continue
                case "${ps_rows}" in
                    *"${svc}"*) ;;
                    *) unhealthy="${unhealthy:+${unhealthy}${IFS}}${svc}" ;;
                esac
            done <<EOF
${services_list}
EOF
        fi
        if [ -z "${unhealthy}" ]; then
            echo "ERROR: stack up exited non-zero but every service reports healthy; inspect the output above" >&2
            return 1
        fi
        echo "Non-healthy services:" >&2
        for svc in ${unhealthy}; do
            echo "  - ${svc}" >&2
            echo "--- logs: ${svc} ---" >&2
            stack_compose logs --no-color --tail=80 "${svc}" >&2 || true
        done
        return 1
    }
}

stack_check_health() {
    # ``GET /health`` must return 200 with the dependency probes
    # reporting ``ok=true`` for postgres and redis (RF-6). Targets
    # the verification backend port (``BACKEND_PORT``) which
    # defaults to ``18000`` in this script, distinct from the dev
    # backend's ``8000``.
    local body
    body="$(curl -fsS "http://localhost:${BACKEND_PORT}/health")" || {
        echo "ERROR: GET /health did not respond with 200 on port ${BACKEND_PORT}" >&2
        return 1
    }
    local status
    status="$(printf '%s' "${body}" | sed -n 's/.*"status":[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
    if [ "${status}" != "ok" ]; then
        echo "ERROR: GET /health returned status=${status}; body=${body}" >&2
        return 1
    fi
    # The probes contract (RF-7) is that the JSON lists postgres and
    # redis as ``ok=true``. Pull the per-probe ``ok`` flag with sed
    # one probe at a time — RNF-2 forbids depending on any
    # host-side JSON parser (no ``jq``, no ``python3``).
    local probe_pg probe_redis
    probe_pg="$(printf '%s' "${body}" \
        | sed -n 's/.*"name":[[:space:]]*"postgres"[^}]*"ok":[[:space:]]*\(true\|false\).*/\1/p' \
        | head -n 1)"
    probe_redis="$(printf '%s' "${body}" \
        | sed -n 's/.*"name":[[:space:]]*"redis"[^}]*"ok":[[:space:]]*\(true\|false\).*/\1/p' \
        | head -n 1)"
    if [ "${probe_pg}" != "true" ] || [ "${probe_redis}" != "true" ]; then
        echo "ERROR: health probes not ok (postgres=${probe_pg}, redis=${probe_redis}); body=${body}" >&2
        return 1
    fi
    echo "GET /health: status=ok, probes ok (postgres, redis)"
}

stack_check_realm_import() {
    # The Keycloak log must show the realm being imported without
    # error (RF-6). The check inspects the log for two strings:
    #   1. "Realm 'usher-library' imported" — emitted by the
    #      ``SingleFileImportProvider`` on a clean import.
    #   2. absence of the deserialization / unrecognized-field errors
    #      that broke spec 001 (see learnings.md, Keycloak 24 vs ≥25
    #      field drift: ``UnrecognizedPropertyException`` and friends).
    local logs
    logs="$(stack_compose logs --no-color --tail=200 keycloak 2>&1)" || {
        echo "ERROR: could not read keycloak logs" >&2
        return 1
    }
    if ! printf '%s\n' "${logs}" | grep -q "Realm 'usher-library' imported"; then
        echo "ERROR: Keycloak did not import the realm 'usher-library'" >&2
        printf '%s\n' "${logs}" | tail -n 40 >&2
        return 1
    fi
    if printf '%s\n' "${logs}" | grep -qiE \
        "UnrecognizedPropertyException|InvalidFormatException|failed to import"; then
        echo "ERROR: Keycloak reported an import error in its logs" >&2
        printf '%s\n' "${logs}" | tail -n 40 >&2
        return 1
    fi
    echo "Keycloak realm 'usher-library' imported cleanly"
}

stack_check_port_conflict() {
    # Plan §2.9: occupy the backend's host port (the verification
    # port, ``18000`` by default) with the *same* backend image so
    # the collision exercises the exact host-port mapping the
    # verification compose uses. The placeholder is the backend
    # image with a long ``sleep`` — no extra image download. Compose
    # must refuse to start the backend with a message that names
    # the port or the offending service, and exit non-zero (RF-6).
    section "stack: port conflict test (RF-6 — down -v + up must name the port)"
    stack_teardown
    # Start the backend build so the image is present; ``build`` is
    # fast on a warm cache.
    stack_compose build backend >/dev/null

    # Occupy the host port with a long-running container based on
    # the **same image the verification project uses** — the image
    # tag is ``${STACK_PROJECT}-backend`` (the project-scoped tag
    # ``stack_compose build backend`` produces under
    # ``-p ${STACK_PROJECT}``). Referencing the dev-project tag
    # ``usher-library-backend`` here would fail on a clean runner
    # that only ran this section (no build of the dev project
    # happened), so the test would erroneously observe the port as
    # free. ``--network host`` is not portable; bind-publishing the
    # same host port keeps the test realistic.
    docker run -d --rm --name "${STACK_PORT_HOLDER}" \
        -p "${BACKEND_PORT}:8000" \
        --entrypoint sh \
        "${STACK_PROJECT}-backend" \
        -c 'sleep 600' >/dev/null

    local up_log
    up_log="$(stack_compose up -d --wait 2>&1)" || {
        local rc=$?
        echo "${up_log}" | tail -n 20 >&2
        # Check that the failure names the port or the backend service.
        if printf '%s\n' "${up_log}" | grep -qiE \
            "${BACKEND_PORT}|backend|address already in use"; then
            echo "port conflict correctly named (port=${BACKEND_PORT}, service=backend)" >&2
            stack_teardown
            return 0
        fi
        echo "ERROR: port conflict did not name the port or backend service" >&2
        stack_teardown
        return 1
    }
    # ``up`` succeeded despite the conflict — that means our
    # placeholder did not bind to it (likely because the host port is
    # not yet claimed by anyone). Fail the section so the negative
    # contract is preserved.
    echo "ERROR: stack up unexpectedly succeeded despite the port collision" >&2
    stack_teardown
    return 1
}

run_section_stack() {
    section "stack: recorrido de arranque completo (RF-6, RF-7) en proyecto ${STACK_PROJECT}"

    # Prepare the dedicated compose file (strips ``name:`` lines,
    # remaps ports) and bring any leftover verification resources down.
    stack_prepare_compose
    stack_teardown

    # Rebuild before up (plan §2.3): the image cache can be stale.
    stack_compose build || return 1

    # First arranque: every service must become healthy within the
    # healthcheck budget.
    if ! stack_wait_or_dump; then
        stack_teardown
        return 1
    fi
    if ! stack_check_health; then
        stack_teardown
        return 1
    fi
    if ! stack_check_realm_import; then
        stack_teardown
        return 1
    fi

    # Tear the stack down between the first arranque and the
    # reproducibility check. This is the destructive step the
    # recorrido demands.
    stack_teardown

    # Rearranque desde cero: a second ``up -d --wait`` after the
    # destructive ``down -v`` must reproduce the same five-healthy
    # state (RF-6).
    if ! stack_wait_or_dump; then
        stack_teardown
        return 1
    fi
    if ! stack_check_health; then
        stack_teardown
        return 1
    fi

    # Tear down before the port-conflict test so the host port is
    # available to the colliding container.
    stack_teardown

    # Port-conflict test (plan §2.9). Must end with exit 0 (the
    # negative contract is that the failure is named).
    if ! stack_check_port_conflict; then
        stack_teardown
        return 1
    fi

    # Final teardown so the host is left clean. ``stack_teardown``
    # already ran as part of the port-conflict test, but a final pass
    # guarantees nothing is left behind in case any helper bailed out.
    stack_teardown
}

# ---------------------------------------------------------------------------
# Section dispatch.
# ---------------------------------------------------------------------------
section_backend() {
    if ! run_section_backend; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
        echo "FAIL: backend section failed" >&2
    fi
}

section_frontend() {
    if ! run_section_frontend; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
        echo "FAIL: frontend section failed" >&2
    fi
}

section_database() {
    if ! run_section_database; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
        echo "FAIL: database section failed" >&2
    fi
}

section_all() {
    section_backend
    section_frontend
    section_database
    section_stack
}

# The ``stack`` section runs the recorrido de arranque (RF-6, RF-7)
# under its own compose project so the development stack is never
# touched. The script-level ``trap teardown_disposable`` guarantees
# the verification project's resources are cleaned up on
# EXIT/INT/TERM.
section_stack() {
    if ! run_section_stack; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
        echo "FAIL: stack section failed" >&2
        # Final defensive teardown; ``stack_teardown`` is idempotent.
        stack_teardown
    fi
}

usage() {
    cat <<EOF
Usage: $0 [SECTION]

Sections:
  backend   lint + tests in the backend container (RF-2)
  frontend  lint + typecheck + tests + build in the frontend container (RF-2, RF-10)
  database  disposable stack + migration cycle + integration tests (RF-4, RF-5)
  stack     recorrido de arranque aislado (RF-6, RF-7)
  all       run backend, frontend, database, stack in order (default — full verification, RF-9)
EOF
}

main() {
    local target="${1:-all}"
    case "${target}" in
        backend)  section_backend ;;
        frontend) section_frontend ;;
        database) section_database ;;
        stack)    section_stack ;;
        all)      section_all ;;
        -h|--help|help) usage; exit 0 ;;
        *)
            usage >&2
            echo "ERROR: unknown section '${target}'" >&2
            exit 2
            ;;
    esac

    if [ "${FAIL_COUNT}" -gt 0 ]; then
        echo
        echo "verify.sh: ${FAIL_COUNT} section(s) failed" >&2
        exit 1
    fi
    echo
    echo "verify.sh: all sections passed"
}

main "$@"