# Constitución de Usher Library

Estos principios son innegociables: cualquier conflicto con ellos detiene la implementación.

1. **Stack simple y único.** Monolito modular (React + FastAPI + PostgreSQL); Redis es solo estado derivado. Toda dependencia o servicio nuevo exige un ADR aprobado. *Comprobar: no hay servicios ni dependencias nuevas sin ADR.*
2. **La spec manda.** Nada se implementa si no está en una spec de `docs/specs/`; si falta una decisión, se para y se pregunta. El cambio va spec → plan/tareas → código. *Comprobar: cada RF es trazable a código y test.*
3. **Lógica separada de la interfaz.** El dominio no depende de FastAPI, React, PostgreSQL, Redis ni Keycloak; el frontend nunca autoriza ni define ubicaciones. La ubicación canónica es `(paragraph, start_offset, end_offset)` UTF-16. *Comprobar: dominio testeable sin framework; rangos validados en backend.*
4. **Tests primero y obligatorios.** Primero el test en rojo, luego el código; el runner de tests de cada stack en verde para cerrar una tarea (p. ej. `node --test` en frontend, `pytest` en backend); cambios de seguridad añaden tests negativos. *Comprobar: ninguna tarea se cierra con tests en rojo.*
5. **Datos del usuario protegidos.** PostgreSQL es la única fuente de verdad; el backend es la autoridad de autorización; nunca secretos ni tokens en Git; nunca tokens de larga duración en `localStorage`; solo datos personales necesarios. *Comprobar: no se confía en roles ni tokens del cliente.*
6. **Idioma.** Código (identificadores, comentarios, commits) y textos visibles de la interfaz en inglés; specs y documentación de trabajo (AGENTS, MEMORY, constitution) en español. *Comprobar: nombres y copy en inglés; specs en español.*
