# Health Tracker

Aplicación web privada, self-hosted y multiusuario. Esta primera fase incluye autenticación, roles y almacenamiento aislado de archivos con deduplicación por usuario.

## Alcance de la Fase 1

- Backend Flask con Flask-SQLAlchemy, Flask-Migrate y MariaDB.
- Login/logout; usuarios con rol `admin` o `user`.
- Creación idempotente del administrador inicial desde `.env`.
- Uploads en `data/uploads/raw/user_<id>/`.
- SHA256 y restricción única por `(user_id, sha256)`.
- Persistencia de los bytes originales y del nombre original como metadato.

Nutrición, rutinas, estudios médicos, importadores especializados, APK y reloj quedan fuera de esta fase.

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

## Estructura de esta fase

```text
backend/
  app/
    auth/                 # login y logout
    main/                 # inicio y página de uploads
    models/               # User y UploadedFile
    services/files.py     # hash y guardado aislado
    templates/
  migrations/             # migración inicial
  Dockerfile
data/
  uploads/raw/             # datos locales ignorados por Git
docker-compose.yml
```

## Seguridad y privacidad

- No expongas la aplicación directamente a Internet; úsala en red local o mediante VPN.
- En HTTP local conserva `SESSION_COOKIE_SECURE=false`. Con HTTPS, cámbialo a `true`.
- No se ofrecen rutas para descargar archivos originales en esta fase.
- El código no contiene datos personales reales; `.env`, `data/`, exports y formatos sensibles están ignorados.
- Cada consulta y cada upload de esta fase se filtran por el `user_id` autenticado.
