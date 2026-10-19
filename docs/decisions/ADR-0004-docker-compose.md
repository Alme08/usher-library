# ADR-0004 — Docker y Docker Compose como runtime del entorno

- Estado: aceptado (2026-10-15).
- Spec: `docs/specs/002-foundation-ci/spec.md` RF-12; lista cerrada en `docs/specs/002-foundation-ci/plan.md` §4.

## Contexto

La constitución principio 1 fija el stack como un monolito modular con
servicios de infraestructura corriendo como procesos propios ("Stack
simple y único"). El entorno de desarrollo debe poder levantarse con
un único comando desde un clon limpio, y la verificación automática
debe ejecutar el stack (no solo inspeccionarlo) — esto es lo que la
spec 002 aprendió del cierre de la spec 001, que pasó tests estáticos
sin detectar tres defectos reales (`docs/specs/002-foundation-ci/spec.md`
"Contexto y objetivo"; `docs/learnings.md` entradas 5, 9, 13–17).

La arquitectura fija el runtime como Docker
(`docs/architecture/overview.md` §20: "Runtime: Docker"; §16
"Infraestructura: Dockerized development and deployment") y
`docs/architecture/system.md` §2 modela los cinco servicios como
nodos independientes. La spec 002 introduce además
`scripts/verify.sh` (RF-9) y `.github/workflows/ci.yml` (RF-1, RF-2,
RF-7) que ejecutan las verificaciones dentro de los contenedores del
repositorio, sin `setup-python`/`setup-node` ajenos
(`docs/specs/002-foundation-ci/plan.md` §2.3 "suites dentro de las
imágenes del repo").

Docker y Docker Compose son por tanto dependencias/herramientas
mayores: estructuran el stack completo y la spec 002 exige ADR por
principio 1 de la constitución.

## Decisión

Se adopta **Docker + Docker Compose** como runtime del entorno, con los
siguientes elementos anclados al repositorio:

- Compose: `infra/docker-compose.yml` declara los cinco servicios del
  stack (`backend`, `frontend`, `postgres`, `redis`, `keycloak`) con
  healthchecks, `depends_on: condition: service_healthy`, red interna
  `usher_net` y volúmenes nombrados `usher_postgres_data`,
  `usher_redis_data`, `usher_keycloak_data` para los datos de
  desarrollo.
- Imágenes de servicio: `postgres:16-alpine`, `redis:7-alpine`,
  `quay.io/keycloak/keycloak:24.0`. Imágenes de aplicación:
  construidas desde `backend/Dockerfile` (`python:3.12-slim`) y
  `frontend/Dockerfile` (`node:24-bookworm-slim`).
- Comando único de arranque: `docker compose -f infra/docker-compose.yml
  up -d --wait` (especificación §2.7, README del recorrido). El flag
  `--wait` delega en los healthchecks de cada servicio la espera al
  estado healthy, acotando cada arranque sin polling casero
  (plan §2.7).
- Verificación: `scripts/verify.sh` ejecuta las suites dentro de las
  imágenes del repo (plan §2.3). El runner de CI
  (`.github/workflows/ci.yml`) solo invoca `./scripts/verify.sh <sección>`
  y la imagen cacheada se reconstruye antes de cada `run` para evitar
  stale (plan §2.3, `docs/learnings.md` entrada 17).

## Alternativas consideradas

- **Servicios nativos en la máquina anfitriona (sin contenedor).**
  Descartada por la razón que la spec 001 documentó como defecto
  estructural (spec 002 §0 "Contexto y objetivo"): sin un runtime
  aislado, la verificación deja de ejecutar el sistema y solo lo
  inspecciona, así que defectos reales del entorno (paths de Alembic,
  configuración del backend, formato del realm-export.json) caen al
  desarrollador en su máquina sin una red de seguridad automática. La
  constitución principio 4 ("Tests primero y obligatorios") exige que la
  suite corra en el mismo entorno que el despliegue.
- **Kubernetes (k8s o k3s) como runtime local.** Descartada por dos
  razones del plan §2.3 y §2.4: (a) introduce un orquestador con su
  propia superficie de configuración (manifiestos, ingress, secrets)
  que la spec 002 no autoriza como nuevo servicio mayor
  (constitución principio 1), y (b) rompe la paridad local/IC:
  GitHub Actions `services:` no existe en local, así que el
  desarrollador terminaría con dos entornos divergentes (HU-7). Compose
  es el mínimo común denominador que corre igual en el portátil y en
  el runner.
- **Podman con pods compose `compose.yaml`.** Descartada por el mismo
  motivo de portabilidad (Docker en macOS/Linux/Windows; Compose v2
  es la referencia en el plan §2.3) y porque el runner de GitHub Actions
  trae Docker preinstalado; usar Podman añadiría setup al workflow sin
  valor para la spec actual.

## Consecuencias

- El runtime de referencia es el contenedor; las dependencias y el
  toolchain embarcan en la imagen (`backend/Dockerfile` instala
  `[dev]` con pytest/ruff; `frontend/Dockerfile` hace `npm ci` con
  devDependencies). Esto encarna el principio 4 de la constitución
  ("el runner de tests de cada stack en verde para cerrar una tarea")
  sin obligar al desarrollador a instalar toolchains locales.
- Los volúmenes de desarrollo (`usher_postgres_data`,
  `usher_redis_data`, `usher_keycloak_data`) son persistentes entre
  arranques del entorno de desarrollo. La verificación automática
  nunca los usa: las secciones `database` y `stack` de
  `scripts/verify.sh` montan la base de datos y Redis en redes
  desechables (`usher_verify_net`) o aplican `down -v` sobre el
  stack completo para validar la reproducibilidad (RF-9).
- El recorrido de arranque con `up -d --wait` se valida como parte
  de la sección `stack` (RF-6, RF-7); el plan §3 congela el timeout
  en 20 minutos y `timeout-minutes: 20` en el job `stack` de
  `.github/workflows/ci.yml`.
- El principio 1 de la constitución queda respetado: Docker y Compose
  son herramientas mayores con ADR previo; no se introduce un
  orquestador nuevo (k8s/k3s/Podman) sin un ADR propio.