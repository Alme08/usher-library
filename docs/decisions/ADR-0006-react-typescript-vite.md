# ADR-0006 — React + TypeScript + Vite como frontend

- Estado: aceptado (2026-10-15).
- Spec: `docs/specs/002-foundation-ci/spec.md` RF-12; lista cerrada en `docs/specs/002-foundation-ci/plan.md` §4.

## Contexto

La arquitectura fija el frontend como una SPA React servida en
producción por el reverse proxy y responsable de la presentación del
lector (`docs/architecture/overview.md` §4 "Components", §8 "Reader
Architecture", §13 "Personalization"; `docs/architecture/system.md` §2).
La constitución principio 3 obliga a que el frontend nunca autorice ni
defina ubicaciones canónicas; principio 6 obliga a identificadores,
comentarios y copy en inglés. El ADR debe dejar explícito ese perímetro.

"React + TypeScript + Vite" está fijado como "Confirmed technology
choice" (`docs/architecture/overview.md` §20
"Frontend: React + TypeScript + Vite"). Es un framework que estructura
un stack completo de la arquitectura (definición de mayor en la spec
002) y, por tanto, exige ADR por principio 1 de la constitución.

## Decisión

Se adopta **React 19 + Vite 7** sobre **TypeScript 5.6** como frontend,
con el toolchain del repositorio:

- Versiones ancladas a `frontend/package.json`:
  `react ^19.0.0`, `react-dom ^19.0.0`,
  `vite ^7.0.0`, `@vitejs/plugin-react ^5.0.0`,
  `typescript ^5.6.0`, `typescript-eslint ^8.0.0`,
  `eslint ^9.0.0`, `eslint-plugin-react-hooks ^5.0.0`,
  `eslint-plugin-react-refresh ^0.5.0`,
  `@types/node ^24.0.0`. Runtime del contenedor:
  `node:24-bookworm-slim` (`frontend/Dockerfile`).
- Scripts de npm (package.json):
  `dev` arranca Vite, `build` ejecuta `tsc -b && vite build`, `test`
  usa `node --test`, `lint` corre `eslint .`, `typecheck` usa
  `tsc -b --noEmit`. Esta es la suite que la spec 002 invoca dentro
  de la imagen del repo (`scripts/verify.sh frontend`, plan §2.3).
- El lector se construye como SPA; el backend provee la API; las
  decisiones de autorización viven en el backend
  (`docs/architecture/overview.md` §11–§12, constitución principio 3).
- Estilos de escritura/tinta/textura se modelan como referencias a
  assets persistidos (`docs/architecture/overview.md` §13) — el frontend los
  renderiza, no los embebe en anotaciones.

## Alternativas consideradas

- **Next.js.** Descartado por dos razones operativas: (a) introduce
  routing, server components y un servidor Node de larga duración que la
  arquitectura ya no necesita (el backend FastAPI cubre la API y el
  reverse proxy sirve estáticos); mantener Next.js añade una segunda
  capa de runtime sin valor para un proyecto donde "Page layout" es
  "Frontend" en overview §17. (b) Encadenaría el frontend al servidor
  de Next.js para cosas como SSR, contradiciendo el principio de
  simplicidad de overview §3 ("prefer a modular monolith over
  unnecessary distributed architecture"). El toolchain que ya tenemos
  (Vite + `node --test`) cubre lo que necesitamos sin esa sobrecarga.
- **SvelteKit.** Descartado porque (a) saldría de la "Confirmed
  technology choice" del overview §20 sin un caso concreto que lo
  justifique (constitución principio 10, "Prefer simple architecture
  over speculative infrastructure"); y (b) implica migrar todo el
  toolchain (eslint, typescript, vitest si lo hubiera) a otro ecosistema
  con ROI incierto.
- **Plantillas server-rendered sin build step (HTML estático servido
  por FastAPI o Caddy).** Descartado porque la SPA React necesita un
  build reproducible y determinista (`docs/specs/002-foundation-ci/plan.md`
  §2.3 "npm ci installs exact versions from package-lock.json
  (deterministic build)") y Vite lo da de fábrica; recrear bundling y
  HMR a mano no aporta.

## Consecuencias

- El frontend se sirve en producción como estáticos generados por
  `npm run build` (`tsc -b && vite build`); Caddy o el reverse proxy
  del entorno productivo los entrega, y FastAPI atiende `/api/*` y
  `/auth/*` desde el mismo origen
  (`docs/architecture/authentication.md` §21 "Same-Origin Deployment",
  constitution principio 5).
- El toolchain del frontend corre dentro del contenedor
  (`frontend/Dockerfile` con `npm ci`), así que el runner local y el
  runner de GitHub Actions ejecutan exactamente el mismo
  `npm run lint && npm run typecheck && node --test` (RNF-2 de la
  spec 002).
- Las pruebas de frontend usan el runner nativo de Node (`node --test`)
  en lugar de un marco adicional (Vitest/Jest), reduciendo
  dependencias: cumple el principio 4 de la constitución ("el runner
  de tests de cada stack en verde para cerrar una tarea") con lo que el
  propio stack ya trae.
- TypeScript aplica tipos en build y en typecheck; ESLint aplica las
  reglas de React Hooks y react-refresh. Los textos visibles de la
  interfaz quedan en inglés (constitución principio 6).
- El principio 1 de la constitución queda respetado: la elección del
  framework frontend está registrada antes de la spec 002; no se
  introduce un segundo framework de presentación sin ADR.