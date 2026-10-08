# Spec 002 — Foundation: verificación automática y documentación
Estado: borrador

## Contexto y objetivo
Esta spec resulta de dividir la fase Foundation original por exceder el límite de tareas del flujo SDD. **Depende de la spec 001** (`docs/specs/001-foundation/`), que deja el entorno de desarrollo ejecutable: repositorio inicializado, aplicaciones frontend y backend con comprobación de vida, servicios en contenedores, migraciones automáticas con el esquema inicial completo y documentación de arranque.

Sobre esa base, esta spec añade dos cosas: (1) la verificación automática de todo cambio en la plataforma de integración continua fijada por la arquitectura, alineada con la sección "Verificación" de AGENTS.md; (2) la documentación pendiente que Foundation hace necesaria: el documento de arquitectura de infraestructura (referenciado por la arquitectura e inexistente hoy) y los ADRs iniciales de las dependencias, servicios y herramientas introducidas, conforme al principio 1 de la constitución.

## Usuarios
- Desarrolladores del proyecto (no hay funcionalidad de producto para lectores).
- Mantenedores del repositorio y de la infraestructura.

## Historias de usuario
- HU-1. Como desarrollador, quiero que cada push y cada pull request se verifiquen automáticamente para detectar errores antes de integrar.
- HU-2. Como desarrollador, quiero que las migraciones se validen automáticamente, incluido el ciclo aplicar → revertir → aplicar y su integración con la base de datos, para confiar en su reversibilidad antes de integrar.
- HU-3. Como mantenedor, quiero la infraestructura de contenedores y despliegue documentada para que las decisiones operativas sean reproducibles y revisables.
- HU-4. Como mantenedor, quiero que cada dependencia, servicio o herramienta introducida tenga su decisión registrada como ADR para que ninguna incorporación quede sin justificación aprobada.

## Definiciones
- **Verificación automática**: ejecución en la plataforma de integración continua fijada por la arquitectura, alineada con la sección "Verificación" de AGENTS.md: lint, comprobación de tipos, tests y compilación del frontend; lint y tests del backend (no aplica compilación); validación de migraciones y tests de integración de base de datos con los servicios necesarios. Sin publicación ni despliegue.
- **ADR (registro de decisión arquitectónica)**: documento breve en `docs/decisions/` que registra una decisión, su contexto, las alternativas consideradas y sus consecuencias, siguiendo el principio 1 de la constitución.

## Requisitos funcionales
- RF-1: CUANDO se realice un push o se abra/actualice una pull request, EL SISTEMA ejecutará automáticamente la verificación automática completa: lint, comprobación de tipos, tests y compilación del frontend; lint y tests del backend; y validación de migraciones y tests de integración de base de datos, con los servicios necesarios levantados en el propio entorno de integración continua.
- RF-2: MIENTRAS se ejecute la validación de migraciones en la verificación automática, EL SISTEMA comprobará el ciclo aplicar → revertir → aplicar sobre una base de datos vacía.
- RF-3: SI cualquiera de las verificaciones automáticas falla, ENTONCES EL SISTEMA marcará la integración como fallida y visible para el autor del cambio.
- RF-4: EL SISTEMA incluirá el documento de arquitectura de infraestructura (`docs/architecture/infrastructure.md`, referenciado por la arquitectura e inexistente hasta ahora) que describa contenedores, topología de desarrollo (puertos directos, sin proxy inverso), topología de producción (con proxy inverso) y despliegue.
- RF-5: EL SISTEMA incluirá ADRs en `docs/decisions/` para cada dependencia, servicio o herramienta que la fase Foundation haya introducido, conforme al principio 1 de la constitución.

## Requisitos no funcionales
- RNF-1: EL SISTEMA ejecutará los tests de cada stack con el runner propio de ese stack, conforme al principio 4 de la constitución.
- RNF-2: EL SISTEMA permitirá que un desarrollador ejecute localmente las mismas verificaciones que corre la integración continua, sin configuración adicional más allá del entorno ya definido en la spec 001.

## Casos límite
- Push que solo modifica documentación: la verificación automática sigue ejecutándose y pasando, sin comportamientos especiales.
- Verificación automática fallida en una rama: el fallo es visible y no bloquea el trabajo local del desarrollador, solo la integración.
- Servicio de base de datos del entorno de integración continua que tarda en estar listo: la validación de migraciones espera a su disponibilidad antes de ejecutarse, en lugar de fallar en falso.
- Migración cuya reversión está rota: la validación del ciclo (RF-2) falla identificando la migración afectada.
- Dependencia o herramienta introducida sin ADR: la fase no puede cerrarse hasta que el ADR correspondiente existe (RF-5, principio 1 de la constitución).

## Fuera de alcance
- Publicación de imágenes de contenedor, despliegue continuo (CD) y aprovisionamiento de un entorno de producción real. El documento de infraestructura describe el despliegue, pero no se ejecuta.
- Configuración de reglas de protección de ramas en la plataforma de hospedaje del repositorio.
- Pruebas automatizadas de extremo a extremo con navegador.
- Cualquier funcionalidad de producto.
- Modificar requisitos de la spec 001; cualquier cambio en el entorno de desarrollo se tramita como cambio sobre esa spec.

## Criterios de finalización
1. La verificación automática está configurada y en verde en la rama principal, ejecutándose en push y pull request, e incluye: lint, comprobación de tipos, tests y compilación del frontend; lint y tests del backend; validación de migraciones y tests de integración de base de datos con los servicios necesarios.
2. La validación de migraciones de la verificación automática ejercita el ciclo aplicar → revertir → aplicar sobre una base de datos vacía, y un fallo de reversión rompe la integración identificando la migración.
3. Un cambio que rompe lint, tipos, tests o compilación queda marcado como integración fallida y visible para su autor.
4. El documento `docs/architecture/infrastructure.md` existe y cubre contenedores, topología de desarrollo y producción, y despliegue.
5. Existen ADRs en `docs/decisions/` que cubren todas las dependencias, servicios y herramientas introducidos en la fase Foundation.

## Dudas abiertas
- Ninguna por ahora.
