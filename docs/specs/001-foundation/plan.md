# Plan — Spec 001: Foundation, entorno de desarrollo ejecutable

Plan de implementación de `docs/specs/001-foundation/spec.md` (aprobada). Aquí SÍ se fijan stack, archivos y comandos: la spec define el QUÉ; este plan define el CÓMO dentro de la arquitectura ya aprobada.

## 1. Archivos y responsabilidades

```text
.gitignore                          # exclusiones: .env, node_modules, __pycache__, dist, artefactos (RF-2, RF-17)
.env.example                        # valores de ejemplo NO sensibles para desarrollo (RF-17)
README.md                           # documentación de arranque: prerrequisitos + comando único (RF-12)

backend/
  pyproject.toml                    # deps (fastapi, uvicorn, alembic, sqlalchemy, asyncpg, redis, pytest, ruff) y config de tooling
  Dockerfile                        # imagen de desarrollo del backend
  alembic.ini
  alembic/env.py                    # wiring de Alembic con la URL de entorno
  alembic/versions/0001_initial_schema.py   # esquema inicial completo (RF-14)
  app/
    main.py                         # app factory FastAPI; monta el router de salud
    api/health.py                   # GET /health: sondas + respuesta de readiness (RF-9)
    core/config.py                  # settings leídos de variables de entorno (sin secretos en código)
    core/startup.py                 # espera de dependencias + guarda RF-16 + auto-migración (RF-4, RF-7, RF-16)
    domain/readiness.py             # función pura de agregación de readiness (RF-9)
    domain/migration_guard.py       # función pura de decisión ante el estado de la BD (RF-16)
    infrastructure/probes.py        # sondas async de conectividad a PostgreSQL y Redis (solo RF-9)
  tests/
    test_readiness.py               # pytest: dominio readiness (sin servicios)
    test_migration_guard.py         # pytest: guarda RF-16 (sin servicios)
    test_health_api.py              # pytest: endpoint /health con sondas falsas (sin servicios)

frontend/
  package.json, tsconfig.json, vite.config.ts, eslint.config.js
  Dockerfile                        # imagen de desarrollo del frontend
  index.html
  src/main.tsx
  src/App.tsx                       # página provisional, copy en inglés (RF-10, RNF-4)
  src/appInfo.ts                    # constantes de copy de la página provisional
  src/appInfo.test.ts               # node --test (RNF-5)

infra/
  docker-compose.yml                # orquestación del entorno completo (RF-3, RF-5, RF-7, RF-11)
  keycloak/realm-export.json        # realm de desarrollo importado al arrancar Keycloak (RF-3, RF-6)
```

Responsabilidades por capa: `domain/` no importa nada de FastAPI/SQLAlchemy/Redis (P3 de la constitución); `api/` solo HTTP; `infrastructure/` solo integraciones; `core/` configuración y arranque. El frontend no contiene lógica de dominio en esta fase.

## 2. Funciones puras

Ninguna lógica de esta fase depende de fechas, por lo que no hay funciones con "hoy" como parámetro.

- `aggregateReadiness(checks: list[CheckResult]) -> ReadinessReport` — `backend/app/domain/readiness.py`. Entrada: resultados de sondas `(name, ok, detail?)`. Salida: `{ready: bool, checks: [...]}` donde `ready = all(ok)`. Pura y testeable sin framework (RF-9, RNF-2).
- `decideMigrationAction(dbState: DbState) -> Literal["apply", "skip", "abort"]` — `backend/app/domain/migration_guard.py`. `DbState = {hasAlembicVersion: bool, hasUserTables: bool}`. Reglas (RF-16):
  - BD vacía (`hasUserTables=False`) → `"apply"`.
  - Con historial (`hasAlembicVersion=True`) → `"apply"` (solo pendientes).
  - Con tablas y sin historial (`True, False`… es decir `hasUserTables=True and hasAlembicVersion=False`) → `"abort"`.
- `appInfo` (constante) — `frontend/src/appInfo.ts`. Copy visible de la página provisional (`name`, `tagline`), en inglés (RF-10, RNF-4).

## 3. Algoritmo (arranque del backend)

```text
startup (backend entrypoint):
  settings = cargar configuración de entorno
  esperar postgres con reintentos (backoff, máx. N; timeout total fijo)
      si agota reintentos: log "dependency unavailable: postgres" y salir con código != 0   (RF-7)
  esperar redis igual
  dbState = inspeccionar BD (¿existe alembic_version? ¿existen tablas de usuario?)
  acción = decideMigrationAction(dbState)                                                   (RF-16)
  si acción == "abort":
      log "database has tables but no migration history; refusing to migrate" y salir != 0
  si acción == "apply":
      alembic upgrade head                                                                  (RF-4)
  iniciar uvicorn

GET /health:
  checks = sondear(postgres, redis) con timeout corto
  report = aggregateReadiness(checks)
  si report.ready: 200 {status: "ok", checks}
  si no:           503 {status: "degraded", checks}                                          (RF-9)
```

El orden de arranque global lo garantiza Compose con `depends_on: condition: service_healthy` sobre los healthchecks de PostgreSQL y Redis; la espera con reintentos del entrypoint es la segunda red de seguridad (RF-7).

## 4. Interfaz

**Endpoints**
- `GET /health` → `200 {"status":"ok","checks":[{"name":"postgres","ok":true},{"name":"redis","ok":true}]}` o `503 {"status":"degraded","checks":[...]}` (RF-9).

**Comandos** (documentados en `README.md`, RF-12)
- `docker compose -f infra/docker-compose.yml up` — comando único de arranque (RNF-1). Levanta frontend (puerto directo, p. ej. 5173), backend (p. ej. 8000), PostgreSQL, Redis y Keycloak (RF-3, RF-5).
- `docker compose -f infra/docker-compose.yml exec backend alembic upgrade head` / `downgrade base` — ciclo manual de migraciones (RF-13, criterio 4).
- `docker compose -f infra/docker-compose.yml exec backend pytest` y `... exec frontend npm test` — runners por stack (RNF-2, RNF-5).

## 5. Decisiones (con alternativa descartada)

1. **Migraciones: Alembic.** La fija `docs/architecture/database.md` §26. *Descartada: SQL plano versionado a mano — sin downgrade ordenado ni historia, violaría RF-13.*
2. **Runner backend: pytest.** *Descartado: unittest — peor ergonomía con async y fixtures del ecosistema FastAPI.*
3. **Runner frontend: `node --test` (nativo).** *Descartado: Vitest — dependencia adicional que exigiría ADR propio (P1); el runner nativo cubre los tests actuales sin añadir nada.*
4. **Orquestación: Docker Compose.** La fija la arquitectura. *Descartado: devcontainers — no sustituye la topología multi-servicio de la arquitectura y añade una capa innecesaria.*
5. **Readiness doble: healthchecks de Compose (para `depends_on`) + `GET /health` agregado (para el desarrollador, RF-9).** *Descartado: solo HEALTHCHECK de Docker — no expone una señal agregada consultable ni identifica qué servicio falla desde fuera.*
6. **Auto-migración en el entrypoint del backend (`alembic upgrade head` antes de uvicorn).** *Descartado: servicio one-shot `migrate` en Compose — una pieza más de orquestación sin beneficio en desarrollo; el entrypoint lo hace atómico con el arranque y concentra la guarda RF-16.*
7. **Keycloak de desarrollo: realm preconfigurado importado al arranque (`realm-export.json`).** *Descartado: configuración manual vía consola de administración — rompe la reproducibilidad (RF-3, RF-6).*
8. **Secretos: `.env` local no versionado + `.env.example`; Compose los inyecta como variables de entorno.** *Descartado: Docker secrets — pensado para Swarm; complejidad injustificada en desarrollo.*
9. **Lint backend: ruff.** *Descartado: flake8+isort+otros — varias dependencias para lo que ruff cubre solo (P1: menos dependencias, menos ADRs).*

## 6. Estrategia de tests

**Backend — `pytest`** (RNF-5), ejecutable sin servicios (RNF-2):
- `test_readiness.py`: `aggregateReadiness` con todas las sondas OK → ready; con una caída → not ready y la sonda identificada. Cubre RF-9 (lógica) y RNF-2.
- `test_migration_guard.py`: `decideMigrationAction` para los tres estados de BD (vacía → apply; con historial → apply; tablas sin historial → abort). Cubre RF-16.
- `test_health_api.py`: `GET /health` con sondas falsas inyectadas (dependency override): 200 cuando todo OK, 503 con la sonda caída identificada. Cubre RF-9.

**Frontend — `node --test`** (RNF-5):
- `src/appInfo.test.ts`: el copy de la página provisional existe y está en inglés (constantes no vacías, ASCII printable). Cubre RF-10 y RNF-4.

**Verificación manual de esta fase** (criterios de finalización; su automatización queda en la spec 002):
- Ciclo `alembic upgrade head` → `downgrade base` → `upgrade head` sobre la BD del entorno, comprobando que el esquema final coincide con el Initial Schema (tablas, constraints, índices). Cubre RF-13 y RF-14 (criterio 4).
- Recorrido de arranque: comando único desde clon limpio, rearranque desde cero, y conflicto de puerto provocado. Cubre RF-3, RF-4, RF-5, RF-6, RF-7, RF-8, RF-10, RF-11 (criterios 1-3).

## 7. Trazabilidad RF → partes del plan

| RF | Cubierto por |
|---|---|
| RF-1, RF-2, RF-17 | `.gitignore`, `.env.example`, estructura monorepo (T1) |
| RF-3, RF-5, RF-7, RF-8, RF-11 | `infra/docker-compose.yml`, `realm-export.json`, Dockerfiles (T4, T5, T6) |
| RF-4, RF-16 | `core/startup.py`, `domain/migration_guard.py` (T10) |
| RF-6 | reproducibilidad Compose + realm importado (T5, T6) |
| RF-9 | `domain/readiness.py`, `api/health.py`, `infrastructure/probes.py` (T2, T6) |
| RF-10 | `App.tsx`, `appInfo.ts` (T3) |
| RF-12 | `README.md` (T1) |
| RF-13, RF-14 | `alembic/` y `0001_initial_schema.py` (T7, T8, T9) |
| RF-15 | regla permanente de Alembic; sin verificación en esta fase (ver spec) |
| RNF-1, RNF-2, RNF-3, RNF-4, RNF-5 | comando único (T6), tests sin servicios (T2, T3), cero servicios externos (T5), copy en inglés (T3), runners por stack (T2, T3) |
