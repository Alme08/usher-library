# AGENTS.md — Usher Library

Plataforma de lectura colaborativa centrada inicialmente en *The Fall of the House of Usher* de Edgar Allan Poe.

El libro es el centro de la experiencia. Las interacciones sociales existen alrededor del texto, no como un feed independiente.

## Stack y estructura

- Frontend: React + TypeScript + Vite.
- Backend: Python + FastAPI.
- Base de datos: PostgreSQL.
- Sesiones / cache: Redis.
- Autenticación: Keycloak + OpenID Connect.
- Reverse proxy: Caddy.
- Runtime: Docker.
- CI/CD: GitHub Actions.
- Arquitectura: modular monolith.

Estructura principal:

```text
frontend/                aplicación React
backend/                 API y lógica de aplicación
infra/                   Docker, Caddy, Keycloak, despliegue
content/                 contenido fuente del libro
docs/
├── product/             visión y glosario
├── architecture/       arquitectura
├── decisions/           ADRs
└── specs/               especificaciones SDD
.opencode/
├── agents/              agentes especializados
├── commands/            comandos SDD
└── skills/              skills reutilizables
```

## Arquitectura

- `docs/architecture/overview.md` → visión arquitectónica.
- `docs/architecture/system.md` → componentes y comunicación.
- `docs/architecture/database.md` → modelo de datos.
- `docs/architecture/authentication.md` → identidad y sesiones.
- `docs/architecture/security.md` → seguridad.
- `docs/architecture/infrastructure.md` → infraestructura y despliegue.
- `docs/decisions/ADR-*.md` → decisiones y su justificación.

Lee únicamente los documentos relevantes para la tarea. No cargues toda la arquitectura por defecto.

## Producto

- La lectura debe seguir siendo la experiencia principal.
- No convertir el producto en una red social genérica.
- Evita añadir feeds, likes, followers, recomendaciones, mensajería u otras funciones no especificadas.
- Usa siempre la terminología de `docs/product/glossary.md`.
- Los textos visibles de la interfaz deben estar en inglés, salvo que la spec indique lo contrario.

## Datos

PostgreSQL es la fuente de verdad.

Redis nunca es fuente de verdad y solo contiene estado derivado o temporal.

El contenido publicado del libro es inmutable.

Las anotaciones siempre apuntan a:

```text
BookVersion
  ↓
Paragraph
  ↓
start_offset
end_offset
```

Los offsets usan UTF-16 y rangos half-open:

```text
[start_offset, end_offset)
```

Nunca almacenes coordenadas de página, posiciones DOM o píxeles como ubicación canónica de una anotación.

Los cambios de esquema requieren migraciones Alembic.

## Autenticación y seguridad

- Keycloak autentica.
- La aplicación decide autorización.
- Los roles pertenecen a la aplicación.
- El backend es la autoridad de autorización.
- Nunca confíes en roles, ownership o permisos enviados por el frontend.
- Los usuarios solo pueden modificar sus propios recursos salvo permisos administrativos.
- No almacenes tokens de larga duración en `localStorage`.
- Las sesiones son server-side.
- Las cookies de autenticación deben ser `Secure` y `HttpOnly`.
- El contenido generado por usuarios siempre es input no confiable.
- No introduzcas HTML arbitrario en comentarios o anotaciones.
- Nunca guardes secretos en Git.

Consulta `docs/architecture/security.md` y `docs/architecture/authentication.md` cuando la tarea afecte estas áreas.

## Memoria

- Al comenzar, lee `MEMORY.md` si existe.
- También revisa `docs/constitution.md` si existe.
- Revisa la spec activa en `docs/specs/`.
- Al terminar, actualiza `MEMORY.md`.
- Mantén `MEMORY.md` breve: aproximadamente 50 líneas como máximo.
- Guarda únicamente estado actual, decisiones relevantes y errores importantes.
- Si una regla pasa a ser permanente, propón moverla a `AGENTS.md` o a la arquitectura correspondiente.
- Nunca guardes secretos, tokens ni datos personales.

## Forma de trabajar

- Haz únicamente lo especificado.
- No añadas funcionalidades por iniciativa propia.
- Prefiere cambios pequeños y enfocados.
- No reescribas partes funcionales sin necesidad.
- Mantén separación clara entre presentación, aplicación, dominio e infraestructura.
- Antes de introducir una nueva tecnología, dependencia o servicio, verifica la spec y la arquitectura.
- No cambies silenciosamente decisiones arquitectónicas.

## Flujo SDD

Para cambios no triviales:

```text
Spec
 ↓
Design
 ↓
Tasks
 ↓
Implementation
 ↓
Tests
 ↓
Review
```

Antes de modificar código:

1. Lee `docs/product/glossary.md` cuando el dominio sea relevante.
2. Lee la spec activa.
3. Lee el `design.md` si existe.
4. Lee únicamente la arquitectura relevante.
5. Revisa ADRs aplicables.

Si la implementación descubre un conflicto arquitectónico:

```text
Detener implementación
↓
Documentar el conflicto
↓
Proponer decisión
↓
Actualizar ADR/arquitectura
↓
Continuar
```

No resuelvas conflictos arquitectónicos silenciosamente.

## Límites

### ✅ Siempre

- Respetar la arquitectura documentada.
- Validar autorización en backend.
- Mantener PostgreSQL como fuente de verdad.
- Mantener las anotaciones basadas en rangos de texto.
- Añadir tests para cambios relevantes.
- Mantener `MEMORY.md` actualizado.

### ⚠️ Requiere revisión

- Nueva dependencia importante.
- Nuevo servicio de infraestructura.
- Cambio de modelo de datos.
- Cambio de autenticación.
- Cambio de roles/permisos.
- Cambio del modelo de anotaciones.
- Nueva superficie pública de API.
- Nueva funcionalidad de seguridad.

### 🚫 Nunca

- Exponer secretos.
- Confiar en autorización del frontend.
- Guardar tokens de larga duración en `localStorage`.
- Modificar texto publicado directamente.
- Usar Redis como persistencia principal.
- Introducir microservicios sin una decisión arquitectónica explícita.
- Añadir funcionalidades no especificadas.

## Verificación

Frontend:

```text
lint
typecheck
tests
```

Backend:

```text
lint
tests
```

Base de datos:

```text
migration validation
integration tests
```

Cambios de seguridad:

```text
security tests
negative tests
```

Antes de considerar una tarea terminada:

- ejecuta las verificaciones relevantes;
- revisa errores de consola;
- comprueba el comportamiento afectado;
- documenta cualquier desviación o limitación en `MEMORY.md`.

## Comandos

Los comandos concretos del proyecto deben mantenerse en las specs/skills o en esta sección cuando estén definidos.

Ejemplos esperados:

```text
Frontend:
  lint
  typecheck
  test

Backend:
  lint
  test

Infrastructure:
  docker compose ...
```