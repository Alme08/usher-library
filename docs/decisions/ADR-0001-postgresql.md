# ADR-0001 — PostgreSQL como base de datos del proyecto

- Estado: aceptado (2026-10-15).
- Spec: `docs/specs/002-foundation-ci/spec.md` RF-12; lista cerrada en `docs/specs/002-foundation-ci/plan.md` §4.

## Contexto

La arquitectura establece que PostgreSQL es la única fuente de verdad del
datos de dominio (overview §17: "PostgreSQL is the application data source
of truth"; system §2 / database §2 "PostgreSQL is the source of truth").
El modelo de dominio persiste libros, versiones, capítulos, párrafos,
anotaciones, comentarios, usuarios de aplicación y eventos de auditoría
(`docs/architecture/database.md` §30, "Initial Schema"). El contenido
publicado es inmutable (database §2.5, §7, §9; overview §7), las
integridades críticas se imponen en la base de datos (§2.7) y las
migraciones pasan obligatoriamente por Alembic (database §26,
backend `alembic/`).

El principio 1 de la constitución exige un ADR aprobado por cada
dependencia o servicio mayor, y la base de datos lo es (overview §20:
"Database: PostgreSQL").

## Decisión

Se adopta **PostgreSQL 16 (alpine)** como base de datos del proyecto.

- Imagen de contenedor: `postgres:16-alpine` (`infra/docker-compose.yml`
  servicio `postgres`).
- Cliente del backend: `asyncpg` ≥ 0.29 vía `sqlalchemy[asyncio]` ≥ 2.0
  (`backend/pyproject.toml`).
- Migraciones: Alembic con revisión base `0001_initial_schema`
  (`backend/alembic/versions/0001_initial_schema.py`); el modelo
  inicial documenta 11 tablas (database §30).
- Codificación y locale de inicialización: `UTF-8 / C` (variable de
  Compose `POSTGRES_INITDB_ARGS`, declarada en `infra/docker-compose.yml`).

## Alternativas consideradas

- **MySQL/MariaDB.** Descartada: el modelo requiere CHECK constraints
  expresivos y tipos UUID/`JSONB` ya canónicos en database.md §4–§17;
  PostgreSQL los soporta de forma nativa y consistente, mientras que
  MySQL históricamente ha requerido desviaciones del estándar (sintaxis
  JSON distinta, semánticas de CHECK relajadas en versiones
  soportadas por proveedores gestionados). Mantener un único dialecto
  también reduce la superficie que Alembic necesita cubrir.
- **SQLite.** Descartada por el requisito de servicio de infraestructura
  independiente (constitución principio 1: "Monolito modular (React +
  FastAPI + PostgreSQL); Redis es solo estado derivado"). SQLite no
  puede correr como servicio separado y complicaría el recorrido de
  arranque (`scripts/verify.sh stack`) que requiere 5 contenedores healthy.

## Consecuencias

- Las migraciones son responsabilidad del repositorio
  (`backend/alembic/versions/`); `alembic upgrade head` se ejecuta desde
  el entrypoint (`backend/app/core/startup.py`) y desde la sección
  `database` de `scripts/verify.sh`.
- Las copias de seguridad, los snapshots y la rotación de credenciales
  de la base de datos siguen siendo tareas operativas fuera del scope
  del repositorio; el archivo `infra/docker-compose.yml` declara los
  volúmenes nombrados `usher_postgres_data` (desarrollo) y los
  desechables en red dedicada (`usher_verify_net`) usados por la
  verificación.
- PostgreSQL es **fuente de verdad** (overview §17, database §2.1);
  Redis (ADR-0002) nunca es autoridad y debe ser reconstruible desde
  esta base de datos.
- El principio 1 de la constitución queda respetado: el ADR precede a
  la presencia del servicio en el repositorio (la spec 001 lo introdujo
  antes de que existiera `docs/decisions/`; este ADR cierra esa deuda de
  trazabilidad).