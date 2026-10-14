Detalles técnicos en docs/learnings.md. Tareas en tasks.md.

## Estado
Spec 001 cerrada con runtime el 2026-10-14 (Docker 29.9.0 + Compose v5.6.0). `up -d --wait` → 5 `healthy`; `GET /health` 200 (`postgres ok`, `redis ok`); auto-migración sobre BD fresca aplica 3 upgrades hasta `0003_users_styles_audit`; reproducible con `down -v && up -d --wait`; Keycloak importa `usher-library` (`usher-library-backend`: `publicClient=false`, `serviceAccountsEnabled=true`, `standardFlowEnabled=true`); PG/Redis/KC internos (RF-11); RF-8: `address already in use`. Fixes D1/D1'/D2': `backend/Dockerfile` copia `alembic.ini`+`alembic/`; `_BACKEND_DIR` → `.parent.parent.parent` en `backend/app/core/startup.py:257` + 4 tests `TestAlembicIniPath`; realm-export sin `verifyEmailListedRealm`, `loginLifecycleBehavior`, `oauth2Device*`, `clientType`, `authenticatorConfig`; description 78 chars (`VARCHAR(255)`). Siguiente: spec 002.

## Decisiones
Constitución docs/constitution.md (6 principios). Frontend `node --test`, ESLint 9. Backend `python -m app.core.startup` (deps + RF-16 + migra + uvicorn). Alembic `target_metadata = None`. `pydantic-settings` (ADR spec 002).

## Reglas
"Tests verdes" ≠ "runtime verificado" para Docker/Compose/migraciones. Tests que mockean la función no detectan bugs en *cómo se llama*; cubrir la frontera con un test determinista sin servicios. JSON/YAML estático no detecta campos eliminados entre versiones de Keycloak; el realm real es la única prueba válida.
