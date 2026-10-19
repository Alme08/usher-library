# ADR-0003 — Keycloak como proveedor de identidad (OIDC)

- Estado: aceptado (2026-10-15).
- Spec: `docs/specs/002-foundation-ci/spec.md` RF-12; lista cerrada en `docs/specs/002-foundation-ci/plan.md` §4.

## Contexto

La arquitectura delega la autenticación en un proveedor externo y
mantiene la autorización como competencia de la aplicación:

- Overview §11: "Authentication is delegated to Keycloak using OpenID
  Connect"; "Keycloak answers: Who is this user? / The application
  answers: What can this user do?"
- Autenticación §2: protocolo OpenID Connect con Authorization Code +
  PKCE; "Long-lived Keycloak tokens are not exposed to browser
  application code".
- Autenticación §3: "Keycloak owns — authentication / password
  recovery / MFA / external identity"; "Usher Library owns — application
  user / username / display name / application role / application
  status / visual preferences / application sessions / authorization".
- Overview §18.5: "The browser is untrusted" — la identidad llega por
  un canal autenticado y validado en backend.

Keycloak corre como servicio de infraestructura propio (overview §4),
cumple la definición de "dependencia, servicio o herramienta mayor"
de la spec 002 ("servicio de infraestructura que corre como proceso o
contenedor propio"), y por tanto requiere un ADR aprobado por el
principio 1 de la constitución.

## Decisión

Se adopta **Keycloak 24.0** como proveedor de identidad.

- Imagen de contenedor: `quay.io/keycloak/keycloak:24.0`
  (`infra/docker-compose.yml` servicio `keycloak`).
- Comando de arranque: `start-dev --import-realm` (Compose) — el flag
  `--import-realm` toma `infra/keycloak/realm-export.json` desde
  `/opt/keycloak/data/import/` y crea el realm `usher-library` en el
  primer arranque, reproduciendo el realm en cada stack limpio.
- Healthcheck: TCP al puerto de administración (`localhost:8080`) porque
  la imagen base de Keycloak 24 (`ubi9-micro`) no incluye `curl` ni
  `wget`; la sonda está documentada en `infra/docker-compose.yml`.
- Cliente OIDC: confidential con Authorization Code + PKCE
  (autenticación §4). El secreto del cliente vive solo en backend
  (autenticación §4 "The client secret exists only on the backend").
- Mapping de identidad: `OIDC sub` ↔ `users.keycloak_subject`
  (autenticación §6, database §4); las claves ajenas del dominio usan
  `users.id`.

## Alternativas consideradas

- **Auth0 / Okta (SaaS gestionado).** Descartada por dos razones
  operativas: (a) introduce un secreto externo más por tercero y un
  endpoint fuera del control del proyecto, lo que aumenta la superficie
  que la constitución principio 5 ("datos del usuario protegidos")
  tendría que auditar; (b) requiere credenciales de pago o cuenta
  gestionada que el repositorio no podría versionar (RNF-4 de la
  spec 002). Keycloak corre en el propio entorno y el realm se importa
  desde el repositorio, manteniendo la trazabilidad.
- **Django/Flask auth casero con `users` propio.** Descartada: el
  principio 3 de la constitución reserva al dominio "libre de
  dependencias de framework y de cliente"; reimplementar OIDC, MFA,
  flujos de recuperación y federation añade cientos de líneas
  criptográficas sensibles. Keycloak resuelve eso como dependencia
  externa, dejando al backend solo el contrato `AuthenticatedUser`
  (autenticación §27).
- **Keycloak ≥ 25.** Descartada por incompatibilidades reales detectadas
  en el cierre de la spec 001 (ver `docs/learnings.md`): los
  `realm-export.json` generados por Keycloak 25/26 incluyen campos no
  soportados por Keycloak 24 (`verifyEmailListedRealm`,
  `loginLifecycleBehavior`, `clientType`, etc.) y `CLIENT.DESCRIPTION`
  se limita a `VARCHAR(255)`. Mantener Keycloak 24.0 —la LTS de la
  familia 24 — evita esa deriva y mantiene el `realm-export.json` del
  repositorio reproducible.

## Consecuencias

- Keycloak autentica; la aplicación autoriza (autenticación §3,
  overview §11). Los roles `READER` / `ADMIN` viven en PostgreSQL
  (`users.role`, `docs/architecture/database.md` §4) y nunca en
  Keycloak; un cambio de rol en la base de datos invalida las sesiones
  existentes (autenticación §26, RNF-8).
- Los tokens de larga duración no se exponen al navegador
  (autenticación §22, principio 5 de la constitución). El frontend
  recibe únicamente el identificador opaco de la sesión server-side.
- El realm `usher-library` se importa desde
  `infra/keycloak/realm-export.json` en cada arranque limpio. Cualquier
  cambio del realm es un cambio del repositorio (auditable) y entra
  en el flujo de verificación por la sección `stack` de
  `scripts/verify.sh`, que valida la importación en los logs de Keycloak
  (RF-6).
- Las credenciales de `KEYCLOAK_ADMIN` viven en `.env` (gitignorado)
  y son marcadores de desarrollo; el ADR no publica ni versiona ningún
  secreto (RNF-4 de la spec 002, constitución principio 5).
- El principio 1 de la constitución queda respetado: la decisión de
  delegar identidad en Keycloak está registrada antes de que la spec
  002 cierre la deuda de trazabilidad; el rol del proveedor es
  limitado y auditado.