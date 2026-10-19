# Plan — Spec 002: Foundation, verificación automática y documentación

Plan de `docs/specs/002-foundation-ci/spec.md` (aprobada). La spec fija el QUÉ; aquí se fija el CÓMO.

## 0. Cierre del criterio 1 (dependencia explícita del usuario)

La implementación NO hace push al repositorio del usuario. El criterio 1 se cierra así (tarea T12):
1. El usuario confirma que GitHub Actions está habilitado en el repositorio hospedado y su visibilidad (no auditable desde este entorno).
2. El usuario publica en `origin/main` los commits de esta spec (incluido `.github/workflows/ci.yml`).
3. Se observa una ejecución real del flujo en verde sobre `main`, visible para su autor (RF-8).
Hasta entonces, todo lo remoto queda en verificación estática (T5 se marca `[~]`).

## 1. Archivos y responsabilidades

```text
.github/workflows/ci.yml                 # RF-1, RF-2, RF-7, RF-8: 4 trabajos, timeouts explícitos
scripts/verify.sh                        # RF-9: comando único; secciones all|backend|frontend|database|stack
backend/pyproject.toml                   # marker pytest `integration`
backend/tests/integration/conftest.py    # activación explícita: USHER_RUN_INTEGRATION=1; si no, skip
backend/tests/integration/test_initial_schema.py  # RF-3(a), RF-5: 11 tablas + restricciones + índices
backend/tests/integration/test_probes.py          # RF-3(b): sondas reales a postgres y redis
docs/architecture/infrastructure.md      # RF-11
docs/decisions/ADR-0001-postgresql.md    # RF-12 (lista cerrada en §4)
docs/decisions/ADR-0002-redis.md
docs/decisions/ADR-0003-keycloak.md
docs/decisions/ADR-0004-docker-compose.md
docs/decisions/ADR-0005-fastapi.md
docs/decisions/ADR-0006-react-typescript-vite.md
docs/decisions/ADR-0007-github-actions.md
docs/decisions/ADR-0008-decisiones-menores.md
AGENTS.md                                # RF-10: sección «Verificación» actualizada
README.md                                # RF-9: comando único documentado; sin notas "pending"
```

`scripts/` existe sin trackear y contiene `sdd-status.sh` (ajeno a esta spec): solo se versiona `verify.sh`; no hay colisión de nombre.

## 2. Decisiones (alternativa descartada entre corchetes)

1. **Plataforma: GitHub Actions** — la fija `docs/architecture/overview.md` §20; ADR-0007 la registra. [Reabrirla: decisión arquitectónica ya confirmada.]
2. **Un solo script `scripts/verify.sh` con secciones** (`all` por defecto); `ci.yml` solo hace checkout y llama a la sección. [Pasos duplicados en YAML: divergencia local/IC (HU-7). Make/just: runner nuevo, prohibido por RNF-2.]
3. **Suites dentro de las imágenes del repo**: `docker compose -f infra/docker-compose.yml build <stack>` + `run --rm --no-deps <stack> sh -c "…"` (ambas imágenes ya embarcan el tooling: backend `[dev]` con pytest/ruff; frontend `npm ci` con devDependencies). [setup-python/setup-node en el runner: duplica versiones del toolchain y añade actions de terceros.] `build` siempre antes de `run` (aprendizaje: la imagen cacheada puede quedar stale).
4. **Desechables en red dedicada**: contenedores `docker run --rm` (`usher-verify-db`, `usher-verify-redis`) en `usher_verify_net`, sin puertos publicados; jamás el volumen `usher_postgres_data` (RF-9). [Servicio extra en docker-compose.yml: contaminaría el entorno de desarrollo. `services:` de GitHub Actions: no existe en local, rompe la paridad.]
5. **Integración con activación explícita**: marker `integration` + conftest que salta esos tests salvo `USHER_RUN_INTEGRATION=1`; el `pytest -q` de AGENTS.md sigue verde sin BD. [Auto-skip al no detectar BD: un fallo de red en IC se enmascararía como skip.]
6. **RF-5 reutiliza `test_initial_schema.py`**: tras `upgrade → downgrade base → upgrade` se vuelve a ejecutar la batería de integración contra la misma BD desechable. [Comparador SQL aparte: dos fuentes de verdad del esquema.]
7. **Espera con la señal de Compose**: `up -d --wait` acotado por los healthchecks; al fallar, el script nombra cada servicio no healthy (`compose ps`) y vuelca `docker compose logs <servicio>` (RF-7). [Bucle propio de polling: duplica la señal de los healthchecks.]
8. **Workflow: 4 trabajos** (`backend`, `frontend`, `database`, `stack`), `on: push` (todas las ramas) + `pull_request`; única action externa: `actions/checkout`. [Job único: sin timeouts por bloque ni atribución clara (RF-7). Matrix: trabajos heterogéneos.] Se aceptan ejecuciones duplicadas push+PR: prima la visibilidad.
9. **Conflicto de puerto con la propia imagen del backend** (`python -m http.server` publicando 8000) y aserción de exit ≠ 0 con mensaje que nombra el puerto. [Imagen extra (nginx): una descarga sin valor.]
10. **ADRs: lista cerrada de 8 (§4), plantilla breve propia**: estado, contexto, decisión, alternativas, consecuencias. [MADR completo: sobredimensionado. Un único ADR global: decisión contraria del usuario.] **`pydantic-settings` (registro provisional del plan 001 §10) entra en ADR-0008: deuda de trazabilidad cerrada aquí.**
11. **`infrastructure.md` describe el despliegue sin ejecutarlo** (CD fuera de alcance); coherente con `overview.md` §16.

## 3. Timeouts congelados (RNF-3; literales en ci.yml y verify.sh)

| Trabajo | `timeout-minutes` | Contenido |
|---|---|---|
| backend | 10 | build + ruff + pytest (unit) |
| frontend | 10 | build + lint + typecheck + node --test + npm run build |
| database | 15 | desechables + ciclo de migraciones + integración ×2 |
| stack | 20 | dos arranques completos + comprobaciones + conflicto de puerto |

Acotaciones internas: espera de cada desechable ≤ 60 s; cada `up -d --wait` acotado por los healthchecks de Compose (peor caso ≈ 6 min, Keycloak) y, como cota externa, el `timeout-minutes` del trabajo. Si un servicio no llega a healthy: el trabajo falla nombrándolo y adjuntando sus logs (RF-7).

## 4. Lista cerrada de ADRs (RF-12; congelada, no se reabre)

Mayores (individuales): ADR-0001 PostgreSQL · ADR-0002 Redis · ADR-0003 Keycloak · ADR-0004 Docker/Docker Compose · ADR-0005 FastAPI · ADR-0006 React + TypeScript + Vite · ADR-0007 GitHub Actions (decisión de esta spec).
Agregado (menores): ADR-0008 — ruff, pytest, ESLint + plugins, `node --test`, uvicorn, SQLAlchemy + asyncpg, Alembic, `pydantic-settings` (cierre de la deuda del plan 001 §10).
Caddy no entra: no está introducido en el repositorio (fuera de alcance de la spec).

## 5. Estrategia de tests

Comandos del proyecto (AGENTS.md «Verificación» tras T11):
- Backend: `cd backend && ruff check . && pytest -q` — debe seguir 213 verdes (integración: skip sin la variable).
- Frontend: `cd frontend && npm run lint && npm run typecheck && node --test && npm run build` — se añade `npm run build` (RF-10).
- Compose: `docker compose -f infra/docker-compose.yml up -d --wait`
- Verificación completa (local e IC): `./scripts/verify.sh`

Bloque desechable canónico (lo ejecuta `verify.sh database`; usable a mano):
```bash
docker network create usher_verify_net
docker run -d --rm --name usher-verify-db --network usher_verify_net \
  -e POSTGRES_USER=usher -e POSTGRES_PASSWORD=verify -e POSTGRES_DB=usher_verify postgres:16-alpine
docker run -d --rm --name usher-verify-redis --network usher_verify_net redis:7-alpine
docker compose -f infra/docker-compose.yml build backend
docker run --rm --network usher_verify_net \
  -e DATABASE_URL=postgresql+asyncpg://usher:verify@usher-verify-db:5432/usher_verify \
  -e REDIS_URL=redis://usher-verify-redis:6379/0 -e USHER_RUN_INTEGRATION=1 \
  usher-library-backend sh -c "alembic upgrade head && pytest -m integration -q"
# ciclo (RF-4/RF-5): sh -c "alembic downgrade base && alembic upgrade head && pytest -m integration -q" (mismo env)
# teardown: docker rm -f usher-verify-db usher-verify-redis; docker network rm usher_verify_net
```
Credenciales `verify`/`usher_verify`: efímeras, solo viven en el contenedor desechable (RNF-4: ningún secreto real).

Cobertura:
- `test_initial_schema.py` — 11 tablas del Initial Schema (`database.md` §30) con PKs, FKs, uniques, checks e índices (§14, §16, §21). Rojo provocado: borrar un índice en la desechable → falla. Cubre RF-3(a) y RF-5.
- `test_probes.py` — sondas reales de `app/infrastructure/probes.py` contra los desechables (ok) y contra un puerto sin servicio (fallo que nombra la dependencia). Cubre RF-3(b). Aprendizaje: imports de `asyncpg`/`sqlalchemy.ext.asyncio` dentro de la función, nunca top-level.
- Recorrido (`verify.sh stack`) — build → `up -d --wait` → 5 healthy → `GET /health` 200 con sondas ok → `logs keycloak` confirma importación del realm sin errores → `down -v` → rearranque reproduce → conflicto de puerto provocado falla nombrando la causa. Cubre RF-6, RF-7.
- `ci.yml` — verificación estructural local (greps: triggers, 4 trabajos, `timeout-minutes`, llamadas a `verify.sh`) más `./scripts/verify.sh` como ensayo; la validación real la hace GitHub tras el push del usuario (T12).

## 6. Trazabilidad RF → partes del plan

| RF | Cubierto por |
|---|---|
| RF-1, RF-2, RF-8 | `ci.yml` (T5) + cierre remoto (T12) |
| RF-3 | tests de integración (T1, T2) |
| RF-4, RF-5 | `verify.sh database` (T3) + `test_initial_schema.py` (T1) |
| RF-6, RF-7 | `verify.sh stack` (T4) + timeouts §3 (T5) |
| RF-9, RNF-2 | `scripts/verify.sh` (T3, T4) + README (T11) |
| RF-10 | AGENTS.md (T11) |
| RF-11 | `infrastructure.md` (T10) + README (T11) |
| RF-12 | ADR-0001…0008 (T6–T9) |
| RNF-1, RNF-3, RNF-4 | runners propios por stack en cada imagen (T3); timeouts §3 (T5); cero secretos en workflow/script (T3–T5) |
