Detalles técnicos en docs/learnings.md. Tareas en tasks.md.

## Estado
Spec 001 cerrada con runtime el 2026-10-14 (commit `ee86a00`). Spec 002 cerrada el 2026-10-18 con CI en verde en los 4 trabajos (`backend`/`frontend`/`database`/`stack`) sobre `origin/main` (commit `f322397`), confirmado por el usuario; URL/id del run no registrados. Siguiente: primera spec de producto (ninguna abierta).

## Verificación
Herramienta única: `./scripts/verify.sh` (`all` = backend+frontend+database+stack). Espejo literal de `.github/workflows/ci.yml` (4 secciones, timeouts 10/10/15/20m). El stack corre aislado en el proyecto Compose `usher-verify` (puertos 18000/15173) y no toca el entorno de desarrollo. AGENTS.md «Verificación» es la definición canónica.

## Decisiones
Constitución docs/constitution.md (6 principios). Runners por stack con timeouts congelados. `pydantic-settings` cerrada con ADR-0008. Alembic `target_metadata = None`. Backend entrypoint `python -m app.core.startup`. Frontend `node --test` + ESLint 9.

## Documentación
`docs/architecture/infrastructure.md` y `docs/decisions/ADR-0001…0008` (PostgreSQL, Redis, Keycloak, Docker Compose, FastAPI, React+TS+Vite, GitHub Actions, decisiones menores).

## Reglas
- "Tests verdes" ≠ "runtime verificado": tareas con Docker/Compose/migraciones no se dan por hechas sin runtime real.
- Cambios de verificación van en `verify.sh`; el YAML solo invoca el script, no duplica pasos.