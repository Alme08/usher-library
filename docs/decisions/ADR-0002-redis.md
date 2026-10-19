# ADR-0002 — Redis como almacén de estado derivado y temporal

- Estado: aceptado (2026-10-15).
- Spec: `docs/specs/002-foundation-ci/spec.md` RF-12; lista cerrada en `docs/specs/002-foundation-ci/plan.md` §4.

## Contexto

La arquitectura reserva Redis a estado derivado o temporal, nunca a
datos de dominio. La regla es doble:

- Overview §17 ("Source of truth"): cache y pub/sub son Redis;
  identidad, usuario de aplicación, autorización, contenido, anotaciones
  y comentarios son PostgreSQL; "Redis must never be the authoritative
  source for domain data".
- Database §24: "Redis may cache derived or public data such as …
  `Redis may also store: sessions, rate-limit state, future pub/sub data`.
  Any Redis value must be reconstructible or recoverable from
  authoritative data."
- Autenticación §10: "Redis is the preferred session store … Redis
  remains ephemeral; PostgreSQL remains the source of truth for
  user/domain data."

Redis es por tanto un servicio mayor (corre como proceso/contenedor
propio en el entorno, overview §4) y el principio 1 de la constitución
exige ADR aprobado por cada dependencia o servicio mayor.

## Decisión

Se adopta **Redis 7 (alpine)** como almacén de estado derivado y
temporal.

- Imagen de contenedor: `redis:7-alpine`
  (`infra/docker-compose.yml` servicio `redis`).
- Modo de persistencia local: `redis-server --appendonly yes`
  (`infra/docker-compose.yml`), de modo que el ciclo de vida del
  contenedor pueda reconstruirse desde PostgreSQL cuando haga falta.
- Cliente del backend: `redis >= 5.0` (`backend/pyproject.toml`);
  el módulo `app/infrastructure/probes.py` define la sonda
  `check_redis` y la dependencia se inyecta en `GET /health`.
- Volumen de desarrollo: `usher_redis_data` (Compose). Las instancias
  desechables de la verificación viven en la red dedicada
  `usher_verify_net` y nunca tocan ese volumen (`scripts/verify.sh`
  sección `database`).

## Alternativas consideradas

- **Memcached.** Descartada por dos razones: (a) el modelo de sesiones
  con expiración configurable (autenticación §12: idle 30 min,
  absolute 7 d) y la necesidad futura de pub/sub (overview §15, "Real-
  Time") se modelan de forma más limpia en Redis; (b) Memcached no
  ofrece `APPENDONLY` ni estructuras que sobreviven reinicios del
  proceso, mientras que Redis sí — coherente con el requisito "any
  Redis value must be reconstructible or recoverable from
  authoritative data" (database §24).
- **PostgreSQL también para sesiones.** Descartada: usar PostgreSQL
  para sesiones y caché aumenta la carga de la base de datos autoritativa
  con escrituras que no son de dominio, contradice el rol de PostgreSQL
  como fuente de verdad de los datos de dominio y diluye la separación
  que la constitución principio 1 impone entre "PostgreSQL" y "Redis
  solo estado derivado".

## Consecuencias

- Cualquier valor en Redis debe poder reconstruirse desde la base de
  datos (database §24). El backend trata Redis como un caché fallible
  y tolera su caída para rutas públicas (autenticación §24 "Redis
  unavailable: public reading can continue").
- Las sesiones son server-side y el identificador que recibe el
  navegador es opaco (autenticación §10–§11). El backend nunca persiste
  tokens de larga duración en almacenamiento del cliente
  (autenticación §22, constitución principio 5).
- La sonda `check_redis` se verifica en el repositorio contra una
  instancia desechable (`backend/tests/integration/test_probes.py`,
  RF-3(b)) y el recorrido de CI la ejercita
  (`scripts/verify.sh stack`).
- El principio 1 de la constitución queda respetado: Redis es servicio
  mayor, su rol está limitado por ADR y la separación PostgreSQL/Redis
  sigue el principio 5 ("PostgreSQL es la única fuente de verdad").