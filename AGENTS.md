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
- MEMORY.md guarda el estado entre specs. Léelo solo si eres el coordinator o la tarea lo cita.
- Solo el implementer de la última tarea de una spec lo reescribe (máximo 1.5 KB).
- Aprendizajes técnicos nuevos: una línea en docs/learnings.md.

## Forma de trabajar
- Haz únicamente lo especificado.
- No añadas funcionalidades por iniciativa propia.
- Prefiere cambios pequeños y enfocados.
- No reescribas partes funcionales sin necesidad.
- Mantén separación clara entre presentación, aplicación, dominio e infraestructura.
- Antes de introducir una nueva tecnología, dependencia o servicio, verifica la spec y la arquitectura.
- No cambies silenciosamente decisiones arquitectónicas.
- Nunca leas ni busques con grep en: dist/, node_modules/, *.lock, package-lock.json, *.min.js. Para dependencias usa `npm ls <paquete>`.

## Flujo SDD
Para cambios no triviales:
Spec → Plan → Tasks → Implementación → Tests → Review (detalle en la skill sdd)

## Flujo SDD
Spec → Plan → Tasks → Implementación → Tests → Review. Detalle en la skill sdd.

Antes de tocar código lee tu tarea y los RF que cita. Lee architecture/ o el glossary solo si la tarea toca ese dominio.
Si descubres un conflicto arquitectónico: para, documéntalo y propón una decisión. No lo resuelvas en silencio.

## Límites - Requiere revisión
- Nueva dependencia importante.
- Nuevo servicio de infraestructura.
- Cambio de modelo de datos.
- Cambio de autenticación.
- Cambio de roles/permisos.
- Cambio del modelo de anotaciones.
- Nueva superficie pública de API.
- Nueva funcionalidad de seguridad.

## Verificación
  Backend:  cd backend && ruff check . && pytest -q
  Frontend: cd frontend && npm run lint && npm run typecheck && node --test && npm run build
  Compose:  docker compose -f infra/docker-compose.yml up -d --wait
  Verificación completa (local e integración continua):  ./scripts/verify.sh

## Comandos
Los comandos concretos del proyecto deben mantenerse en las specs/skills o en esta sección cuando estén definidos. La definición única de verificación del proyecto vive en la sección «Verificación» anterior; este apartado queda libre de listas de comandos que la dupliquen.