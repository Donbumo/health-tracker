# Health Tracker

## Alpha 0.6: API Auth Foundation

La API `/api/v1` prepara la futura companion sin reutilizar cookies web: access corto, refresh opaco hash-only con rotación/reuse detection, logout, dispositivos, `/me`, bootstrap y rutina activa con ETag.

```powershell
curl.exe http://localhost:8000/api/v1/health
flask api-auth cleanup
flask api-auth cleanup --apply
```

CORS está cerrado por defecto, HTTPS es obligatorio fuera de QA y el rate limiter en memoria es por proceso: solo basta para QA privada/self-hosted; producción pública requiere backend compartido. Los IDs públicos son UUID persistidos y no cambian al rotar `API_TOKEN_SIGNING_KEY`. Sync push/pull, conflictos, planned workouts, APK y reloj no están implementados. Consulta `docs/API_V1.md`, `docs/API_AUTH.md`, `docs/API_DEVICE_SESSIONS.md`, `docs/API_SECURITY.md` y `docs/COMPANION_BOOTSTRAP.md`.

## Alpha 0.6.1: Web UI Homelab

La interfaz web usa un shell responsive propio: navegación lateral agrupada en escritorio, menú compacto en móvil, dashboard centrado en el estado diario y accesos de cuenta para dispositivos API y diagnóstico seguro del homelab.

- `/account/devices`: dispositivos API propios y revocación segura mediante POST + CSRF.
- `/account/system`: salud de DB/storage y conteos operativos del usuario sin exponer secretos ni rutas.
- Tema claro/oscuro automático según el sistema.
- Tablas contenidas, formularios táctiles y navegación por teclado con foco visible.

Consulta [WEB_UI_HOMELAB.md](docs/WEB_UI_HOMELAB.md), [WEB_UI_DESIGN_SYSTEM.md](docs/WEB_UI_DESIGN_SYSTEM.md) y [WEB_UI_ACCESSIBILITY.md](docs/WEB_UI_ACCESSIBILITY.md).

Aplicación web privada, self-hosted y multiusuario. El MVP actual incluye autenticación, almacenamiento aislado, entrenamiento versionable, nutrición/energía diaria, peso y composición corporal, además de un dashboard diario consolidado.

## Alcance de la Fase 1

- Backend Flask con Flask-SQLAlchemy, Flask-Migrate y MariaDB.
- Login/logout; usuarios con rol `admin` o `user`.
- Creación idempotente del administrador inicial desde `.env`.
- Uploads en `data/uploads/raw/user_<id>/`.
- SHA256 y restricción única por `(user_id, sha256)`.
- Persistencia de los bytes originales y del nombre original como metadato.

Nutrición completa, rutinas avanzadas, estudios médicos, importadores especializados, APK y reloj quedan fuera de estas fases.

## Alcance de la Fase 2

- Schemas JSON Draft 2020-12 para `weigh_in`, `daily_energy`, `daily_nutrition` mínimo y `completed_workout` mínimo.
- Servicio común de validación con comprobación de formatos `date` y `date-time`.
- Generador determinista de archivos JSON estándar para capturas manuales.
- Formulario inicial de pesaje con peso, grasa corporal opcional y notas.
- Archivos generados en `data/uploads/generated/user_<id>/`.
- Registro con `source_type=manual_generated`, SHA256 y deduplicación por usuario.

El flujo actual conserva ese JSON como fuente y también lo importa a la tabla `weigh_ins`; esta persistencia posterior mantiene compatibilidad con los documentos creados desde la Fase 2.

## Alcance de la Fase 3

- Schema `training_plan` con semanas, días, ejercicios y series mínimas.
- Modelos `TrainingPlan` y `TrainingPlanVersion`, ambos aislados por `user_id`.
- Importación desde `.json`, conservando el upload original y registrando `source_file_id`.
- Primera importación guardada como versión 1 y versión activa.
- Listado, detalle y exportación JSON de la versión activa.
- Deduplicación: importar nuevamente el mismo archivo devuelve la rutina existente.

Edición visual avanzada, sobrecarga progresiva, comparación avanzada plan vs realidad e integraciones con dispositivos permanecen fuera de esta fase.

## Alcance de la Fase 4

- Modelos `TrainingSession`, `TrainingSessionExercise` y `TrainingSet`, todos aislados por `user_id`.
- Registro manual basado en un día de la versión activa de una rutina.
- Generación previa de un `completed_workout` en `data/uploads/generated/user_<id>/`.
- Peso, reps, RIR opcional y notas por serie, además de notas generales de sesión.
- Asociación histórica con `training_plan_id` y `training_plan_version_id`.
- Comparación básica de ejercicios, series y reps objetivo contra reps reales.

## Alcance de la Fase 5

- Historial por ejercicio a partir de las sesiones ya registradas.
- Volumen por serie (`peso × reps`) y volumen acumulado por ejercicio y sesión.
- Reps totales, peso máximo y mejor serie por volumen.
- Comparación de volumen, reps y peso máximo contra la sesión anterior del mismo ejercicio.
- Sugerencias simples de carga usando el rango planeado y el RIR registrado.
- Resumen de progreso desde el detalle de cada sesión.
- Estimación de 1RM con Epley, RPE promedio y descanso promedio cuando existen.
- Tendencia contra la sesión anterior, detección básica de estancamiento y señales de fatiga.
- Identidades canónicas y aliases privados por usuario para agrupar nombres equivalentes sin reescribir las sesiones históricas.

Para planes de fuerza, cada serie puede usar `reps` como objetivo exacto o el par `reps_min` y `reps_max` como rango. La sugerencia es **Subir carga** cuando se completan todas las series en el extremo alto con al menos 2 RIR; **Mantener** cuando el trabajo queda dentro del rango; y **Revisar fatiga** cuando falta una serie o sus reps caen por debajo del mínimo. Son reglas descriptivas del entrenamiento registrado, no recomendaciones médicas ni un motor avanzado de programación.

## Alcance de la Fase 6

- Registry uniforme con preview read-only, capability, warnings y pérdidas declaradas.
- `ExportRecord` owner-only con SHA256, tamaño, media type, storage relativo y estado.
- Activity: JSON, CSV resumen/track/laps, GPX 1.1 y TCX Activity.
- Route: JSON, CSV de puntos, GPX 1.1 y TCX Course.
- Rutinas/versiones: JSON, CSV, HTML, PDF y ZWO/ERG/MRC cuando los targets de potencia son explícitos.
- Sesiones: completed_workout JSON, CSV, HTML y PDF.
- Historial y descarga segura desde `/exports`, con verificación de tamaño/hash y eliminación controlada.
- FIT de salida queda experimental/unsupported; no se usa un encoder casero ni se fabrican archivos `.fit` falsos.

Consulta `docs/EXPORTERS.md`, `docs/ACTIVITY_ROUTE_EXPORTS.md`, `docs/TRAINING_EXPORTS.md` y `docs/EXPORT_STORAGE.md`.

## Fase 5 / Alpha 0.3: importadores reales

La rama `feature/phase-5-real-importers` agrega una base funcional para importar archivos desde **Importar archivos** (`/imports/files`):

- GPX como actividad si trae timestamps o ruta si solo trae puntos.
- TCX de actividad con laps, trackpoints, FC, cadencia, distancia y potencia cuando existen.
- TCX Course como ruta cuando el archivo contiene cursos sin `Activity`.
- FIT binario vendor-neutral mediante `fitdecode==0.10.0`, con soporte para `file_id`, `device_info`, `sport`, `session`, `lap` y `record`.
- CSV de pesajes con conversión lb → kg.
- CSV de energía diaria con calorías, pasos y distancia.
- JSON interno de laboratorio, rutina y sesión completada dentro del pipeline común.
- Actividades y rutas persistidas, listables y exportables como JSON.
- `activity` y `route` incluidos en export/restore completo de cuenta.

Flujo:

```text
upload raw -> SHA256 -> detector/parser -> JSON estándar -> preview -> confirmación firmada -> ImportRun
```

FIT se decodifica con `fitdecode` sobre fixtures binarias FIT sintéticas y archivos FIT estándar que expongan campos compatibles. Se validan header/CRC, truncados, límites de records, semicircles GPS, unidades, laps, records y actividad sin GPS. Si hay GPS se crea actividad + ruta; sin GPS se crea solo actividad con warning. No se usan APIs privadas de Magene/OnelapFit.

Documentación:

- `docs/REAL_FILE_IMPORTS.md`
- `docs/FIT_IMPORT.md`
- `docs/GPX_TCX_IMPORT.md`
- `docs/CSV_IMPORT.md`
- `docs/project-rules/real-file-imports.md`

## Requisitos

- Windows 10/11.
- Docker Desktop iniciado y configurado para contenedores Linux.
- Docker Compose v2 (incluido en Docker Desktop).

No hace falta instalar Python ni MariaDB en Windows para ejecutar la aplicación.

## Instalación en Windows (PowerShell)

Desde la raíz del repositorio:

```powershell
Copy-Item .env.example .env
notepad .env
```

Antes de continuar, reemplaza todos los valores `replace-with-...`. Usa secretos largos y distintos. Para generar uno aleatorio desde PowerShell:

```powershell
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$bytes = New-Object byte[] 48
$rng.GetBytes($bytes)
[Convert]::ToBase64String($bytes)
```

Valida la configuración y levanta los servicios:

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose logs -f web
```

Cuando el log indique que Gunicorn está escuchando en el puerto 8000, abre [http://localhost:8000](http://localhost:8000) e inicia sesión con `ADMIN_USERNAME` y `ADMIN_PASSWORD`.

El contenedor ejecuta automáticamente `flask db upgrade` y `flask seed-admin` antes de iniciar el servidor. Si el administrador ya existe, no cambia su contraseña ni sus datos.

## QA manual web

Desde la raíz del repositorio, construye y levanta la aplicación:

```powershell
docker compose up --build -d
docker compose exec web flask db upgrade
docker compose ps
```

El administrador inicial usa `ADMIN_USERNAME` y `ADMIN_PASSWORD` de `.env`. El entrypoint ejecuta `flask seed-admin` de forma idempotente; después abre [http://localhost:8000](http://localhost:8000) e inicia sesión con esas credenciales. Desde **Admin** puedes crear otras cuentas locales.

Para poblar una cuenta de QA con datos completamente ficticios ejecuta, de forma explícita:

```powershell
docker compose exec web flask seed demo
```

Credenciales demo:

```text
email: demo@example.com
password: demo12345
```

El comando crea dos pesajes, dos días de energía, dos días de nutrición, una rutina, una sesión y un reporte de laboratorio con siete marcadores ficticios para hoy/ayer según `APP_TIMEZONE`. Es idempotente al repetirlo para las mismas fechas y restablece la contraseña conocida de la cuenta demo. Solo debe usarse en desarrollo o QA; no se ejecuta automáticamente ni crea archivos en `/data`.

Checklist sugerido:

1. Inicia sesión como administrador y crea un usuario desde **Admin**.
2. Inicia sesión con el usuario creado o con `demo@example.com`.
3. Abre **Peso → Captura manual** y registra un pesaje ficticio.
4. Abre **Energía → Captura manual** y registra gasto ficticio.
5. Abre **Nutrición → Captura manual** y registra un item ficticio.
6. Revisa el estado completo/parcial/faltante en **Dashboard**.
7. Prueba imports JSON y exports JSON/CSV desde los detalles correspondientes.
8. Prueba **Importar archivos** con GPX, TCX o CSV ficticio y revisa `/activities` o `/routes`.
9. Importa una rutina JSON o usa la rutina demo.
10. Registra una sesión basada en la rutina y revisa su detalle.
11. Abre **Progreso** y entra al análisis de la sesión.
12. Abre **Laboratorios**, revisa el reporte demo, su historial y sus exports JSON/CSV.
13. Comprueba estados vacíos y mensajes 403/404 con una cuenta sin datos/permisos.

Verificación dentro del contenedor:

```powershell
docker compose exec -T web flask db check

# pytest es una dependencia de desarrollo; esta instalación es temporal en el contenedor actual.
docker compose exec -T --user root web python -m pip install --no-cache-dir -r requirements-dev.txt
docker compose exec -T web python -m pytest -q
```

Para detener los servicios sin borrar MariaDB ni archivos locales:

```powershell
docker compose down
```

## Captura manual de pesaje

1. Inicia sesión.
2. Abre **Registrar pesaje** en la navegación o visita [http://localhost:8000/manual/weigh-in](http://localhost:8000/manual/weigh-in).
3. Indica fecha/hora y peso. Opcionalmente agrega grasa corporal, masa muscular, agua, grasa visceral, BMR, BMI y notas.
4. Al guardar, la aplicación genera el JSON, lo valida contra `schemas/weigh_in.schema.json`, calcula su SHA256, conserva el archivo fuente y persiste el pesaje en MariaDB.

La fecha se interpreta con `APP_TIMEZONE`. El valor recomendado para esta instalación es `America/Mexico_City`; usa un nombre válido de la base IANA si necesitas cambiarlo. Enviar exactamente la misma captura nuevamente no crea otro archivo ni registro.

También están disponibles:

- `/weigh-ins`: listado y accesos de peso.
- `/weigh-ins/import`: importación de JSON interno validado.
- `/weigh-ins/history`: historial con cambios, promedio de los últimos siete registros y tendencia simple.
- `/weigh-ins/<id>/export/json`: documento completo de un pesaje.
- `/weigh-ins/export/csv`: resumen tabular del historial.

Los imports válidos, duplicados o con error actualizan el estado de `UploadedFile`. El JSON es el formato recomendado para conservar todos los campos; CSV omite notas y metadatos de procedencia.

## Dashboard diario

Abre **Dashboard** o visita `/dashboard?date=AAAA-MM-DD`. Para la fecha elegida muestra:

- calorías y macros nutricionales básicos;
- gasto total/activo, pasos y balance de calorías;
- pesaje del día o, si falta, el último pesaje anterior;
- sesiones realizadas con duración, volumen, ejercicios y calorías.
- última actividad importada y totales de actividad de los últimos siete días.
- último reporte de laboratorio disponible en la fecha y cantidad de marcadores.

El estado del día considera esenciales una nutrición con calorías y una energía con gasto total. Distingue entre dato completo, registro parcial y dato faltante. Peso y entrenamiento se muestran como contexto opcional: un día de descanso o sin pesaje no se marca como incompleto.

El bloque corporal muestra el cambio contra el pesaje anterior cuando existe. Si hay varias sesiones, entrenamiento presenta totales de duración, volumen, ejercicios y calorías registradas. Las calorías de sesión no se suman al gasto diario porque el dispositivo o fuente de energía podría haberlas incluido ya.

Cada bloque conserva estados explícitos cuando faltan datos y todas las consultas quedan limitadas al usuario autenticado. No se generan estimaciones para valores ausentes ni interpretaciones médicas del balance.

## Rutinas versionables

Abre **Rutinas → Importar rutina** o visita [http://localhost:8000/training-plans/import](http://localhost:8000/training-plans/import). La página muestra el `user_id` que debe contener el documento.

Ejemplo mínimo con un día de descanso:

```json
{
  "schema_version": "1.0",
  "record_type": "training_plan",
  "user_id": 1,
  "source_type": "uploaded",
  "data": {
    "name": "Example foundation plan",
    "weeks": [
      {
        "week_number": 1,
        "days": [
          {"day_number": 1, "name": "Rest day", "exercises": []}
        ]
      }
    ]
  }
}
```

Reemplaza `user_id` por el valor mostrado en la página. El archivo debe usar extensión `.json`. Tras importarlo puedes abrir su detalle y descargar la versión activa como **Rutina JSON** o **Rutina CSV**.

## Registrar una sesión realizada

1. Importa al menos una rutina que contenga un día con ejercicios.
2. Abre **Sesiones → Registrar sesión**, o usa **Registrar sesión** desde el detalle de una rutina.
3. Selecciona el día planeado y pulsa **Cargar ejercicios**.
4. Marca las series efectivamente realizadas e indica peso, reps, RIR, RPE, descanso y notas cuando apliquen.
5. Opcionalmente registra duración total, frecuencia cardiaca promedio y calorías.
6. Guarda la sesión para ver su detalle y la comparación plan vs realidad.

Las series no marcadas aparecen como omitidas. En este MVP solo se capturan series correspondientes al día planeado; no existe todavía edición avanzada ni captura de ejercicios adicionales.

## Consultar el progreso

Después de registrar una sesión:

1. Abre su detalle y pulsa **Ver progreso** para consultar volumen total, reps, peso máximo, mejor serie, 1RM estimado, RPE y descanso promedio.
2. Pulsa el nombre de un ejercicio para abrir su historial completo.
3. Consulta la tendencia, la diferencia contra la ejecución anterior y la recomendación básica calculada desde el rango de reps, RIR, RPE e historial.
4. Desde el historial agrega aliases para nombres equivalentes, por ejemplo `Remo en T` y `T-bar row`.

El historial usa la identidad canónica cuando existe; de lo contrario mantiene el fallback por nombre sin distinguir mayúsculas. Los aliases son privados y siempre se limitan al usuario autenticado. Si el plan usa un objetivo exacto `reps`, ese valor funciona como mínimo y máximo del rango.

## Importar y exportar

En el detalle de una rutina están disponibles:

- **Rutina JSON**: documento interno completo, validado contra `training_plan.schema.json`.
- **Rutina CSV**: una fila por serie planeada; los días de descanso conservan una fila vacía de ejercicio.

En el detalle de una sesión están disponibles:

- **Sesión JSON**: documento interno completo, validado contra `completed_workout.schema.json`.
- **Sesión CSV**: una fila por serie realizada.
- **Vista imprimible**: HTML sencillo con tabla de ejercicios y series.

CSV aplana la jerarquía y puede perder estructura o metadatos; usa JSON para respaldos o intercambio entre instalaciones compatibles. Para importar una sesión abre **Sesiones → Importar JSON**. El documento debe usar tu `user_id` y referenciar una rutina y versión que ya existan en tu cuenta. Los archivos válidos, inválidos y duplicados se conservan como fuentes originales bajo `data/uploads/raw/user_<id>/`.

La página **Archivos** muestra el tipo detectado, estado de importación (`pending`, `imported`, `duplicate` o `error`) y el mensaje de error cuando corresponde.

## Importación asistida confirmada

La ruta `/imports/standard` permite probar el flujo nuevo de QA:

1. Inicia sesión.
2. Sube un JSON interno o un JSON no estándar compatible con el asistente.
3. Revisa el preview, el mapping sugerido, la validación y el plan.
4. Confirma explícitamente.
5. La app guarda el lote de forma transaccional en tu cuenta.

El plan usa operaciones:

- `insert`
- `update`
- `skip`
- `conflict`
- `invalid`

El `user_id` efectivo siempre sale de la sesión autenticada; un `user_id` dentro del archivo no puede importar datos hacia otra cuenta. Si hay documentos inválidos o conflictos, el commit se bloquea. Para respaldos completos usa el flujo separado de **Mis datos** / `/account/data`.

La confirmación web se firma contra usuario, target, payload y plan revisado. Si el plan cambia entre preview y confirmación, o el token vence, se reutiliza o pertenece a otro usuario, la app exige revisar un nuevo preview. El lote es atómico: si falla un elemento durante la escritura, se hace rollback y no queda éxito parcial silencioso.

Para conservar esa atomicidad, el flujo confirmado usa adaptadores internos de persistencia en `StandardImportExecutor` y no llama importadores que hacen commit propio. `completed_workout` permite insert pero devuelve conflicto ante repetición/update hasta tener una clave segura de actualización; `recipe_bundle` se importa por recetas embebidas y no crea un modelo Bundle persistente.

## Administración básica de usuarios

Los usuarios con rol `admin` pueden abrir **Usuarios** o visitar [http://localhost:8000/admin/users](http://localhost:8000/admin/users). Desde ahí pueden listar cuentas y crear usuarios con email, contraseña temporal y rol `admin` o `user`. Los usuarios normales reciben HTTP 403. Las cuentas creadas desde este panel pueden iniciar sesión con su email; los usernames existentes siguen siendo compatibles.

## Nutrición y energía diaria

El módulo persiste:

- `DailyEnergy`: calorías totales, activas y de reposo, pasos, distancia, fuente y payload original opcional.
- `DailyNutrition`: totales diarios y notas.
- `NutritionMeal` y `NutritionItem`: comidas ordenadas e items con cantidad, unidad y macros básicos.

Rutas principales:

- `/daily-energy` y `/daily-energy/import`.
- `/daily-nutrition` y `/daily-nutrition/import`.
- `/daily-balance?date=AAAA-MM-DD`.
- `/manual/energy` y `/manual/nutrition`.

Los imports JSON se validan contra `daily_energy.schema.json` o `daily_nutrition.schema.json`, conservan el archivo original y registran su estado. Existe un único agregado de energía y uno de nutrición por usuario y fecha.

Cuando un día nutricional contiene items, cada macro presente en esos items se suma y tiene prioridad. Los totales del documento se usan como fallback únicamente para métricas que ningún item aporte. Esto permite conservar el formato legado de totales sin tratar datos desconocidos como cero.

La captura manual de nutrición es intencionalmente mínima: crea una comida con un item. Para días con varios items o comidas se usa el JSON importable; queda pendiente un editor dinámico.

Desde el detalle de cada registro están disponibles JSON estándar y CSV. El CSV nutricional contiene solo el resumen diario y pierde la jerarquía de comidas/items; JSON es el formato recomendado para reimportación y respaldo.

Formatos futuros, todavía sin implementación real: FIT, GPX, TCX, Magene, Huawei, PDF avanzado e integraciones de APK/reloj. Los módulos stub de FIT, GPX y Magene solo reservan el punto de extensión y lanzan `NotImplementedError`.

## Estudios de laboratorio

El módulo organiza reportes y marcadores ficticios o capturados por el usuario. No interpreta resultados, emite diagnósticos ni sustituye una evaluación médica.

Rutas principales:

- `/medical/labs`: lista de reportes y accesos para captura/importación.
- `/medical/labs/manual`: captura mínima de un reporte con un marcador.
- `/medical/labs/import`: importación del JSON interno validado.
- `/medical/labs/<id>`: detalle y exports del reporte.
- `/medical/markers`: marcadores disponibles.
- `/medical/markers/<nombre>`: historial cronológico y cambio numérico cuando la unidad coincide.

Ejemplo deliberadamente ficticio; sustituye `user_id` por el identificador mostrado en la pantalla de importación:

```json
{
  "schema_version": "1.0",
  "type": "medical_lab",
  "user_id": 1,
  "source_type": "uploaded",
  "date": "2026-01-15",
  "laboratory_name": "Laboratorio ficticio QA",
  "notes": "Ejemplo ficticio; no es un resultado clínico.",
  "markers": [
    {
      "name": "Marcador ficticio QA",
      "code": "DEMO",
      "value": 12.3,
      "unit": "unidad-demo",
      "status": "unknown"
    }
  ]
}
```

El import valida `schemas/medical_lab.schema.json`, conserva el archivo original, calcula SHA256 y marca el upload como `imported`, `duplicate` o `error`. La deduplicación se aplica por usuario y contenido; el mismo documento puede pertenecer a usuarios distintos sin mezclar datos. JSON conserva toda la estructura del reporte. CSV aplana los marcadores y se ofrece tanto por reporte como para el historial de un marcador.

Checklist médico para QA:

1. Captura manualmente un reporte ficticio de un marcador.
2. Importa un JSON ficticio con varios marcadores.
3. Repite el import y confirma el aviso de duplicado.
4. Abre el detalle, los historiales y los exports JSON/CSV.
5. Verifica con otra cuenta que los IDs ajenos respondan 404 y no aparezcan en listas.

No se admiten OCR, PDF médico, FHIR ni interpretación clínica en esta fase.

## Operación y QA

Levanta la aplicación, aplica migraciones y crea los datos demo ficticios de forma explícita:

```powershell
docker compose up --build -d
docker compose exec web flask db upgrade
docker compose exec web flask seed demo
```

Abre [http://localhost:8000](http://localhost:8000) e inicia sesión con `demo@example.com` / `demo12345`.

Healthcheck público:

```text
GET http://localhost:8000/healthz
```

Responde `200` con `{"app":"health-tracker","status":"ok"}` cuando la aplicación y la consulta ligera `SELECT 1` funcionan. Si la base no responde, devuelve `503` sin exponer detalles de conexión.

Logs de Gunicorn:

```powershell
docker compose logs -f web
docker compose logs web --tail=120
```

Para QA, Gunicorn usa valores conservadores y configurables: timeout de 60 segundos, cierre gradual de 30 segundos y keep-alive de 5 segundos. Los logs de acceso, errores y salida capturada permanecen en stdout/stderr de Docker. Se pueden ajustar con `GUNICORN_TIMEOUT`, `GUNICORN_GRACEFUL_TIMEOUT`, `GUNICORN_KEEP_ALIVE` y `GUNICORN_LOG_LEVEL`.

Un administrador puede abrir `/admin/system` para consultar estado de DB, versión operativa, hora UTC y conteos agregados. La pantalla no muestra datos personales ni secretos. `APP_VERSION` puede contener una versión o commit desplegado; si no se configura muestra `unknown`.

Cada usuario autenticado puede descargar `/account/export.json`. El JSON incluye productos de alimento, recetas, pesajes, nutrición, energía, balances, rutinas y sus versiones, sesiones, laboratorios y metadata segura de uploads. No incluye `password_hash`, secretos, rutas internas ni archivos binarios. El respaldo ZIP queda para una fase futura.

## Handoff y portabilidad

[`docs/ACTIVE_HANDOFF.md`](docs/ACTIVE_HANDOFF.md) es el documento vivo para cambiar de agente sin depender de memoria previa. Debe leerse después de `AGENTS.md` y `docs/PROJECT_CONTEXT.md`.

Un usuario autenticado puede:

- Descargar su respaldo validado desde `/account/export.json`.
- Abrir `/account/restore` y seleccionar ese JSON para preview de restore.
- Confirmar el restore si el plan no tiene conflictos ni documentos inválidos.
- Opcionalmente abrir `/account/import-preview` para un dry-run heredado que solo valida y resume.

El restore valida `schemas/user_data_export.schema.json`, muestra errores, advertencias y un plan `insert/update/skip/conflict/invalid/unsupported`. La confirmación web se firma contra usuario autenticado, payload y plan revisado. El archivo se procesa en memoria: no crea `UploadedFile`, no guarda bytes en `/data`, ignora usuario/email/rol del export y remapea IDs internos de rutinas/versiones para restaurar sesiones. `uploads` y `daily_balances` son metadata/derivados y se omiten. El commit es atómico: si falla un registro, se hace rollback completo y queda auditoría saneada en `ImportRun` con `target_type=user_data_restore`.

No hay restore de archivos binarios, borrado masivo, selección manual de `user_id`, ZIP backup ni API pública.

Guías dedicadas:

- [`docs/ACCOUNT_RESTORE.md`](docs/ACCOUNT_RESTORE.md)
- [`docs/DATA_PORTABILITY.md`](docs/DATA_PORTABILITY.md)
- [`docs/project-rules/account-restore.md`](docs/project-rules/account-restore.md)

## QA de importación estándar confirmada

El flujo `/imports/standard` permite a un usuario autenticado subir JSON, revisar preview/plan y confirmar una importación transaccional. La fase de preview sigue siendo read-only; la escritura ocurre solo tras confirmación.

La misma pantalla incluye **Preparar archivo con IA**, un bloque colapsable con prompts base y plantillas JSON ficticias para los nueve targets soportados. Health Tracker no llama a APIs de IA, no envía datos fuera de la aplicación y no guarda el texto copiado. El usuario puede copiar el prompt, usarlo externamente bajo su responsabilidad, revisar el JSON devuelto y volver a `/imports/standard` para el preview normal.

Guía detallada: [`docs/IMPORT_WITH_AI_PROMPTS.md`](docs/IMPORT_WITH_AI_PROMPTS.md).

Hay fixtures ficticias para QA manual en:

```text
examples/qa/standard-import/
```

Incluyen `daily_energy`, `training_plan`, `completed_workout` y `medical_lab` con casos de insert, repetición/update/conflict, inválidos y batches. Antes de probar `completed_workout`, crea/importa una rutina para el usuario de QA y reemplaza los IDs ficticios de plan/version por IDs propios de ese usuario. No copies estas fixtures a `/data` ni uses datos reales.

### Historial de importaciones

Cada confirmación válida crea un `ImportRun` agregado:

- `succeeded` si el lote se guardó;
- `blocked` si el plan tenía inválidos o conflictos;
- `failed` si ocurrió un error de escritura y se hizo rollback.

Consulta desde:

```text
/imports/history
```

El historial muestra target, estado, conteos y hashes truncados. No guarda ni muestra payloads crudos, tokens, trazas ni datos de salud. La retención inicial conserva estos agregados; pruning automático queda para una fase futura.

Para entregar el proyecto a otro agente, compartir:

```text
AGENTS.md
docs/PROJECT_CONTEXT.md
docs/ACTIVE_HANDOFF.md
git status
git log --oneline -20
```

Pedir cambios por fases pequeñas y exigir `compileall`, pytest, `flask db check` y Compose válido antes de aceptar el handoff.

## Comandos habituales

```powershell
# Ver el estado
docker compose ps

# Ver logs
docker compose logs -f web db

# Detener la aplicación sin borrar datos
docker compose down

# Reconstruir tras cambios de código o dependencias
docker compose up --build -d
```

`docker compose down -v` elimina el volumen de MariaDB y todos sus registros. No lo uses si quieres conservar la base de datos. Los archivos subidos viven en `data/` y tampoco deben compartirse ni añadirse a Git.

## Desarrollo y pruebas sin Docker

Las pruebas usan SQLite temporal y datos ficticios; la aplicación normal usa MariaDB.

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m compileall -q .
python -m pytest -q
flask db check

cd ..
docker compose config --quiet
```

## Estructura de estas fases

```text
backend/
  app/
    auth/                 # login y logout
    admin/                # listado y creación básica de usuarios
    body/                 # pesajes, composición, historial e imports/exports
    medical/              # reportes de laboratorio, marcadores e imports/exports
    main/                 # dashboard diario y página de uploads
    models/               # usuarios, archivos, wellness, entrenamiento y laboratorios
    progress/             # historial y resumen de sobrecarga básica
    sessions/             # registro y detalle de sesiones realizadas
    training/             # importar, listar, ver y exportar rutinas
    wellness/             # nutrición, energía, balance, captura e imports
    services/files.py     # uploads originales
    services/daily_balance.py
    services/daily_dashboard.py
    services/exercise_identity.py # nombres canónicos y aliases privados
    services/exporters/   # JSON, CSV y HTML base
    services/importers/   # JSON interno y stubs de formatos futuros
    services/manual_json.py
    services/overload.py
    services/weight_history.py
    services/training_plans.py
    services/workout_sessions.py
    services/validation.py
    templates/
  migrations/
  Dockerfile
data/
  uploads/raw/             # uploads originales ignorados por Git
  uploads/generated/       # JSON manuales ignorados por Git
schemas/                   # contratos JSON versionados
docker-compose.yml
```

## Backup integral Alpha 0.5

Desde `/account/data` un usuario autenticado puede previsualizar y generar un backup ZIP 1.0 con su export JSON, uploads raw y exports generados. `/account/backups/restore` valida manifest, límites, paths, tamaños y SHA256 antes de mostrar el plan; la escritura exige confirmación firmada y conserva ownership del usuario destino.

Rutas principales:

- `/account/backups`: historial owner-only.
- `/account/backups/new`: preview y generación.
- `/account/backups/<id>/download`: descarga verificada.
- `/account/backups/restore`: preview read-only en staging.
- `/account/backups/restore/confirm`: restore confirmado.

Reconciliación operativa, dry-run por defecto:

```powershell
docker compose exec web flask backup reconcile
docker compose exec web flask backup reconcile --apply
```

El ZIP no incluye contraseñas, password hashes, sesiones ni secretos y no está cifrado. Consulta [FULL_BACKUP.md](docs/FULL_BACKUP.md), [BACKUP_FORMAT_1_0.md](docs/BACKUP_FORMAT_1_0.md), [BACKUP_SECURITY.md](docs/BACKUP_SECURITY.md) y [BACKUP_RESTORE_RUNBOOK.md](docs/BACKUP_RESTORE_RUNBOOK.md).

## Seguridad y privacidad

- No expongas la aplicación directamente a Internet; úsala en red local o mediante VPN.
- En HTTP local conserva `SESSION_COOKIE_SECURE=false`. Con HTTPS, cámbialo a `true`.
- Backups y archivos raw restaurados tienen descarga owner-only con verificación de tamaño y SHA256.
- El código no contiene datos personales reales; `.env`, `data/`, exports y formatos sensibles están ignorados.
- Cada consulta y cada upload de esta fase se filtran por el `user_id` autenticado.

## Alpha privada 0.5

Health Tracker está preparado para evaluación privada por usuarios invitados mediante una red local o VPN privada.

La Alpha 0.5 conserva los flujos de la Alpha 0.1 y agrega importación real, exportadores avanzados y backup/restore integral:

- crear cuentas desde la administración;
- registrar peso, nutrición, energía y entrenamiento;
- consultar el dashboard y el historial de importaciones;
- exportar los datos personales;
- usar la interfaz desde computadora o teléfono;
- mantener los datos aislados entre usuarios.
- crear y restaurar backups ZIP con datos y binarios verificados.

Esta aplicación no sustituye atención médica y no debe exponerse directamente a Internet.

Consulta:

- `docs/ALPHA_DEPLOYMENT.md` para desplegarla y compartir acceso;
- `docs/ALPHA_RELEASE_CHECKLIST.md` para validar una entrega.
