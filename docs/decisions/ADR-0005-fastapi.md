# ADR-0005 — FastAPI + uvicorn como framework del backend

- Estado: aceptado (2026-10-15).
- Spec: `docs/specs/002-foundation-ci/spec.md` RF-12; lista cerrada en `docs/specs/002-foundation-ci/plan.md` §4.

## Contexto

La arquitectura fija el backend como un monolito modular con cuatro
capas explícitas — API, Aplicación, Dominio, Infraestructura
(`docs/architecture/overview.md` §5, `docs/architecture/system.md` §3) —
y la constitución principio 3 prohíbe que el dominio dependa de
FastAPI, SQLAlchemy, Redis o Keycloak. Esto encaja con un framework que
sea delgado en la capa HTTP y deje la lógica de negocio en el código
del proyecto, no en el framework.

La elección de framework backend es un "framework o runtime que
estructura un stack completo de la arquitectura" (definición de
"dependencia, servicio o herramienta mayor" en la spec 002 §"Defi-
niciones"), figura como "Confirmed technology choice"
(`docs/architecture/overview.md` §20 "Backend: FastAPI") y por tanto
exige ADR por principio 1 de la constitución.

## Decisión

Se adopta **FastAPI + uvicorn[standard]** como framework y servidor
ASGI del backend, con la separación de capas que fija la arquitectura:

- Versiones ancladas al repositorio (`backend/pyproject.toml`):
  `fastapi>=0.110`, `uvicorn[standard]>=0.27`, `pydantic>=2.6`,
  `pydantic-settings>=2.2`. Runtime del contenedor: `python:3.12-slim`
  (`backend/Dockerfile`).
- Capa API en `app/main.py` (router) y `app/api/` (endpoints por
  dominio). Capa de aplicación: casos de uso que orquestan dominio e
  infraestructura (`app.application.*`). Capa de dominio: entidades y
  reglas puras, sin importar FastAPI, SQLAlchemy, Redis ni Keycloak
  (`app.domain.*`). Capa de infraestructura: clientes reales
  (`app.infrastructure.probes`, `app.infrastructure.alembic`).
- Endpoints documentados con OpenAPI que FastAPI genera de los type
  hints, sin librería de serialización acoplada al ORM
  (`docs/architecture/database.md` §27 "API responses must use explicit
  schemas rather than serializing ORM objects blindly").
- Tests con `pytest` + `pytest-asyncio` (dev extra del pyproject) y
  `httpx` para el TestClient. La sonda de `/health` (`check_postgres`,
  `check_redis` en `app/infrastructure/probes.py`) se valida en la
  suite de integración contra instancias desechables
  (`backend/tests/integration/test_probes.py`, RF-3(b)).

## Alternativas consideradas

- **Django + Django REST Framework.** Descartada por dos razones: (a)
  Django arrastra un ORM y un panel admin que duplicarían el contrato de
  la arquitectura — el ORM oficial contradice database §27 ("ORM
  models are persistence models, not automatically domain models or API
  contracts") y la constitución principio 3 (el dominio libre de
  framework); (b) Django REST Framework reifica las vistas en clases
  con demasiada maquinaria (serializers, mixins, view-sets), cuando la
  arquitectura pide una capa API delgada que delegue en la aplicación.
  Además, integrar Django con el patrón de inyección de dependencias
  de FastAPI costaría adaptadores adicionales sin valor.
- **Flask.** Descartada porque Flask 2.x no trae validación de tipos
  ni OpenAPI integrados: añadir pydantic + flask-smorest/flask-pydantic
  reproduce las piezas que FastAPI ya da de fábrica. Mantener una
  dependencia menos y un handler-tipado end-to-end (request y response)
  encaja mejor con el "API responses must use explicit schemas"
  (database §27) que la arquitectura exige.
- **Starlette puro (sin FastAPI).** Descartada porque FastAPI es
  Starlette + pydantic + OpenAPI generados, sin coste operativo
  apreciable, y la convención del repositorio (entrypoint
  `python -m app.core.startup` → `uvicorn app.main:app`) usa explícitamente
  el ASGI tipado. Migrar a Starlette puro sacrificaría el ecosistema
  de tipado y validación que la suite de tests ya da por sentado.

## Consecuencias

- El backend tiene un handler tipado y OpenAPI generado, pero la lógica
  de negocio no depende del framework: los tests de dominio se ejecutan
  sin levantar FastAPI (cumple constitución principio 3 y la
  definición de "testability" en overview §3).
- `uvicorn[standard]` instala el event loop `uvloop` y el cliente
  `httptools`, que el contenedor del backend usa para servir la API
  con el menor overhead posible. El entrypoint
  (`backend/app/core/startup.py`) espera PostgreSQL y Redis con
  reintentos/backoff antes de `exec` uvicorn (RF-7).
- El contrato HTTP/JSON queda anclado en tipos pydantic; los errores
  se serializan con el handler por defecto de FastAPI. Cambios en la
  forma de respuesta rompen el contrato con el frontend, que es lo que
  la spec exige.
- El principio 1 de la constitución queda respetado: FastAPI está
  registrado como framework mayor; no se introduce un segundo framework
  web sin un ADR previo.