---
name: sdd
description: Úsala siempre que trabajes con Spec-Driven Development en este proyecto (docs/constitution.md o cualquier archivo dentro de specs/) - redactar, revisar o cambiar specs, planes y tareas, o implementar y validar tareas de una spec.
--- 

# Spec-Driven Development (SDD)

## Flujo
Constitución → Spec → Clarificación → Plan → Tareas → Implementación → Validación → Cambio.
- El usuario aprueba dos cosas: la spec, y después el plan con las tareas. Solo el coordinator pide esas aprobaciones.
- La spec manda: si algo no está en la spec, no se implementa. Si falta una decisión, para y pregunta.
- Un cambio de requisitos se hace primero en la spec, luego en el plan y las tareas, y por último en el código.
- Cada spec vive en `docs/specs/NNN-nombre/` con `spec.md`, `plan.md` y `tasks.md`.
- El avance se marca en tasks.md. MEMORY.md solo se toca al cerrar la spec.

## Plantilla de spec (spec.md)

```
# Spec NNN — <Nombre>
Estado: borrador | aprobada | implementada
## Contexto y objetivo
## Usuarios
## Historias de usuario
- HU-1. Como <rol>, quiero <acción> para <beneficio>.
## Definiciones (solo si hay términos que puedan interpretarse de varias formas)
## Requisitos funcionales
## Requisitos no funcionales
## Casos límite
## Fuera de alcance
## Criterios de finalización
## Dudas abiertas
- [NECESITA ACLARACIÓN] <duda>
```
La spec describe el QUÉ y el POR QUÉ. Nada de stack, arquitectura ni nombres de archivos.

## Requisitos en EARS (en español)
- RF-x: CUANDO <evento>, EL SISTEMA <respuesta>.
- RF-x: SI <condición no deseada>, ENTONCES EL SISTEMA <respuesta>.
- RF-x: MIENTRAS <estado>, EL SISTEMA <respuesta>.
- RF-x: EL SISTEMA <comportamiento permanente>.
Cada RF debe ser verificable: nada de "rápido", "intenso" o "bonito" sin un criterio medible.

## Plan (plan.md)
Máximo 120 líneas. Contiene: archivos y responsabilidades, decisiones con su alternativa descartada, estrategia de tests con los comandos de AGENTS.md y qué RF cubre cada parte. Pseudocódigo solo si el algoritmo no es obvio.

## Tareas (tasks.md)
```
- [ ] **Tn. <Descripción>.** RF-x, RF-y · tipo: simple|compleja · requiere: docker (solo si aplica)
  - Verify: `<comando exacto>`
  - Hecho cuando: <comprobación verificable>.
```
- Estados: `[ ]` pendiente, `[~]` hecha con verificación solo estática, `[x]` verificada.
- Una tarea toca 5 archivos como máximo y cabe en una sesión corta. Si necesita más, se divide.
- Máximo 15 tareas, en orden de dependencia. Si salen más, propón dividir la spec.
- Las notas de una tarea ocupan una línea.

## Implementación
Una sola tarea cada vez. En lógica: tests primero (rojo), después el código. Corre el `Verify:` de la tarea, márcala en tasks.md y para.
