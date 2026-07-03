# Health Tracker

Aplicación web privada, self-hosted y multiusuario. Las seis primeras fases incluyen autenticación, almacenamiento aislado, captura manual validada, rutinas versionables, sesiones realizadas, análisis básico de sobrecarga e importación/exportación base.

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

La Fase 2 todavía no importa el contenido del pesaje a una tabla clínica: conserva el JSON validado como fuente estándar para una fase posterior.

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

- Interfaz común para exportadores y adaptadores separados por tipo de recurso.
- Rutinas exportables como JSON interno validado o CSV plano.
- Sesiones exportables como JSON interno validado, CSV plano o HTML imprimible.
- Importadores separados para `training_plan` y `completed_workout` JSON.
- Conservación del archivo original, SHA256 y deduplicación por `(user_id, sha256)`.
- Stubs documentados, sin parser real, para FIT genérico, GPX y Magene FIT.

Las descargas se generan en memoria. No se registran como `UploadedFile`, porque ese modelo representa archivos fuente; queda pendiente un modelo específico de auditoría de exports si se necesita en una fase posterior.

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

## Captura manual de pesaje

1. Inicia sesión.
2. Abre **Registrar pesaje** en la navegación o visita [http://localhost:8000/manual/weigh-in](http://localhost:8000/manual/weigh-in).
3. Indica la fecha/hora, el peso y, opcionalmente, grasa corporal y notas.
4. Al guardar, la aplicación genera el JSON, lo valida contra `schemas/weigh_in.schema.json`, calcula su SHA256 y lo registra en MariaDB.

La fecha se interpreta con `APP_TIMEZONE`. El valor recomendado para esta instalación es `America/Mexico_City`; usa un nombre válido de la base IANA si necesitas cambiarlo. Enviar exactamente la misma captura nuevamente no crea otro archivo ni registro.

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
pytest
```

## Estructura de estas fases

```text
backend/
  app/
    auth/                 # login y logout
    admin/                # listado y creación básica de usuarios
    main/                 # inicio y página de uploads
    models/               # usuarios, archivos y training plans versionados
    progress/             # historial y resumen de sobrecarga básica
    sessions/             # registro y detalle de sesiones realizadas
    training/             # importar, listar, ver y exportar rutinas
    wellness/             # nutrición, energía, balance, captura e imports
    services/files.py     # uploads originales
    services/daily_balance.py
    services/exercise_identity.py # nombres canónicos y aliases privados
    services/exporters/   # JSON, CSV y HTML base
    services/importers/   # JSON interno y stubs de formatos futuros
    services/manual_json.py
    services/overload.py
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

## Seguridad y privacidad

- No expongas la aplicación directamente a Internet; úsala en red local o mediante VPN.
- En HTTP local conserva `SESSION_COOKIE_SECURE=false`. Con HTTPS, cámbialo a `true`.
- No se ofrecen rutas para descargar archivos originales en esta fase.
- El código no contiene datos personales reales; `.env`, `data/`, exports y formatos sensibles están ignorados.
- Cada consulta y cada upload de esta fase se filtran por el `user_id` autenticado.
