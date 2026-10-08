# Tareas — Spec 001: Foundation, entorno de desarrollo ejecutable

Orden de dependencia. Tests primero (en rojo), luego el código, runner en verde para cerrar la tarea (P4). Los comandos se ejecutan dentro de contenedores salvo los de git.

- [x] **T1. Base del monorepo y control de versiones.** RF-1, RF-2, RF-12, RF-17
  - Hecho cuando: `git init` hecho con la estructura del plan; `.gitignore` excluye `.env`, dependencias y artefactos; `.env.example` contiene solo valores no sensibles; `README.md` documenta prerrequisitos y el comando único de arranque.
- [ ] **T2. Esqueleto del backend + dominio de readiness (pytest primero).** RF-9 (lógica), RNF-2, RNF-5
  - Hecho cuando: `pyproject.toml` con deps y config de pytest/ruff; `test_readiness.py` y `test_health_api.py` pasan sin levantar servicios; la app FastAPI responde `GET /health` con sondas falsas (200 todo OK, 503 con sonda caída identificada); ruff sin errores.
- [ ] **T3. Esqueleto del frontend + página provisional (node --test primero).** RF-10, RNF-4, RNF-5
  - Hecho cuando: scaffold Vite + React + TS con lint y typecheck sin errores; `appInfo.test.ts` pasa con `node --test`; la página provisional muestra el copy en inglés de `appInfo.ts`.
- [ ] **T4. Dockerfiles de desarrollo (backend y frontend).** RF-3
  - Hecho cuando: ambas imágenes construyen y arrancan de forma aislada; el backend ejecuta su entrypoint y el frontend sirve la página provisional en sus contenedores.
- [ ] **T5. Compose: PostgreSQL, Redis y Keycloak.** RF-3, RF-11
  - Hecho cuando: `docker compose up` de los tres servicios los deja healthy en la red interna; Keycloak importa `realm-export.json` al arrancar; nada requiere instalación en la máquina anfitriona.
- [ ] **T6. Compose: aplicaciones, orden de arranque y readiness real.** RF-3, RF-5, RF-6, RF-7, RF-8, RF-9
  - Hecho cuando: comando único levanta el entorno completo con frontend y backend en puertos directos; `/health` devuelve 200 con postgres y redis OK; el backend espera a la BD (arranque parcial sin fallo en falso); un puerto ocupado produce un mensaje que identifica el conflicto; rearrancar desde cero reproduce el entorno.
- [ ] **T7. Alembic: configuración + migración del núcleo del libro.** RF-13, RF-14 (parcial)
  - Hecho cuando: Alembic configurado con la URL de entorno; la migración crea `books`, `book_versions`, `chapters` y `paragraphs` con sus constraints (incluida `UNIQUE(book_id, version_number)`, ordenaciones y hashes); `downgrade` las elimina.
- [ ] **T8. Migración: annotations y comments.** RF-14 (parcial)
  - Hecho cuando: la migración crea `annotations` y `comments` con las restricciones documentadas (rango UTF-16 half-open, `UNIQUE(paragraph_id, user_id, start_offset, end_offset)`, invariante highlight/note, `parent_comment_id` autorreferenciado, soft delete) y los índices requeridos; `downgrade` revierte.
- [ ] **T9. Migración: users, estilos de referencia y audit_events.** RF-14 (completa)
  - Hecho cuando: la migración crea `users` (con FKs a estilos y `keycloak_subject` único), `handwriting_fonts`, `ink_styles`, `paper_textures` y `audit_events` (append-only); el esquema resultante coincide con el Initial Schema completo de `docs/architecture/database.md`.
- [ ] **T10. Auto-migración en arranque + guarda RF-16 + ciclo de migraciones.** RF-4, RF-16 (criterio 4)
  - Hecho cuando: `test_migration_guard.py` pasa; al levantar con el comando único las migraciones se aplican sin pasos manuales; una BD con tablas y sin historial aborta el arranque con mensaje claro sin tocar datos; el ciclo `upgrade head → downgrade base → upgrade head` se ejecuta manualmente sobre la BD del entorno dejando el esquema esperado.
