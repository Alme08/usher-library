# ADR-0007 — GitHub Actions como plataforma de integración continua

- Estado: aceptado (2026-10-15).
- Spec: `docs/specs/002-foundation-ci/spec.md` RF-12; lista cerrada en `docs/specs/002-foundation-ci/plan.md` §4.

## Contexto

La arquitectura fija la integración continua como parte del stack:
"CI/CD: GitHub Actions" en `docs/architecture/overview.md` §20
"Confirmed technology choices". El repositorio está hospedado en
GitHub con `origin` ya conectado (spec 002 §"Prerrequisito del
usuario"; plan §0) y la spec 002 nace para corregir el defecto del
cierre de la spec 001, cuya verificación solo inspeccionaba el
sistema y no lo ejecutaba, por lo que tres defectos reales
(paths de Alembic, configuración del backend, formato del
realm-export.json) cayeron al desarrollador sin una red de seguridad
automática (`docs/specs/002-foundation-ci/spec.md` §0; `docs/learnings.md`
entradas 5, 9, 13–17).

La plataforma de CI es una dependencia mayor: estructura el flujo
de verificación del cambio y está enumerada en la lista cerrada de
ADRs del plan §4. El principio 1 de la constitución obliga a
registrar esta incorporación con un ADR antes de que los commits
lleguen a `origin/main`.

## Decisión

Se adopta **GitHub Actions** como plataforma de integración continua,
con la siguiente materialización anclada al workflow
`.github/workflows/ci.yml`:

- Disparadores: `on: push` (todas las ramas, `branches: "**"`) y
  `on: pull_request` para todo PR. La duplicación en push + PR es
  explícita en el plan §2.8 ("se aceptan ejecuciones duplicadas push+PR:
  prima la visibilidad") y refleja RF-1, RF-8.
- Trabajos: cuatro independientes, sobre `ubuntu-latest` (runner que
  trae Docker preinstalado), cada uno ejecutando una sección de
  `scripts/verify.sh`. `timeout-minutes` congelados del plan §3,
  iguales a los del workflow real:
  - `backend`: 10 minutos (lint + tests del backend en la imagen).
  - `frontend`: 10 minutos (lint + typecheck + `node --test` +
    `npm run build` en la imagen).
  - `database`: 15 minutos (bloque desechable + ciclo de migraciones +
    `pytest -m integration` tras el primer y último `upgrade head`).
  - `stack`: 20 minutos (dos arranques completos del stack con
    `up -d --wait`, comprobación de `/health`, importación del realm
    en Keycloak, `down -v`, port-conflict test).
- Lógica íntegra en `scripts/verify.sh` (plan §2.2 "un solo script con
  secciones; ci.yml solo hace checkout y llama a la sección"). El
  workflow añade únicamente `actions/checkout` y la invocación del
  script, para no divergir de la verificación local (HU-7,
  constitución principio 4: "el runner de tests de cada stack en
  verde para cerrar una tarea").
- `concurrency: ci-${{ github.workflow }}-${{ github.ref }}` con
  `cancel-in-progress: true` para no gastar minutos en pushes
  incrementales del mismo PR.
- Única action externa: `actions/checkout@v4` (plan §2.8). No se
  usan `setup-python` / `setup-node`: las suites corren dentro de las
  imágenes del repositorio, no en runners de terceros (plan §2.3).

## Alternativas consideradas

- **GitLab CI / CircleCI.** Descartadas por dos razones: (a) la
  arquitectura fija GitHub Actions como plataforma (overview §20), y
  reabrir esa decisión violaría el principio del plan §2.1; (b) el
  repositorio ya está hospedado en GitHub con `origin` conectado
  (spec 002 §"Prerrequisito del usuario"), así que mover la
  verificación a otro proveedor implicaría duplicar el código del
  workflow y romper la traza del cambio (RF-8: el resultado debe ser
  visible para el autor del push).
- **Un único trabajo que ejecute `./scripts/verify.sh all`.**
  Descartado por dos motivos: (a) plan §2.8 lo prohíbe explícitamente
  ("[Job único: sin timeouts por bloque ni atribución clara (RF-7)]");
  un solo trabajo no podría acotar el stack a 20 minutos sin que un
  fallo del backend a los 5 minutos consuma el presupuesto del stack.
  (b) Sin jobs paralelos, el `frontend` espera al `backend` aunque son
  independientes — el wall-clock del run crece innecesariamente.
- **Solo lint y tests unitarios (sin stack recorrido ni base
  desechable).** Descartado por el precedente del cierre de la spec
  001, que demuestra exactamente el riesgo: la inspección estática no
  detectó los tres defectos reales. La spec 002 nace para que
  `pytest -m integration` corra contra PostgreSQL y Redis reales
  (RF-3) y que el recorrido de arranque (RF-6, RF-7) ejercite
  `up -d --wait`, `/health`, los healthchecks de Keycloak y el
  `down -v`. Limitar CI a lint + tests unitarios repetiría el error
  documentado en `docs/specs/002-foundation-ci/spec.md` §0.

## Consecuencias

- Coste y tiempo: el trabajo `stack` levanta el entorno dos veces
  (primer arranque + re-arranque tras `down -v`, plan §5) y aplica
  el port-conflict test, dentro del techo de 20 minutos. Los
  restantes trabajos son lineal el tiempo del backend y frontend en
  sus imágenes.
- Dependencia del runtime: los cuatro trabajos ejecutan sobre
  `ubuntu-latest`, que trae Docker y Docker Compose v2 preinstalados.
  No se introduce ninguna dependencia de infraestructura adicional más
  allá del runtime de contenedores (RNF-2 de la spec 002).
- Visibilidad: cada push y cada PR produce un run con cuatro
  trabajos. Si cualquiera falla, RF-8 exige que el resultado sea visible
  para el autor — esto queda configurado por defecto en GitHub
  Actions; la spec 002 no introduce reglas de protección de rama
  (queda fuera de alcance, spec §"Fuera de alcance").
- Pendiente del usuario: la ejecución real sobre `origin/main`
  requiere que el usuario habilite GitHub Actions y haga `git push`
  de los commits (T12). Hasta entonces, este ADR y el workflow
  existen en el entorno local y se ejecutan en verde en
  `./scripts/verify.sh`, pero no hay un run verde hospedado. T5
  marca el flujo `[~]` por el mismo motivo.
- El principio 1 de la constitución queda respetado: la plataforma
  de CI es una dependencia mayor registrada por ADR antes de que
  los commits lleguen al remoto.