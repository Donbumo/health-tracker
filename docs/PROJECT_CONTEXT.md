# Contexto del proyecto: Plataforma self-hosted de salud, nutrición, entrenamiento y dispositivos

## Estado verificado: Mobile Sync Foundation

La Fase 7B añade `PlannedWorkout`, identidad pública/revisión para `TrainingSession`, cambios incrementales, estado de cursor por dispositivo e idempotencia persistente. API Sync 1.0 escribe únicamente planned/completed workouts. Otros dominios permanecen fuera de push.

No hay APK ni app de reloj. La rutina activa continúa seleccionándose temporalmente por `most_recent_plan_active_version`.

## Alpha 0.7 publicada / Fase 7C activa

Alpha 0.7 está integrada en el merge `b0b6bb2`, tag `alpha-0.7-mobile-sync`, con migración head `20260714_0023`. Incluye planned workouts, completed workout upload, bootstrap/pull/push/status, conflictos por revisión, tombstones, cursor por dispositivo, idempotencia, cleanup CLI y UI homelab mínima. Suites local/Docker y concurrencia MariaDB pasaron; la cobertura Flask/HTML existe y el sign-off visual humano final quedó pendiente operativo.

La rama `feature/phase-7c-companion-delivery` construye Alpha 0.8 sobre esa base: perfil negociado por dispositivo, package 1.0 inmutable, delivery persistente, ACK/start/abort/fail, checkpoints pequeños y completion que reutiliza `TrainingSession` y Mobile Sync. No implementa APK, reloj, Bluetooth, telemetría continua, FIT output ni vendors.

Estado verificado de Alpha 0.8 en desarrollo: migraciones aditivas `20260714_0024` y `20260714_0025`, single head `0025`, ciclo aislado SQLite reversible y MariaDB `db check` limpio. Suite local `535 passed, 2 skipped, 1 warning`; Docker `536 passed, 1 skipped, 1 warning`. QA HTTP y tema oscuro en seis anchos pasaron; el sign-off visual de tema claro continúa pendiente.

Limitaciones reales: rate limiter por proceso; tombstones/cursores obsoletos report-only; sin CRDT ni last-write-wins general; activity/route/body/wellness/labs sin sync write; `watch_bridge=false`, `bluetooth_bridge=false`, `continuous_telemetry=false` y `fit_output=false`; clave API independiente recomendada para homelab y obligatoria antes de exposición pública; incompatibilidad histórica SQLite de migración `0015` aún documentada.

## Alpha 0.6 / Fase 7A

Base `/api/v1` con access firmado corto, refresh opaco hash-only rotatorio, reuse detection, dispositivos revocables, UUID públicos persistidos, JSON/request ID, rate limiting QA, CORS allowlist, `/me`, bootstrap y rutina activa read-only. Migraciones aditivas `20260713_0021` y `20260713_0022`. Sync offline, conflictos, tombstones, planned workouts, APK y reloj siguen planificados, no implementados.

## Alpha 0.6.1 / Web UI Homelab

La capa web conserva Flask/Jinja/CSS y agrega un shell responsive con navegación agrupada, dashboard orientado al día, tema del sistema, accesibilidad base, estado owner-only en `/account/system` y gestión owner-only de dispositivos en `/account/devices`. No agrega modelos ni migraciones y no cambia los contratos de API o datos. El estado homelab no expone secretos, logs ni paths internos.

## Visión general

El proyecto es una aplicación web self-hosted, multiusuario y privada, pensada para ejecutarse localmente o mediante VPN.

El objetivo es centralizar:

- Nutrición diaria.
- Gasto energético.
- Pesajes.
- Composición corporal.
- Estudios médicos.
- Rutinas.
- Entrenamientos.
- Resultados de dispositivos.
- Capturas manuales.
- Importadores y exportadores de archivos.

El backend principal es Python con Flask. La base de datos es MariaDB. El proyecto debe poder levantarse con Docker Compose.

El repositorio de GitHub solo debe contener código, documentación, schemas, ejemplos ficticios, parsers, importadores y exportadores. Los datos reales deben vivir localmente en `/data` o en volúmenes Docker ignorados por Git.

La aplicación debe permitir que varios usuarios, por ejemplo miembros de una familia, tengan su propio login y sus propios datos separados. No está pensada como SaaS público, sino como una plataforma privada instalable y controlada por el usuario.

---

## Estado actual del proyecto

Actualización verificada: 2026-07-12.

La rama `feature/phase-6b-full-backup-recovery`, basada en el tag `alpha-0.4-exporters-complete` (`f36ae9d`), agrega Alpha 0.5: backup ZIP 1.0 con manifest, export de cuenta, raw y generated; preview seguro en staging; confirmación firmada; restore coordinado con compensación; dedupe; auditoría y reconciliación. No requiere modelo ni migración nueva: reutiliza `ExportRecord`, `UploadedFile` e `ImportRun`.

Línea base previa: `441 passed`. Resultado final: `465 passed` local y `464 passed, 1 skipped` en Docker.

El estado ejecutable actual incluye la Fase 5 / Alpha 0.3 integrada en `2d617ed`. La rama `feature/phase-6-exporters-complete` implementa el cierre de exportadores de Alpha 0.4 con auditoría persistente, storage seguro, formatos Activity/Route y entrenamiento avanzado. Para cualquier tarea nueva, usar también `docs/AI_WORK_CONTEXT.md`, las reglas en `docs/project-rules/` y el estado real del código.

Estado verificado en `master` / `docs/refresh-ai-context`:

- Commit documental integrado en `master`: `9a5d474`.
- Las tareas posteriores deben obtener su base real desde el `master` vigente.
- Último merge conocido: `Merge branch 'feature/standard-json-generator-medical-lab'`.
- Línea base local verificada anterior: `250 passed`.
- Línea base local posterior al cierre de Fase 5B e importación confirmada: `304 passed`.
- Rama de cierre QA backend `feature/overnight-backend-qa-closure`: agrega cobertura automatizada para `daily_energy`, `training_plan`, `completed_workout` y `medical_lab`, más fixtures ficticias en `examples/qa/standard-import/`.
- El proyecto conserva Flask, Flask-SQLAlchemy, Flask-Migrate, MariaDB y Docker Compose.
- Los datos reales siguen fuera de Git y deben vivir en `/data` o volúmenes ignorados.

Módulos actualmente implementados o con núcleo funcional:

- Auth, login/logout y admin básico.
- Uploads con SHA256, estado, tipo detectado y aislamiento por `user_id`.
- Dashboard diario y QA web.
- Healthcheck, diagnóstico admin y export completo de usuario.
- Import-preview dry-run del export completo.
- Restore completo de usuario desde `/account/restore`, con preview, confirmación firmada, remapeo de IDs internos, commit atómico y auditoría saneada.
- Entrenamiento: rutinas versionables, sesiones, progreso, sobrecarga, aliases de ejercicios e imports/exports base.
- Nutrición diaria, energía diaria y balance.
- Peso y composición corporal.
- Productos de alimento, recetas y bundles de recetas.
- Laboratorios médicos con reportes, marcadores, historial, importación y exportación.
- Fase 5B cerrada para los targets finales: detección estricta de schemas, asistente universal read-only, generación estándar read-only y orquestación de preview.
- Fase posterior a 5B: importación estándar confirmada para QA desde web con plan `insert/update/skip/conflict/invalid` y confirmación explícita.
- Ayudas locales de prompt para IA en `/imports/standard`: catálogo read-only para copiar prompts/plantillas JSON de los nueve targets soportados, sin integrar API externa, sin enviar datos fuera de la app y sin almacenar contenido copiado.
- Portabilidad de cuenta: `/account/data`, `/account/export.json`, `/account/restore` y `/account/restore/confirm`. El restore ignora identidad exportada, no restaura binarios, omite derivados como `daily_balances` y no implementa borrado ni ZIP. Ver `docs/ACCOUNT_RESTORE.md`, `docs/DATA_PORTABILITY.md` y `docs/project-rules/account-restore.md` para el contrato operativo.
- Rama `feature/phase-5-real-importers`: importadores reales para FIT, GPX, TCX, CSV de pesajes, CSV de energía diaria y JSON interno dentro del pipeline común; agrega `Activity`/`Route`, schemas `activity`/`route`, preview/confirmación firmada, auditoría `ImportRun`, UI de actividades/rutas y export/restore de esas secciones. FIT binario vendor-neutral usa `fitdecode==0.10.0`.
- Validación local del bloque `feature/backend-complete-roundtrip`: `399 passed`.

Estado real de Fase 5B verificado:

- `SchemaDetector` reconoce schemas oficiales internos.
- `UniversalJsonImportAssistant` detecta candidatos y aliases.
- `AssistedImportService` orquesta preview read-only.
- `StandardJsonGenerator` genera y valida JSON estándar en memoria.
- Estos servicios no escriben DB, no guardan archivos y no ejecutan importación real.
- La escritura real posterior se hace mediante `StandardImportExecutor`, separado del preview.
- La confirmación web se firma contra usuario, target, payload y plan; tokens reutilizados, vencidos o de otro usuario deben rechazarse.
- El commit confirmado debe ser atómico y hacer rollback si falla un elemento durante la escritura.
- `recipe_bundle` se planea por receta embebida y conserva `recipe_index` para trazabilidad.
- La rama `feature/overnight-backend-qa-closure` endurece QA de targets pendientes y conserva errores detallados en commits bloqueados por documentos inválidos/conflictivos.
- La rama `feature/import-audit-persistence` agrega `ImportRun` e `ImportAuditService` para auditar intentos confirmados sin guardar payloads crudos ni datos sensibles.
- La rama `release/alpha-teammate-ready` prepara una alpha privada por LAN/VPN para un companero real: onboarding web sin tabla nueva, pagina de privacidad, version visible `Alpha 0.1`, documentacion operativa y pruebas de flujo web basico.

Dominios actualmente soportados por `SUPPORTED_TARGETS` del módulo `standard_json_generator.py`:

| `target_type` | `schema_name` |
| --- | --- |
| `weigh_in_batch` | `weigh_in` |
| `food_products` | `food_product` |
| `daily_energy` | `daily_energy` |
| `daily_nutrition` | `daily_nutrition` |
| `completed_workout` | `completed_workout` |
| `medical_lab` | `medical_lab` |
| `training_plan` | `training_plan` |
| `recipe` | `recipe` |
| `recipe_bundle` | `recipe_bundle` |

Bloques próximos previstos:

1. Definir pruning operativo de `ImportRun` si se requiere retención limitada.
2. Ampliar contratos de update seguro solo donde existan claves naturales o IDs explícitos verificables.
3. Endurecer equivalencia semántica del round-trip si aparecen nuevos dominios o se agregan binarios.
4. Evaluar cifrado de backup únicamente con infraestructura y administración de claves revisadas; ZIP 1.0 no está cifrado.

No presentar APK, app de reloj, APIs privadas Magene/OnelapFit, OCR, FHIR o API REST pública como implementados. Siguen siendo planes, stubs o estructura futura salvo que el código de una rama posterior demuestre lo contrario. FIT/GPX/TCX se soportan como importación de archivos exportados en la rama de Fase 5, no como sincronización directa.

Las subsecciones siguientes contienen contexto histórico útil. Si contradicen el estado verificado anterior, manda el estado verificado, los schemas y las pruebas actuales.

### Estado histórico anterior: Fase 6 inicial completada

Se implementó:

- Interfaz común de exportadores.
- Rutinas en JSON y CSV.
- Sesiones en JSON, CSV y HTML imprimible.
- Importadores separados para `training_plan` y `completed_workout`.
- Conservación de archivos originales.
- SHA256.
- Deduplicación.
- Aislamiento por usuario.
- Stubs documentados para FIT, GPX y Magene.
- Advertencias visibles sobre pérdida de información en CSV.
- TODO documentado para un futuro modelo `ExportRecord`.

No se añadieron tablas ni migraciones durante esa fase.

### Verificaciones históricas de la Fase 6 inicial

- Pruebas locales: 29 passed.
- Pruebas en Docker: 29 passed.
- `compileall`: correcto.
- `flask db check` local: sin cambios pendientes.
- `flask db check` con MariaDB: sin cambios pendientes.
- `docker compose config`: válido.
- MariaDB: saludable.
- Login real en `localhost:8000`: correcto.
- Exportaciones HTTP JSON/CSV/HTML: cubiertas por pruebas.
- Aislamiento por usuario en exportaciones: cubierto por pruebas.

### Archivos tocados recientemente

- `README.md`
- `training_plans.py`
- `workout_sessions.py`
- `sessions`

### Evolución actual de Fase 6

- `ExportRecord` reemplaza el TODO histórico de auditoría de exports.
- `/exports` ofrece preview, generación confirmada, historial, descarga y borrado controlado owner-only.
- Activity/Route exportan JSON, CSV, GPX y TCX con round-trip probado.
- TrainingPlan exporta versiones activas/históricas en JSON/CSV/HTML/PDF; ZWO/ERG/MRC solo cuando capability confirma potencia explícita.
- TrainingSession exporta JSON/CSV/HTML/PDF.
- FIT output no está implementado y se declara unsupported experimental.
- Validación de la rama: `441 passed` local; `440 passed, 1 skipped` en Docker; migración MariaDB en head `20260712_0020` y `db check` limpio.

### Pendientes técnicos cercanos

- Mantener exportadores como adaptadores separados, no como un exportador universal monolítico.
- Mantener la importación FIT/GPX/TCX documentada como flujo por archivo exportado; Magene/OnelapFit solo entra si exporta FIT/GPX/TCX estándar, sin APIs privadas.
- No generar migraciones si no hay cambios reales en modelos.
- Mantener pruebas de aislamiento por usuario en importación/exportación.
- Mejorar documentación de uso HTTP/curl autenticado cuando el entorno lo permita.

---

## Filosofía principal

Todo dato debe entrar por un pipeline común:

```text
Archivo subido
  o
Captura manual
  o
Sincronización desde app/dispositivo
        ↓
Conversor / generador
        ↓
Archivo estándar interno
        ↓
Validación contra JSON Schema
        ↓
Importación a MariaDB
        ↓
Dashboard / análisis / reportes
```

La aplicación no debe depender directamente del formato original de cada dispositivo o app. Debe tener formatos internos estandarizados y versionados.

Ejemplo con archivo FIT:

```text
.fit de Magene/Garmin/Huawei
        ↓
fit_importer.py
        ↓
activity_standard.json
        ↓
validación
        ↓
MariaDB
```

Ejemplo de captura manual:

```text
Formulario web de peso
        ↓
generated_weigh_in.json
        ↓
validación
        ↓
importación
        ↓
dashboard
```

---

## Principios clave

1. El sistema debe ser multiusuario privado.
2. Cada usuario debe tener login propio.
3. Todo registro debe estar asociado a `user_id`.
4. Todo dato importado o capturado debe poder rastrearse a un archivo fuente.
5. Las capturas manuales también deben generar archivos JSON estándar.
6. Los archivos originales deben conservarse localmente.
7. Los archivos procesados/generados deben poder reimportarse.
8. Los formatos internos deben estar documentados mediante JSON Schema.
9. El sistema debe permitir exportar datos y rutinas a otros formatos.
10. El sistema debe permitir importar resultados de vuelta para comparar plan vs realidad.
11. GitHub no debe contener información médica, corporal, alimentaria o personal real.
12. Los datos personales deben vivir en `/data` o volúmenes Docker ignorados por Git.
13. Toda consulta sensible debe filtrar por usuario.
14. Las rutas de admin deben validar rol.
15. Las pruebas deben cubrir aislamiento cuando se trabaje con datos de usuarios.

---

## Stack técnico base

- Backend: Python.
- Framework web: Flask.
- Base de datos: MariaDB.
- ORM: SQLAlchemy / Flask-SQLAlchemy.
- Migraciones: Flask-Migrate / Alembic.
- Contenedores: Dockerfile + Docker Compose.
- Validación: JSON Schema.
- Frontend inicial: templates Flask/Jinja + Bootstrap o similar.
- Futuro frontend avanzado: API REST + app móvil / PWA.
- Parsing `.fit`: el import actual usa `fitdecode`; si en el futuro se requiere escritura/export FIT, evaluar librería compatible para esa necesidad específica.
- Exportaciones: JSON, CSV, HTML imprimible; PDF/FIT/GPX/ZWO/ERG/MRC como fases posteriores.

---

## Módulos principales

### 1. Autenticación y usuarios

El sistema debe incluir:

- Login.
- Logout.
- Usuarios múltiples.
- Roles básicos.
- Admin inicial desde `.env`.
- Separación de datos por usuario.

Roles iniciales:

```text
admin:
  - Puede crear usuarios.
  - Puede ver todos los datos.
  - Puede gestionar importaciones.
  - Puede acceder a paneles de otros usuarios.

user:
  - Solo puede ver y modificar sus propios datos.

viewer:
  - Solo lectura, opcional para futuro.
```

Tablas relacionadas:

```text
users
user_profiles
user_settings
```

---

### 2. Sistema de archivos e importaciones

El sistema debe aceptar archivos externos como:

```text
.fit
.json
.gpx
.tcx
.csv
.pdf
```

No todos deben procesarse desde el inicio. Algunos pueden guardarse como documento para procesar después.

Estructura local sugerida:

```text
data/
├── uploads/
│   ├── raw/
│   │   └── user_<id>/
│   ├── processed/
│   │   └── user_<id>/
│   └── generated/
│       └── user_<id>/
├── exports/
│   └── user_<id>/
└── backups/
```

Tabla de archivos:

```text
uploaded_files
├── id
├── user_id
├── original_filename
├── stored_filename
├── stored_path
├── file_extension
├── source_type
├── detected_type
├── sha256
├── import_status
├── error_message
├── created_at
```

`source_type` puede ser:

```text
uploaded
manual_generated
converted
system_generated
synced_from_device
```

`detected_type` puede ser:

```text
activity
daily_nutrition
daily_energy
weigh_in
medical_lab
training_plan
planned_workout
completed_workout
route
unknown
```

---

### 3. Captura manual con generación de archivo

La app no solo debe permitir subir archivos. También debe permitir crear registros manuales desde formularios web.

Cada captura manual debe generar un archivo JSON estándar y guardarlo en:

```text
data/uploads/generated/user_<id>/
```

Ejemplos de capturas manuales:

- Dieta diaria.
- Comida individual.
- Gasto energético del día.
- Peso.
- Composición corporal.
- Entrenamiento realizado.
- Rutina planeada.
- Estudios médicos.
- Marcadores de laboratorio.
- Notas de salud.
- Sueño.
- Síntomas.
- Presión arterial.
- Glucosa.

Flujo:

```text
Formulario web
        ↓
file_generator.py
        ↓
archivo JSON estándar
        ↓
validators.py
        ↓
import_service.py
        ↓
MariaDB
```

---

## Dominios de datos

### 4. Nutrición diaria

Debe permitir registrar:

- Desayuno.
- Comida.
- Cena.
- Snacks/extras.
- Totales diarios.
- Calorías.
- Proteína.
- Grasa.
- Carbohidratos netos.
- Carbohidratos totales.
- Fibra.
- Azúcares.
- Sodio.
- Micronutrientes cuando estén disponibles.

Debe soportar:

- Captura manual.
- Importación desde JSON.
- Recetas guardadas.
- Alimentos reutilizables.
- Alacena virtual.
- Cálculo de totales por día.
- Exportación del día completo.

Formato interno:

```text
daily_nutrition.schema.json
```

---

### 5. Gasto energético diario

Debe almacenar:

- Calorías totales.
- Calorías activas.
- Calorías de reposo.
- Pasos.
- Distancia.
- Fuente del dato.
- Fecha.
- Datos crudos del reloj/app.

Formato interno:

```text
daily_energy.schema.json
```

Debe poder cruzarse contra nutrición para calcular:

```text
balance = calorías ingeridas - calorías gastadas
```

---

### 6. Pesajes y composición corporal

Debe permitir registrar:

- Peso.
- Porcentaje de grasa.
- Masa muscular.
- Agua corporal.
- Grasa visceral.
- BMR estimado.
- BMI.
- Fuente.
- Fecha.

Fuentes posibles:

- Captura manual.
- Báscula inteligente.
- JSON exportado.
- CSV.
- App externa.

Formato interno:

```text
weigh_in.schema.json
```

---

### 7. Estudios médicos y análisis clínicos

Debe permitir almacenar:

- Archivo original del estudio.
- Laboratorio.
- Fecha.
- Marcadores individuales.
- Valor.
- Unidad.
- Rango de referencia.
- Estado: bajo, normal, alto.
- Notas.
- Médico o fuente, opcional.

Ejemplos:

```text
glucosa
insulina
HbA1c
colesterol total
LDL
HDL
triglicéridos
TSH
T3
T4
creatinina
ALT
AST
vitamina D
B12
ferritina
```

Formato interno:

```text
medical_lab.schema.json
```

A futuro se puede evaluar compatibilidad con FHIR, pero no debe ser requisito del MVP.

---

## Módulo de entrenamiento

### 8. Rutinas como archivos versionables

Las rutinas no deben existir solo como registros manuales. Deben poder:

- Crearse manualmente desde la web.
- Importarse desde `.json`.
- Editarse desde la web.
- Guardarse como nuevas versiones.
- Exportarse nuevamente a `.json`.
- Compararse entre versiones.
- Activarse/desactivarse por usuario.

Concepto:

```text
training_plan.json
        ↓
importar
        ↓
editar
        ↓
guardar v2
        ↓
exportar
```

Ejemplo de versiones:

```text
Full Body Frecuencia 3 v1
Full Body Frecuencia 3 v2
Full Body Frecuencia 3 v3
```

Debe registrarse:

- Qué cambió.
- Cuándo cambió.
- Quién lo cambió.
- Motivo del cambio.
- Qué versión estaba activa cuando se realizó una sesión.

Tablas sugeridas:

```text
training_plans
training_plan_versions
training_plan_days
training_plan_exercises
exercises
```

---

### 9. Sesiones de entrenamiento realizadas

Debe distinguirse entre:

```text
Rutina planeada ≠ entrenamiento realizado
```

Rutina planeada:

```text
Remo en T
3 series
8-12 reps
RIR 2
```

Sesión real:

```text
Remo en T
45 kg x 10
45 kg x 9
45 kg x 8
RIR 1-2
```

La app debe permitir registrar:

- Ejercicio.
- Series.
- Peso.
- Repeticiones.
- RIR.
- RPE.
- Descanso.
- Notas.
- Duración.
- Frecuencia cardiaca, si viene del reloj.
- Calorías, si vienen del reloj.
- Fuente del dato.

Tablas sugeridas:

```text
training_sessions
training_session_exercises
training_sets
```

Formato interno:

```text
completed_workout.schema.json
```

---

### 10. Sobrecarga progresiva

El sistema debe analizar progreso por ejercicio, sesión, semana y rutina.

Métricas:

```text
volumen = peso x reps x series
reps totales
peso máximo usado
mejor set
estimación de 1RM, opcional
RIR/RPE
cumplimiento del rango objetivo
fatiga entre series
progreso contra sesión anterior
```

El sistema debe poder sugerir:

```text
subir peso
mantener peso
bajar peso
subir reps
mantener ejercicio
cambiar ejercicio
reducir volumen
marcar estancamiento
```

Ejemplo de regla:

```text
Si el rango es 8-12 reps:
- Si se completa el rango alto con buen RIR → sugerir subir carga.
- Si queda dentro del rango → mantener.
- Si cae por debajo del mínimo → revisar fatiga o bajar carga.
- Si no progresa en varias sesiones → sugerir ajuste.
```

---

### 11. Preferencias de entrenamiento del usuario

Para la programación personal del usuario, considerar:

- El día fuerte de la semana debe ser el tercer día.
- Si el usuario llega cansado, ese día fuerte queda al final de la semana.
- Si llega con energía, puede agregar un día extra después.
- Priorizar ejercicios estables y progresables.
- Evitar que técnica, equilibrio o coordinación sean el límite principal cuando el objetivo es hipertrofia/progresión.
- Priorizar máquinas, Smith, poleas, apoyos de pecho, prensa/hack, jalones/remos guiados.
- Mantener ejercicios libres o técnicos solo si aportan motivación, transferencia o el usuario los domina sin dolor ni pérdida clara de ejecución.
- El usuario quiere ajustes pequeños a su rutina, no rehacerla completa.
- Le interesa priorizar/probar remo en T porque le resulta más fácil y estable que el remo sentado.
- Priorizar remo en T con pecho apoyado como remo principal.
- Mantener remo sentado como variante secundaria o alternada.
- El peso muerto rumano libre le parece técnicamente complicado.
- Para reemplazarlo o simplificarlo, priorizar Smith RDL + curl femoral sentado.
- Volumen base para cadena posterior: 2 series de Smith RDL + 2 series de curl femoral sentado.
- En día fuerte o si llega bien recuperado: 3 series de Smith RDL + 3 series de curl femoral sentado.
- Mantener Smith RDL técnico/moderado y curl femoral sentado como estímulo principal estable para femoral.

---

### 12. Plan vs realidad

El sistema debe comparar lo planeado contra lo realizado.

Para gym:

```text
Ejercicio planeado vs ejercicio realizado
Series planeadas vs series realizadas
Reps objetivo vs reps reales
Peso sugerido vs peso usado
RIR objetivo vs RIR real
Descanso objetivo vs descanso real
```

Para bici:

```text
Intervalos planeados vs intervalos realizados
Potencia objetivo vs potencia real
FC objetivo vs FC real
Cadencia objetivo vs cadencia real
Duración objetivo vs duración real
Ruta planeada vs ruta recorrida
```

Resultado:

```text
cumplimiento %
desviación
progreso
fatiga
recomendación siguiente
```

---

## Motor de intercambio de entrenamientos

### 13. Training Interchange Engine

Debe existir una capa encargada de importar/exportar rutinas y resultados entre la app y dispositivos externos.

Nombre conceptual:

```text
Training Interchange Engine
```

Funciones:

```text
planear
exportar
ejecutar
importar resultado
comparar
ajustar
versionar
```

Flujo:

```text
planned_workout
        ↓
exporter
        ↓
device/app
        ↓
completed_activity
        ↓
importer
        ↓
plan_vs_actual
        ↓
progression_engine
```

Módulos sugeridos:

```text
app/services/training/
├── plan_parser.py
├── plan_versioning.py
├── workout_scheduler.py
├── overload_engine.py
├── plan_vs_actual.py
├── exporters/
└── importers/
```

---

## Exportadores

### 14. Exportadores por destino

El sistema debe tener exportadores por tipo de rutina y destino.

No debe existir un solo exportador universal. Debe haber adaptadores.

Ejemplo:

```text
routine.json interno
        ↓
MageneExporter
HuaweiExporter
GarminFitExporter
ZwiftExporter
PdfExporter
CsvExporter
JsonExporter
```

Cada exportador debe declarar:

```text
qué tipo de rutina soporta
qué formato genera
qué datos conserva
qué datos pierde
qué dispositivos son compatibles
qué tan experimental es
```

Interfaz conceptual:

```text
can_export(routine)
export(routine)
get_supported_sports()
get_supported_devices()
get_data_loss_warning()
```

---

### 15. Exportadores para ciclismo

Para rutinas de bici, rutas o intervalos:

Formatos deseables:

```text
GPX
TCX
FIT Course
FIT Workout
ZWO
ERG
MRC
```

Destinos:

```text
Magene / OnelapFit
Garmin
Wahoo
Zwift
TrainingPeaks
ROUVY
```

Casos:

```text
Bici outdoor ruta → GPX / TCX / FIT Course
Bici indoor intervalos → ZWO / ERG / MRC / FIT Workout
Bici outdoor workout estructurado → FIT Workout si es compatible
```

---

### 16. Exportador Magene

Para Magene, el sistema debe contemplar:

Exportación:

```text
GPX para rutas
ZWO / ERG / MRC para entrenamientos estructurados, si aplica mediante OnelapFit/TrainingPeaks
FIT Course o FIT Workout de forma experimental
Texto/HTML legible para recrear entrenamiento si no hay importación directa
```

Importación:

```text
FIT activity exportado desde OnelapFit
sincronización futura con Strava/TrainingPeaks si se implementa
```

Flujo:

```text
Rutina de bici en app
        ↓
exportador Magene
        ↓
OnelapFit / Magene
        ↓
actividad realizada
        ↓
FIT de regreso
        ↓
importador FIT
        ↓
plan vs realidad
```

---

### 17. Exportadores para gimnasio/fuerza

Para rutinas de fuerza:

Formatos iniciales:

```text
JSON propio
CSV
HTML
PDF
Huawei companion payload
FIT Workout experimental
```

No se debe asumir que una compu de bici o un reloj aceptan rutinas de fuerza de forma nativa. La app debe usar el destino correcto según disciplina.

Para gym, el mejor flujo futuro es:

```text
Rutina gym
        ↓
APK Android companion
        ↓
App reloj
        ↓
registro de series
        ↓
resultado de vuelta al servidor
```

---

## APK Android y app de reloj

### 18. APK companion

El proyecto debe contemplar una app Android companion a futuro.

Funciones del APK:

```text
login contra servidor Flask
descargar rutinas
guardar cache offline
enviar rutinas al reloj
recibir resultados del reloj
subir resultados al servidor
mostrar rutina si el reloj no soporta app
sincronizar cuando haya conexión
gestionar tokens
```

El APK debe ser el puente principal entre el servidor y el reloj.

Flujo:

```text
Servidor Flask
        ↕ API REST
APK Android
        ↕ Bluetooth / Wear Engine / bridge
Reloj
```

---

### 19. App de reloj

La app del reloj debe servir para ejecutar entrenamientos con mayor flexibilidad.

Para gym debe mostrar:

```text
rutina del día
ejercicio actual
series pendientes
peso objetivo
rango de reps
RIR objetivo
descanso
botón completar serie
botón saltar ejercicio
captura de reps
captura de peso
captura de RIR/RPE
resumen final
```

Debe funcionar offline durante el entrenamiento.

Flujo:

```text
APK manda planned_workout al reloj
        ↓
reloj guía la sesión
        ↓
reloj genera completed_workout
        ↓
reloj manda resultado al APK
        ↓
APK sube al servidor
```

---

### 20. Huawei como destino

Huawei debe manejarse en niveles:

```text
Nivel 1:
  APK Android muestra rutina y registra sesión.

Nivel 2:
  App de reloj recibe rutina y registra series.

Nivel 3:
  Integración con Huawei Health Kit para leer/escribir datos autorizados.

Nivel 4:
  Integración más profunda con rutinas nativas si la API/dispositivo lo permite.
```

No se debe depender desde el MVP de que Huawei acepte importar rutinas personalizadas nativas.

La estrategia principal debe ser:

```text
formato propio
APK companion
app reloj
sincronización de resultados
```

---

## Importadores

### 21. Importadores de resultados

El sistema debe importar resultados desde:

```text
.fit de dispositivos
.json interno
actividad completada desde APK
actividad completada desde reloj
archivos de Magene/OnelapFit
Garmin/Strava/TrainingPeaks en fases futuras
captura manual
```

Importadores iniciales:

```text
fit_activity_importer.py
completed_workout_json_importer.py
manual_result_importer.py
magene_fit_importer.py
huawei_companion_result_importer.py
```

Todos deben convertir a:

```text
completed_workout.schema.json
```

---

## Base de datos sugerida

### 22. Tablas principales

Usuarios:

```text
users
user_profiles
user_settings
```

Archivos:

```text
uploaded_files
generated_files
exported_files
import_jobs
```

Nutrición:

```text
daily_nutrition
nutrition_meals
nutrition_items
foods
recipes
recipe_versions
```

Energía:

```text
daily_energy
activity_energy_records
```

Peso:

```text
weigh_ins
body_composition_records
```

Médico:

```text
medical_documents
medical_lab_reports
medical_lab_results
medical_markers
```

Entrenamiento:

```text
exercises
training_plans
training_plan_versions
training_plan_days
training_plan_exercises
planned_workouts
training_sessions
training_session_exercises
training_sets
```

Intercambio:

```text
exported_workouts
imported_workout_results
device_profiles
connected_apps
```

---

## API inicial

### 23. Rutas web

Auth:

```text
GET  /login
POST /login
POST /logout
GET  /admin/users
POST /admin/users/create
```

Dashboard:

```text
GET /dashboard
GET /dashboard/<user_id>
```

Uploads:

```text
GET  /upload
POST /upload
GET  /files
GET  /files/<id>
```

Captura manual:

```text
GET  /manual/nutrition
POST /manual/nutrition
GET  /manual/energy
POST /manual/energy
GET  /manual/weight
POST /manual/weight
GET  /manual/medical
POST /manual/medical
GET  /manual/training-session
POST /manual/training-session
```

Rutinas:

```text
GET  /routines
GET  /routines/import
POST /routines/import
GET  /routines/<id>
GET  /routines/<id>/edit
POST /routines/<id>/edit
GET  /routines/<id>/history
POST /routines/<id>/activate-version
GET  /routines/<id>/export
```

Entrenamientos:

```text
GET  /workouts
GET  /workouts/planned
GET  /workouts/completed
POST /workouts/import-result
GET  /workouts/<id>/analysis
```

---

### 24. API REST para APK

Auth:

```text
POST /api/auth/login
POST /api/auth/refresh
POST /api/auth/logout
```

Rutinas:

```text
GET  /api/routines/active
GET  /api/routines/<id>
GET  /api/planned-workouts/today
POST /api/planned-workouts/<id>/export
```

Resultados:

```text
POST /api/completed-workouts
GET  /api/completed-workouts
GET  /api/completed-workouts/<id>
```

Sincronización:

```text
GET  /api/sync/bootstrap
POST /api/sync/push
GET  /api/sync/pull
```

---

## Estructura de repositorio sugerida

```text
health-tracker/
├── backend/
│   ├── app/
│   │   ├── auth/
│   │   ├── routes/
│   │   ├── models/
│   │   ├── services/
│   │   │   ├── importers/
│   │   │   ├── exporters/
│   │   │   ├── training/
│   │   │   ├── nutrition/
│   │   │   ├── medical/
│   │   │   └── files/
│   │   ├── templates/
│   │   └── static/
│   ├── migrations/
│   ├── Dockerfile
│   └── requirements.txt
│
├── schemas/
│   ├── daily_nutrition.schema.json
│   ├── daily_energy.schema.json
│   ├── weigh_in.schema.json
│   ├── medical_lab.schema.json
│   ├── training_plan.schema.json
│   ├── planned_workout.schema.json
│   ├── completed_workout.schema.json
│   └── route.schema.json
│
├── examples/
│   ├── fake_daily_nutrition.json
│   ├── fake_weigh_in.json
│   ├── fake_training_plan.json
│   ├── fake_completed_workout.json
│   └── fake_medical_lab.json
│
├── android-app/
│   └── planned_future_module/
│
├── watch-app/
│   └── planned_future_module/
│
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
├── AGENTS.md
└── LICENSE
```

---

## Docker

### 25. Servicios iniciales

```text
app:
  Flask backend

db:
  MariaDB

optional:
  adminer/phpmyadmin para desarrollo
```

Variables `.env`:

```text
DB_PASSWORD
DB_ROOT_PASSWORD
SECRET_KEY
INITIAL_ADMIN_EMAIL
INITIAL_ADMIN_PASSWORD
UPLOAD_FOLDER
APP_BASE_URL
```

---

## Seguridad y privacidad

### 26. Reglas obligatorias

- Nunca subir `/data` real a GitHub.
- Nunca subir `.env`.
- Nunca subir estudios médicos reales.
- Nunca subir datos reales de usuarios.
- Separar datos por `user_id`.
- Validar permisos en cada consulta.
- Usar hash para evitar duplicados.
- Registrar origen de cada dato.
- Conservar archivo original.
- Permitir exportación y backup.
- Usar login incluso en red local.
- Pensar en VPN o reverse proxy privado, no exposición pública directa.
- Los ejemplos del repositorio deben ser ficticios.
- Los tests no deben depender de datos personales reales.

---

## MVP por fases

### Fase 1: Base del sistema

- Flask.
- MariaDB.
- Docker Compose.
- Usuarios.
- Login.
- Admin inicial.
- `.gitignore`.
- Upload básico.
- Tabla `uploaded_files`.
- Guardado de archivos por usuario.
- Hash SHA256.

### Fase 2: Schemas y captura manual

- JSON Schemas base.
- Generador de archivos manuales.
- Captura manual de:
  - peso.
  - dieta.
  - energía diaria.
  - entrenamiento simple.
- Validación e importación.

### Fase 3: Rutinas versionables

- Importar rutina `.json`.
- Editar rutina desde web.
- Guardar nuevas versiones.
- Activar versión.
- Exportar rutina `.json`.
- Registrar sesiones manuales.
- Comparar sesión vs rutina.

### Fase 4: Sobrecarga progresiva

- Historial por ejercicio.
- Volumen.
- Reps totales.
- Peso usado.
- RIR/RPE.
- Sugerencia de progresión.
- Estancamiento.
- Día fuerte.
- Comparativa semanal.

### Fase 5: Importadores reales

- Importar `.fit`.
- Importar resultados de Magene/OnelapFit.
- Importar rutas GPX/TCX.
- Importar pesajes JSON/CSV.
- Importar estudios médicos JSON.

### Fase 6: Exportadores

- Exportador JSON.
- Exportador CSV.
- Exportador HTML/PDF.
- Exportador GPX.
- Exportador ZWO/ERG/MRC.
- Exportador FIT experimental.
- Perfil Magene.
- Perfil Huawei companion.

Estado actual: Fase 6 avanzada en `feature/phase-6-exporters-complete`; FIT de salida continúa unsupported experimental. Magene/OnelapFit sigue limitado a archivos estándar interoperables, sin APIs privadas.

### Fase 7: APK companion

- Login.
- Descargar rutinas.
- Cache offline.
- Registrar sesión desde celular.
- Subir resultados.
- Preparar comunicación con reloj.

### Fase 8: App de reloj

- Recibir rutina.
- Guiar sesión.
- Registrar series.
- Temporizador de descanso.
- Guardar offline.
- Enviar resultado al APK.

---

## Diferenciador del proyecto

Este proyecto no debe verse solo como un tracker de dieta o gimnasio. Su diferenciador principal es ser una plataforma privada de normalización e intercambio de datos personales de salud y entrenamiento.

La idea fuerte es:

```text
Planear → exportar → ejecutar → importar resultado → comparar → ajustar
```

Aplicado a:

```text
dieta
energía
peso
entrenamiento
bici
gym
rutas
estudios médicos
```

El valor principal no es únicamente el dashboard, sino el pipeline:

```text
datos externos/manuales
        ↓
formato estándar
        ↓
validación
        ↓
historial
        ↓
análisis
        ↓
exportación/importación
        ↓
mejora progresiva
```

La app debe funcionar como una especie de hub privado entre el usuario, su familia, sus dispositivos, sus rutinas y sus datos médicos.

---

## Reglas para próximos agentes

Antes de implementar:

1. Leer `AGENTS.md`.
2. Leer `docs/AI_WORK_CONTEXT.md`.
3. Leer este archivo completo.
4. Leer las reglas canónicas aplicables en `docs/project-rules/`.
5. Revisar README.
6. Revisar pruebas existentes.
7. Revisar modelos actuales antes de crear migraciones.
8. No modificar datos reales.
9. No subir ni tocar `/data`.
10. No romper aislamiento por usuario.

Al terminar una tarea:

1. Ejecutar `python -m compileall .`.
2. Ejecutar `pytest`.
3. Ejecutar `flask db check` si aplica.
4. Ejecutar `docker compose config`.
5. Si hay Docker disponible, probar también dentro del contenedor.
6. Documentar qué archivos se modificaron.
7. Indicar si se añadieron migraciones o no.
8. Indicar si hay cambios pendientes.
