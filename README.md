# Health Tracker

Aplicación web privada, self-hosted y multiusuario. Las cuatro primeras fases incluyen autenticación, almacenamiento aislado, captura manual validada, rutinas versionables y sesiones realizadas.

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

Esta fase no incluye recomendaciones automáticas ni motor de sobrecarga progresiva.

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

Reemplaza `user_id` por el valor mostrado en la página. El archivo debe usar extensión `.json`. Tras importarlo puedes abrir su detalle y descargar la versión activa desde **Exportar JSON**.

## Registrar una sesión realizada

1. Importa al menos una rutina que contenga un día con ejercicios.
2. Abre **Sesiones → Registrar sesión**, o usa **Registrar sesión** desde el detalle de una rutina.
3. Selecciona el día planeado y pulsa **Cargar ejercicios**.
4. Marca las series efectivamente realizadas e indica peso, reps, RIR opcional y notas.
5. Guarda la sesión para ver su detalle y la comparación plan vs realidad.

Las series no marcadas aparecen como omitidas. En este MVP solo se capturan series correspondientes al día planeado; no existe todavía edición avanzada, ejercicios adicionales ni recomendaciones de progresión.

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
    main/                 # inicio y página de uploads
    models/               # usuarios, archivos y training plans versionados
    sessions/             # registro y detalle de sesiones realizadas
    training/             # importar, listar, ver y exportar rutinas
    services/files.py     # uploads originales
    services/manual_json.py
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
