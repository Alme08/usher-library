# Spec 001 — Foundation: entorno de desarrollo ejecutable
Estado: aprobada

## Contexto y objetivo
El proyecto está en fase de documentación: `backend/`, `frontend/` e `infra/` están vacíos y no existe código, repositorio de control de versiones inicializado, specs ni ADRs. La arquitectura (stack, componentes y topología) ya está fijada en `docs/architecture/` y la constitución define 6 principios innegociables; esta spec no elige tecnologías, exige que el proyecto quede inicializado y ejecutable conforme a esa arquitectura.

El objetivo de esta spec es que cualquier desarrollador pueda clonar el repositorio y levantar el entorno de desarrollo completo con una sola acción (incluida la aplicación automática de migraciones), disponiendo del esquema inicial completo del dominio.

**Nota de alcance:** esta spec resulta de dividir la fase Foundation original por exceder el límite de tareas del flujo SDD. La verificación automática en integración continua y la documentación de infraestructura y de decisiones (ADRs) se cubren en la spec 002 (`docs/specs/002-foundation-ci/`), que depende de esta.

## Usuarios
- Desarrolladores del proyecto (único usuario de esta fase; no hay funcionalidad de producto para lectores).
- Mantenedores del repositorio y de la infraestructura.

## Historias de usuario
- HU-1. Como desarrollador, quiero levantar todo el entorno de desarrollo con un único comando para empezar a trabajar sin configuración manual ni instalación de runtimes en mi máquina.
- HU-2. Como desarrollador, quiero comprobar de forma visible que el entorno ha levantado correctamente, incluidos sus servicios, para saber si puedo trabajar o si algo falla.
- HU-3. Como desarrollador, quiero migraciones de base de datos versionadas con el esquema inicial completo del dominio para evolucionar el modelo de datos de forma controlada y reversible.
- HU-4. Como desarrollador, quiero documentación de arranque y valores de configuración de ejemplo para levantar el entorno sin adivinar configuración ni exponer secretos.

## Definiciones
- **Entorno de desarrollo reproducible**: entorno aislado mediante contenedores que cualquier desarrollador levanta con el mismo resultado, sin instalar runtimes del proyecto en la máquina anfitriona (solo el runtime de contenedores). En desarrollo no hay proxy inverso: las aplicaciones se exponen por puertos directos; el proxy solo aparece en la topología de producción documentada.
- **Comprobación de vida (readiness)**: señal inequívoca de que un componente responde y de que los servicios de los que depende son accesibles. Para el backend: la aplicación responde y la base de datos y el almacén de estado temporal son accesibles. Para el frontend: la página provisional se sirve en el navegador. Para los servicios (base de datos, almacén temporal, proveedor de identidad): contenedor operativo y alcanzable en la red del entorno. No implica integración funcional ni lógica de dominio.
- **Esquema de dominio completo**: el esquema inicial ("Initial Schema") del modelo de datos documentado en `docs/architecture/database.md`: núcleo del libro (libro, versión de libro, capítulo, párrafo), anotaciones, comentarios, tablas de referencia de estilos (fuentes de escritura, tintas, texturas), eventos de auditoría y usuarios de aplicación, con sus restricciones e índices documentados. Las respuestas a comentarios NO son una tabla propia: se representan mediante la autorreferencia de comentarios (`parent_comment_id`).

## Requisitos funcionales
- RF-1: EL SISTEMA mantendrá el código de frontend, backend e infraestructura en un único repositorio, organizado según la estructura definida en la arquitectura.
- RF-2: EL SISTEMA estará gestionado en un repositorio de control de versiones inicializado, con reglas de exclusión que impidan versionar secretos, credenciales, dependencias instaladas y artefactos generados.
- RF-3: CUANDO un desarrollador ejecute el comando documentado de arranque, EL SISTEMA levantará de forma aislada todos los componentes del entorno de desarrollo definidos en la arquitectura: aplicación frontend, aplicación backend, base de datos relacional, almacén de estado temporal y proveedor de identidad.
- RF-4: CUANDO se ejecute el comando de arranque, EL SISTEMA aplicará automáticamente las migraciones pendientes sobre la base de datos del entorno, sin pasos manuales adicionales.
- RF-5: MIENTRAS el entorno de desarrollo esté levantado, EL SISTEMA expondrá las aplicaciones frontend y backend mediante puertos directos de la máquina anfitriona, sin proxy inverso.
- RF-6: SI el entorno se detiene por completo y se vuelve a arrancar desde cero, ENTONCES EL SISTEMA reproducirá el mismo entorno sin pasos manuales adicionales.
- RF-7: CUANDO un componente dependa de otro para estar listo (por ejemplo, el backend de la base de datos), EL SISTEMA esperará a que la dependencia esté disponible antes de dar el componente por listo; SI la dependencia no llega a estar disponible, ENTONCES EL SISTEMA informará del fallo identificando la dependencia.
- RF-8: SI un recurso necesario del entorno no está disponible al arrancar (por ejemplo, un puerto ocupado), ENTONCES EL SISTEMA informará del conflicto con un mensaje que permita identificar la causa.
- RF-9: CUANDO el entorno de desarrollo esté levantado, EL SISTEMA expondrá una comprobación de vida del backend que confirme que la aplicación responde y que la base de datos y el almacén de estado temporal son accesibles.
- RF-10: CUANDO el entorno de desarrollo esté levantado, EL SISTEMA servirá una página provisional de la aplicación frontend accesible desde el navegador.
- RF-11: CUANDO el entorno de desarrollo esté levantado, EL SISTEMA mantendrá los contenedores de la base de datos, el almacén de estado temporal y el proveedor de identidad operativos y alcanzables en la red interna del entorno, sin exigir integración funcional del backend con ellos más allá de la verificación de accesibilidad de RF-9.
- RF-12: EL SISTEMA incluirá en el repositorio documentación de arranque del entorno que describa los prerrequisitos y el comando único de arranque.
- RF-13: EL SISTEMA dispondrá de migraciones de base de datos versionadas, aplicables y revertibles de forma ordenada.
- RF-14: CUANDO se apliquen las migraciones sobre una base de datos vacía, EL SISTEMA creará el esquema de dominio completo con las restricciones e índices del modelo de datos documentado.
- RF-15: CUANDO existan migraciones sucesivas, EL SISTEMA las aplicará de forma incremental sin destruir datos existentes. *Nota: en Foundation solo existe la migración inicial, por lo que este comportamiento no es verificable hasta que una spec posterior introduzca una segunda migración; se mantiene como regla permanente de la herramienta de migraciones y se verificará a partir de entonces.*
- RF-16: SI al aplicar migraciones se detecta una base de datos con datos pero sin historial de migraciones, ENTONCES EL SISTEMA detendrá la aplicación automática e informará de la situación, sin modificar el esquema ni los datos.
- RF-17: EL SISTEMA mantendrá credenciales y secretos del entorno fuera del control de versiones, proporcionando valores de ejemplo no sensibles para desarrollo.

## Requisitos no funcionales
- RNF-1: EL SISTEMA permitirá levantar el entorno de desarrollo completo con un único comando documentado.
- RNF-2: MIENTRAS se ejecuten los tests de la lógica de dominio, EL SISTEMA no requerirá los servicios de infraestructura (base de datos, almacén de estado temporal, proveedor de identidad); los tests se ejecutan dentro de contenedores o del entorno de integración continua, sin exigir runtimes del proyecto instalados en la máquina anfitriona.
- RNF-3: EL SISTEMA no requerirá servicios externos de pago ni acceso a red más allá de la descarga inicial de dependencias para levantar el entorno de desarrollo.
- RNF-4: EL SISTEMA mantendrá el código, los identificadores y los textos visibles de la interfaz (incluida la página provisional) en inglés, conforme a la constitución.
- RNF-5: EL SISTEMA ejecutará los tests de cada stack con el runner propio de ese stack, conforme al principio 4 de la constitución.

## Casos límite
- Primera ejecución en una máquina limpia: el entorno debe levantar asumiendo únicamente el runtime de contenedores instalado.
- Repositorio sin inicializar: esta spec incluye la inicialización del control de versiones y sus reglas de exclusión desde el primer commit (RF-2).
- Arranque parcial: el backend intenta arrancar antes de que la base de datos esté lista; el entorno espera y no falla en falso (RF-7).
- Dependencia que nunca queda disponible: el arranque falla informando de qué dependencia falta (RF-7).
- Puerto en uso por otra aplicación: el arranque falla informando del puerto en conflicto (RF-8).
- Volumen de base de datos previo sin historial de migraciones: la aplicación automática se detiene e informa, sin tocar esquema ni datos (RF-16).
- Migración revertida y reaplicada: el ciclo aplicar → revertir → aplicar deja el esquema en el estado esperado; en esta fase se verifica manualmente en local y su verificación automática en integración continua queda en la spec 002.
- Revertir la migración inicial con datos existentes: operación destructiva por naturaleza; solo se ejecuta por acción explícita del desarrollador, nunca automáticamente durante el arranque.

## Fuera de alcance
- Verificación automática en integración continua (push/pull request), incluida la validación automática del ciclo de migraciones y los tests de integración de base de datos: se cubre en la spec 002.
- Documento de arquitectura de infraestructura (`docs/architecture/infrastructure.md`) y ADRs iniciales (`docs/decisions/`): se cubren en la spec 002.
- Flujo de autenticación real de punta a punta con el proveedor de identidad (login, sesiones, roles). El proveedor se levanta en el entorno, pero su integración funcional va en una spec posterior.
- Carga inicial (seed) del contenido de *The Fall of the House of Usher* desde `content/`; pertenece a una spec posterior de contenido.
- Publicación de imágenes de contenedor, despliegue continuo (CD) y aprovisionamiento de un entorno de producción real.
- Proxy inverso en el entorno de desarrollo: en desarrollo se usan puertos directos; el proxy solo se documenta para la topología de producción.
- Cualquier funcionalidad de producto: lectura del libro, anotaciones, comentarios, perfiles, moderación, personalización.
- Integración funcional del backend con la base de datos y el almacén de estado temporal (repositorios, casos de uso); esta spec solo exige la comprobación de accesibilidad de RF-9.
- Pruebas automatizadas de extremo a extremo con navegador.
- Datos de ejemplo del dominio (usuarios, anotaciones) más allá de lo imprescindible para verificar el esquema.
- Verificación del comportamiento incremental de migraciones sucesivas (RF-15): no ejercitable hasta que exista una segunda migración.

## Criterios de finalización
1. Un desarrollador clona el repositorio y, con un único comando documentado, levanta el entorno completo: las migraciones se aplican automáticamente, la comprobación de vida del backend confirma respuesta y accesibilidad de base de datos y almacén temporal, la página provisional del frontend es visible en el navegador por puerto directo, y los contenedores de servicios están operativos en la red del entorno.
2. Tras detener el entorno por completo y rearrancarlo desde cero, se reproduce el mismo entorno sin pasos manuales adicionales.
3. Provocando un conflicto de puerto, el arranque falla con un mensaje que identifica la causa.
4. Sobre una base de datos vacía, las migraciones crean el esquema de dominio completo con las restricciones e índices documentados; el ciclo aplicar → revertir → aplicar funciona verificado en local (su automatización queda en la spec 002).
5. No hay secretos ni credenciales reales en el repositorio; las reglas de exclusión están configuradas, existen valores de ejemplo documentados y la documentación de arranque está presente.

## Dudas abiertas
- Ninguna por ahora.
