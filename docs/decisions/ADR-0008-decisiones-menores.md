# ADR-0008 — Decisiones menores de Foundation (registro agregado)

- Estado: aceptado (2026-10-15).
- Spec: `docs/specs/002-foundation-ci/spec.md` RF-12; lista cerrada en `docs/specs/002-foundation-ci/plan.md` §4.

## Contexto

El principio 1 de la constitución exige un ADR aprobado por cada
dependencia, servicio o herramienta que se incorpore al repositorio.
La spec 002 §"Dependencia, servicio o herramienta mayor" define el
criterio: (a) servicio de infraestructura con proceso o contenedor
propio; (b) framework o runtime que estructura un stack completo
de la arquitectura; (c) la plataforma de integración continua. Todo lo
demás — linters, formateadores, runners de tests del toolchain estándar
del stack, devDependencies y librerías de apoyo de un mayor — es
**menor** y no justifica un ADR individual.

Este ADR es el registro agregado de las decisiones menores
introducidas en la fase Foundation. Cierra explícitamente la deuda
de trazabilidad abierta por `docs/specs/001-foundation/plan.md` §10:
la spec 001 registró provisionalmente la decisión de
`pydantic-settings` y aplazó el ADR formal a la spec 002
("Pendiente de ADR formal en la spec 002 …, esta entrada de plan es
el registro provisional que mantiene la spec 001 trazable"). El
presente ADR cierra esa deuda y registra las demás menores reales
del manifiesto.

## Decisión

Se adoptan, agrupadas por categoría, las siguientes dependencias
menores introducidas en Foundation. Cada elemento contrasta con el
manifiesto del repositorio (`backend/pyproject.toml`,
`frontend/package.json`) y se acompaña de la alternativa razonable
descartada.

### Backend — librerías menores (apoyo de FastAPI / SQLAlchemy)

- **pydantic-settings ≥ 2.2** (`backend/pyproject.toml`). Soporte
  oficial de `BaseSettings` en Pydantic v2; el paquete se independizó
  de `pydantic` en la v2 y la API vive aquí. Cierra el registro
  provisional de `docs/specs/001-foundation/plan.md` §10.
  - Descartado: reimplementar `os.environ` a mano. Viable para los
    pocos settings actuales, pero introduce boilerplate sin valor y
    rompe el principio P2 ("menos dependencias, mejor que eso")
    reimplementando `env_file`/case-insensitive/extras que
    `BaseSettings` ya resuelve.
  - Descartado: `from pydantic import BaseSettings`. La API no existe
    en Pydantic v2 (upstream la movió a `pydantic-settings`); usarla
    requiere el shim deprecado `pydantic[email]`.
- **uvicorn[standard] ≥ 0.27** (`backend/pyproject.toml`). Servidor
  ASGI que arranca la app de FastAPI; el extra `standard` instala
  `uvloop` y `httptools` para el camino caliente del handler HTTP.
  - Descartado: `hypercorn`. Funciona, pero FastAPI documenta
    uvicorn como el camino de referencia y la suite ya asume el
    runner ASGI estándar; añadir un segundo servidor duplica la
    superficie operativa (entrada de `app.core.startup`, healthcheck
    de Compose, scripts de CI).
- **pytest ≥ 8.0** + **pytest-asyncio ≥ 0.23** (dev extras). Runner de
  tests del backend (constitución principio 4) y modo async
  requerido por los endpoints de FastAPI y por `app.infrastructure.*`.
  - Descartado: unittest de la stdlib. No da el modo async nativo ni
    el ecosistema de fixtures que ya usa la suite
    (`backend/tests/test_startup.py`).
- **ruff ≥ 0.4** (dev extra). Linter y formateador del backend.
  - Descartado: flake8 + isort + black por separado. ruff unifica las
    tres responsabilidades (config en `[tool.ruff.lint]` /
    `[tool.ruff.format]`) en una sola dependencia y un solo ejecutable,
    con menos latencia en CI.
- **httpx ≥ 0.27** (dev extra). Cliente HTTP necesario por
  `fastapi.testclient.TestClient` en la suite
  (`backend/tests/test_health_api.py`).
  - Descartado: `requests`. La pila asíncrona del backend prefiere
    httpx para mantener una única familia de cliente HTTP en tests.

### Backend — drivers (clientes de infraestructura)

- **sqlalchemy[asyncio] ≥ 2.0** + **asyncpg ≥ 0.29** +
  **alembic ≥ 1.13**. El plan 001 §1 los declara como grupo
  (driver async, ORM con asyncio, y migrador oficial SQLAlchemy);
  son librerías de apoyo del stack PostgreSQL (mayor, ADR-0001).
  `sqlalchemy[asyncio]` instala `greenlet`, requerido por
  `sqlalchemy.ext.asyncio` desde SQLAlchemy 2.1
  (`backend/pyproject.toml` comentario en la línea 13–18).
  - Descartado: psycopg2. Síncrono, no encaja con el entrypoint async
    de FastAPI y con `app.infrastructure.probes`.
  - Descartado: Alembic comunitario de terceros. No existe; Alembic
    es el migrador oficial de SQLAlchemy y es el que el plan
    documenta (`docs/architecture/database.md` §26).
- **redis ≥ 5.0**. Cliente Python de Redis (mayor, ADR-0002).
  - Descartado: aioredis. El paquete `redis>=5` ya incluye la API
    asíncrona (`redis.asyncio`) usada por `app.infrastructure.probes`,
    así que un cliente adicional sería redundante.

### Frontend — linter, plugins y tipos

- **eslint ^9.0.0** + **@eslint/js ^9.0.0** + **typescript-eslint
  ^8.0.0** + **eslint-plugin-react-hooks ^5.0.0** +
  **eslint-plugin-react-refresh ^0.5.0** (frontend/package.json
  devDependencies). Linter flat-config y plugins oficiales para
  React Hooks y HMR.
  - Descartado: prettier solo. ESLint ya cubre reglas de formato vía
    su propio flat-config en la spec 002; añadir prettier duplicaría
    la responsabilidad sin valor medible.
- **@vitejs/plugin-react ^5.0.0** (frontend/package.json
  devDependencies). Plugin oficial de Vite que aplica el JSX runtime
  de React 19 y conecta el HMR con FastAPI en CI/dev.
  - Descartado: configurar el JSX runtime y el HMR a mano. Posible,
  pero el plugin mantiene los defaults alineados con la versión de
  React declarada en `dependencies`.
- **globals ^16.0.0**. Conjunto de globals del navegador/Node
  reconocido por ESLint.
  - Descartado: declarar las globals a mano en `eslint.config.js`.
  Posible pero propenso a desviaciones al actualizar Node.

### Frontend — typings y soporte de Node

- **@types/node ^24.0.0**, **@types/react ^19.0.0**,
  **@types/react-dom ^19.0.0**. Tipos para Node y React que el
  proyecto usa en su código y en sus tests con `node --test`.
  - Descartado: dejar el código sin typings. Rompería
    `npm run typecheck` (`tsc -b --noEmit`) y el principio 4 de la
    constitución: "lint, comprobación de tipos, tests y compilación en
    el frontend" (RF-2).

### Frontend — runner de tests estándar

- **`node --test`** invocado desde el script `test` del
  `frontend/package.json` (no es un paquete, es el runner nativo de
  Node 24 que ya trae `node:24-bookworm-slim`, ADR-0006). Cumple
  el principio 4 sin agregar dependencia.
  - Descartado: Vitest / Jest. Runner o tools adicionales con ROI
    incierto frente al runner nativo, que ya cubre los tests del
    proyecto.

## Alternativas consideradas

- **Un ADR individual por cada librería menor.** Descartado por
  coste de mantenimiento sin valor: el criterio de "mayor" en la spec
  002 es explícito (no estructura un stack), así que doce ADR
  cortos no aportarían decisión revisable — solo ruido.
- **No registrar las menores.** Descartado porque vulnera el principio
  1 de la constitución ("Toda dependencia o servicio nuevo exige un
  ADR aprobado"): el espíritu del principio es la trazabilidad de la
  pila, y un registro agregado cumple ese espíritu con un coste
  proporcional al valor de cada decisión.
- **Agrupar mayores y menores en los ADRs individuales.**
  Descartado: los ADR-0001…0007 ya nombran las mayores (FastAPI,
  PostgreSQL, Keycloak, etc.) en su contexto; extender cada uno con
  sus devDependencies propias confundiría el "qué decide cada ADR".

## Consecuencias

- Inventario de referencia: cuando se añada una dependencia menor
  nueva, este ADR se actualiza con el mismo formato (categoría,
  versión anclada, alternativa descartada). No requiere un ADR
  propio.
- Criterio "mayor / menor": para una nueva incorporación se aplican
  los tres puntos de la spec 002 (servicio de infraestructura
  propio, framework/runtime que estructura un stack completo, o
  plataforma de CI). Si cumple alguno → ADR individual (siguiente
  número de la serie ADR-0009+). Si no → entrada aquí.
- Cierre del registro provisional de `pydantic-settings`
  (`docs/specs/001-foundation/plan.md` §10): esta ADR-0008 es el
  ADR formal prometido por el plan 001. La deuda queda cerrada y
  cualquier cambio futuro de la dependencia se registra en este
  archivo o en uno nuevo según el criterio mayor/menor.
- El principio 1 de la constitución queda respetado: cada
  dependencia menor introducida en Foundation tiene una entrada con
  alternativa razonable descartada y anclaje al manifiesto.