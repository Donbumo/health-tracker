# Contexto estable del producto

Este documento es contexto frío. Explica la visión y los límites duraderos de Health Tracker; no contiene el estado de una rama, resultados temporales de QA ni instrucciones obligatorias para toda tarea.

Para trabajo en curso consulta `ACTIVE_HANDOFF.md`. Para localizar contratos y guías usa `DOCUMENTATION_INDEX.md`. La arquitectura ejecutable resumida está en `architecture/OVERVIEW.md`.

## Base y dirección actuales

La base oficial es **Health Tracker Beta 1.0.1** en `master` (`64abf34b0c7082fc31c75b8a4bef62c5786e50d1`). Web, Android, API y MariaDB forman una sola base consolidada; Resumen longitudinal y Hoy están cerrados, Health Connect funciona en dispositivo físico y mobile sync/offline está operativo. Objetivos/recordatorios/adherencia, registros médicos, intercambio de actividades y portabilidad de datos también existen.

La prioridad actual es evolucionar **Beta 1.1 AI Foundation** con el AI Operator
seguro y mantener después **Beta 1.2 External Integrations**. Device Bridge/BLE
continúa en una fase posterior. IA e integraciones comparten el mismo modelo de
procedencia. Ninguna feature nueva debe partir de ramas Alpha antiguas ni de
`integration/alpha-1.5-dashboard`.

## Visión

Health Tracker es una plataforma privada, self-hosted y multiusuario para normalizar, conservar, analizar e intercambiar datos personales de salud y entrenamiento.

Las actividades de dispositivo siguen el mismo principio: FIT/GPX/TCX se normalizan a un contrato propio auditable, el original permanece privado, las rutas tienen consentimiento separado y la comparación con planes es descriptiva. La plataforma no depende de nubes, mapas externos, APIs privadas ni scraping para este flujo.

Centraliza, según el soporte real del código:

- nutrición y gasto energético;
- peso y composición corporal;
- laboratorios y marcadores;
- alimentos y recetas;
- rutinas, sesiones, progreso y actividades;
- archivos originales, imports, exports y backups;
- sincronización con clientes companion mediante contratos versionados.

No está diseñado como SaaS público. El despliegue esperado es local o mediante una red/VPN privada administrada por el usuario.

## Diferenciador

El valor principal es un pipeline trazable, no solo el dashboard:

```text
capturar o recibir
  → normalizar a un contrato estándar
  → validar
  → persistir con ownership
  → analizar
  → exportar o sincronizar
  → reimportar sin perder el contrato
```

En entrenamiento, la dirección de producto es:

```text
planear → exportar/entregar → ejecutar → importar resultado → comparar → ajustar
```

El cliente móvil materializa ese ciclo con planificación offline por identidad estable, packages versionados e inmutables durante una ejecución, y reconciliación idempotente hacia una única sesión histórica. El servidor conserva la autoridad y el aislamiento por usuario; la caché local nunca crea un segundo contrato ni un segundo motor de sesiones.

## Principios permanentes

1. Cada usuario tiene login y datos separados.
2. Todo registro sensible y archivo pertenece a un `user_id` efectivo del servidor.
3. Los archivos originales y SHA256 permiten rastrear el origen cuando el flujo lo requiere.
4. Las capturas manuales y adaptadores producen JSON estándar antes de persistir dominio.
5. Los JSON Schemas versionados son el contrato público importable/exportable.
6. Los aliases externos nunca contaminan el JSON estándar.
7. Preview, detección y generación asistida permanecen separados de la escritura.
8. Import/export debe declarar dedupe, update y pérdida de información.
9. Los formatos y dispositivos no soportados se declaran honestamente; no se fabrican datos.
10. Git solo contiene código, documentación y fixtures ficticias.

Las reglas ejecutables de estos principios viven en `../AGENTS.md`, `schemas/AGENTS.md` y `project-rules/`.

## Plataforma técnica

- Backend: Python y Flask.
- UI: Flask/Jinja/CSS con mejora progresiva.
- Persistencia: SQLAlchemy/Flask-SQLAlchemy y MariaDB.
- Migraciones: Alembic/Flask-Migrate.
- Validación: JSON Schema.
- Ejecución: Docker Compose; SQLite se usa en pruebas donde corresponde.
- Archivos: storage local por usuario para raw, generated, exports y backups.
- Cliente móvil: Kotlin, Jetpack Compose, Room, WorkManager y OkHttp en `../android/`.

## Política permanente de entornos

El entorno **local** vive exclusivamente en `C:\Users\donbu\Documents\GitHub\health-tracker`. Usa un solo checkout, una sola MariaDB descartable, un solo proyecto Docker Compose, el puerto web `8000` y un único `.env` local ignorado por Git. Desarrollo, pruebas automáticas y QA manual cambian de rama feature dentro de ese mismo checkout; un número de versión no crea otro entorno.

El entorno **de producción** vive en `~/health-tracker` en el NAS. Contiene datos reales y recibe únicamente `master` estable o releases aprobadas, con backup antes de migraciones. Nunca se usa para experimentos o QA.

No se crean worktrees, stacks Docker paralelos, bases de datos, puertos o archivos de entorno por versión salvo petición explícita del usuario.

El cliente móvil cubre planificación, ejecución, historial, progreso, registro diario de salud e importación Health Connect de solo lectura sin duplicar dominio: las rutinas editables publican versiones inmutables, la agenda usa planned workouts, la ejecución usa Companion Delivery/Mobile Sync y salud reutiliza peso, nutrición, catálogo y energía canónicos mediante endpoints owner-only.

La web separa el análisis longitudinal en **Resumen** (`/dashboard`) de la operación cotidiana en **Hoy** (`/today`). Ambos consumen servicios owner-only existentes o read models internos; esta separación no crea un contrato móvil ni obliga a Android a consumir tendencias web.

Alpha 1.6 añade una base local experimental para fuentes externas y BLE: registro/deduplicación, diagnóstico Health Connect de báscula, asociación, descubrimiento GATT, captura privada/replay y evidencia de protocolo. No amplía el dominio servidor ni afirma soporte S400: ningún valor BLE llega al dominio de salud mientras el mapper permanezca deshabilitado.

La estructura real del código manda sobre diagramas o rutas narrativas antiguas. Consulta `architecture/OVERVIEW.md` y el árbol del repositorio en vez de copiar una estructura sugerida a nuevas tareas.

Beta 1.1 incorpora una interfaz AI segura sobre servicios reales: provider fake y adapter cloud desacoplados, consentimiento remoto por usuario, conversaciones acotadas, tools read-only owner-only, evidencia, portabilidad y drafts de peso/comida con confirmación explícita e idempotente. El modelo no recibe acceso a SQL/shell/filesystem y nunca escribe directamente ni diagnostica. La frontera y limitaciones están en [AI_FOUNDATION.md](AI_FOUNDATION.md).

El Adaptive AI Capability Engine organiza esa interfaz mediante manifests
tipados y provider-neutral en Python. Cada dominio declara entidades, catálogo
de métricas, semántica de ausencia, periodos, comparaciones, lecturas y acciones.
Un `AIIntentSpec` validado se resuelve a un plan determinista con el subconjunto
exacto de tools antes de consultar al proveedor. El catálogo cubre Resumen,
Energía, Nutrición, Cuerpo, Actividad, Entrenamiento, Metas y Datos; incorporar
un dominio nuevo no exige multiplicar plantillas estáticas.

Los 41 IDs de AI Templates 2.0 permanecen estables como presets/aliases para
deep links y compatibilidad. El catálogo principal se genera dinámicamente y
distingue capacidad soportada de disponibilidad de datos owner-only; sus
recomendaciones son determinísticas y no inicializan al proveedor.

Los periodos admitidos son hoy, 7, 30 y 90 días según cada capacidad. Los deep
links contextuales transportan intención, dominio, métricas y periodo
allowlisted, nunca cifras de salud ni el prompt editable; los enlaces legacy por
ID siguen funcionando. Elegir una capacidad solo prepara texto del lado
servidor: crear la conversación tampoco envía el mensaje, y el usuario debe
pulsar Enviar. Las acciones de comida y medición corporal continúan como draft →
preview → confirmación explícita; las correcciones corporales reutilizan el
patch oficial owner-only. Ninguna capacidad escribe silenciosamente.

Los manifests se validan contra metadata reusable de las tools y read models
reales. Patrones de comida y progreso por ejercicio ya son lecturas agregadas
owner-only; las cargas incompatibles no se comparan y la ausencia no se vuelve
cero. Consentimiento remoto, límites de contexto, procedencia, tratamiento de
texto externo como datos y prohibición de diagnóstico permanecen en la capa AI
común. Las plantillas personalizadas por usuario son una posibilidad futura, no
una capacidad actual: requerirán un contrato separado de validación, ownership,
límites y seguridad, sin convertir prompts de usuario en instrucciones de
sistema.

AI Operator añade un contrato `ActionCapability` propiedad del dominio y un
`AIPlanSpec` server-side. Siete acciones reales cubren registro de comida,
creación/corrección corporal, creación/corrección de entrenamiento planificado y
creación/actualización de metas. Una petición puede producir varios pasos,
persistidos como `AIActionDraft` agrupados por metadata, con preview, edición
local, confirmación/rechazo individual, confirmar todo y retry idempotente de
fallos parciales. `PROPOSE_CHANGES` lee datos actuales antes de preparar cambios.

El registro de capabilities alimenta el resolver, las definiciones del provider
y las acciones rápidas de `/ai`; por eso un módulo puede añadir una acción a su
manifest sin añadir ramas de dominio al orquestador central. Las escrituras sólo
ocurren tras confirmación explícita mediante el handler oficial owner-only. No
hay delete genérico, service names elegidos por browser/modelo ni SQL directo.
Los contextos desde páginas de dominio usan tokens firmados ligados a owner y no
incluyen valores de salud en la URL.

## Capacidades de producto

### Identidad y archivos

El sistema ofrece autenticación web, administración básica, dispositivos/API, uploads con SHA256, estados de importación y aislamiento owner-only.

### Bienestar y salud

Incluye contratos y flujos para peso/composición, nutrición, energía, alimentos, recetas y laboratorios. La aplicación conserva y muestra datos; no sustituye evaluación médica ni debe emitir diagnósticos.

Android Alpha 1.5 registra offline peso/composición ya soportada, comidas manuales, alimentos personalizados y pasos, e importa de Health Connect peso, grasa compatible, pasos diarios agregados y nutrición representable. Room conserva procedencia y ledger aislados por cuenta; la reconciliación usa IDs de origen, UUID, `client_event_id`, idempotencia, revisiones y Changes tokens. No se crean objetivos inexistentes, no se equipara masa magra con masa muscular ni masa de agua con porcentaje, y no se fusionan fuentes de pasos potencialmente solapadas.

### Entrenamiento

Las rutinas son versionables y las sesiones realizadas conservan la versión histórica del plan. El sistema registra sets, carga, reps, RIR/RPE y otros campos soportados, compara plan vs realidad y calcula métricas descriptivas de progreso.

Las cargas avanzadas mantienen `weight_kg` como total normalizado compatible y usan detalle opcional versionado. Consulta las reglas de entrenamiento antes de cambiar ese contrato.

### Importación

Los JSON estándar pasan por su schema e importador oficial. Los JSON no estándar pueden usar detección, mapping y generación canónica en preview. FIT/GPX/TCX/CSV soportados pasan por parsers que generan JSON estándar antes del commit confirmado.

### Exportación y portabilidad

Los exporters declaran capability, warnings y pérdidas. Los artefactos persistidos guardan owner, formato, tamaño y SHA256. El export de cuenta y el backup ZIP agregan portabilidad sin permitir que IDs o paths del archivo elijan el usuario destino.

### API y companion

`/api/v1` usa Bearer independiente de la sesión web, UUID públicos y contratos versionados. Mobile Sync y Companion backend soportan los dominios y operaciones expresamente documentados. El cliente Android ejecuta el protocolo desde el teléfono con cache offline, recuperación de process death, cola durable e idempotencia; la lectura Health Connect es un adaptador local explícito y no implica una aplicación de reloj, escritura de datos ni integración directa con fabricantes.

Desde Alpha 1.2 el cliente también consulta historial paginado y progreso descriptivo por periodo/ejercicio desde Room. Las métricas y mejores marcas son lecturas deterministas sobre `TrainingSession`; no constituyen recomendaciones automáticas, IA ni gamificación. Los modos de carga incompatibles producen ausencia explícita en vez de una comparación fabricada.

## Seguridad y privacidad de producto

- Login incluso en red local.
- Exposición pública directa fuera del alcance; usar red privada/VPN o infraestructura revisada.
- No registrar credenciales, tokens, payloads clínicos ni contenido sensible completo.
- Descargas y consultas filtran por owner; recursos ajenos responden sin revelar existencia.
- Backups y exports no incluyen contraseñas, sesiones ni secretos.
- Fixtures, ejemplos y QA usan identidades y datos ficticios.

## Fuera de alcance actual

Salvo evidencia nueva en código y pruebas, no considerar implementados:

- APK firmado/publicado, distribución Play Store o app de reloj;
- bridge con reloj o Bluetooth de entrenamiento; la única base BLE actual es investigación local S400 sin métricas habilitadas;
- telemetría continua;
- FIT binario de salida;
- APIs privadas o scraping de fabricantes;
- OCR/FHIR o interpretación clínica;
- operación como SaaS público.

El trabajo futuro vive en `ROADMAP.md`, no en instrucciones operativas.

## Portabilidad selectiva

Alpha 1.7 define `health-tracker-portable-v1` como contrato de migración de usuario entre instalaciones. Es distinto de exportadores de conveniencia, backup/restore administrativo y Mobile Sync. Conserva UUID públicos sólo cuando es seguro, remapea colisiones, deriva el owner del destino y excluye cachés/estado técnico recalculable. Los contratos públicos viven en `schemas/portable_*.schema.json`; el diseño se documenta en [ALPHA_1_7_DATA_PORTABILITY.md](ALPHA_1_7_DATA_PORTABILITY.md).

Alpha 1.8 incorpora engagement no clínico. El servidor persiste objetivos y reglas; Android agenda avisos locales sin push y conserva schedule/permiso/dedupe como estado técnico no portable. Adherencia describe cumplimiento contra un objetivo explícito, nunca sustituye métricas canónicas, diagnóstico o recomendación. Véase [ALPHA_1_8_GOALS_REMINDERS.md](ALPHA_1_8_GOALS_REMINDERS.md).

## Fuentes de verdad

1. Schemas para contratos JSON públicos.
2. Pruebas para comportamiento vigente.
3. Reglas en `project-rules/` para invariantes de dominio.
4. Código para implementación actual.
5. Este documento para visión y límites estables.
6. `history/` para trazabilidad, nunca para redefinir el presente.

Consulta `DOCUMENTATION_INDEX.md` para el mapa completo por dominio.

## Freeze Android Beta 1

Android `2.0.0-beta01` es una estabilización de Alpha 2.0, no una nueva fase funcional. Room 10, Alembic 0036, contratos, cinco pestañas y límites de producto permanecen congelados. Los gates conectados y QA físico se documentan como pendientes cuando no se han ejecutado; consulta [BETA_1_ANDROID_STABILIZATION.md](BETA_1_ANDROID_STABILIZATION.md).

Alpha 1.9 incorpora documentación médica privada sin convertir Health Tracker en herramienta clínica: conserva estudios, resultados y originales, compara únicamente unidades/métodos técnicamente compatibles y mantiene rangos/estados como procedencia del informe. OCR clínico, diagnóstico, recomendaciones, FHIR obligatorio y rangos universales siguen fuera de los límites del producto; la capa AI general no altera esa restricción. Véase [ALPHA_1_9_MEDICAL_RECORDS.md](ALPHA_1_9_MEDICAL_RECORDS.md).
