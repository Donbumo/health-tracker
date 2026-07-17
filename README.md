# Health Tracker

Aplicación privada, self-hosted y multiusuario para centralizar salud, nutrición, entrenamiento, archivos e intercambio de datos mediante contratos JSON versionados.

Base integrada actual: tag `alpha-1.0.1-runtime-security` (`1938a48`). La cronología de entregas está en [docs/history/IMPLEMENTATION_HISTORY.md](docs/history/IMPLEMENTATION_HISTORY.md); no uses un hito histórico como contrato vigente.

## Capacidades actuales

- Login, usuarios y aislamiento owner-only.
- Peso/composición, nutrición, energía, alimentos, recetas y laboratorios.
- Rutinas versionables, sesiones, planned workouts, progreso y cargas avanzadas.
- Uploads con SHA256, JSON estándar, importación asistida y archivos FIT/GPX/TCX/CSV soportados.
- Exports por dominio, portabilidad JSON y backup/restore ZIP.
- API v1 con Bearer/dispositivos, Mobile Sync y backend Companion.
- Interfaz Flask/Jinja responsive, Import Hub y PWA limitada a assets estáticos.

No existen todavía APK Android, app de reloj, Bluetooth, telemetría continua, FIT de salida ni integraciones privadas de fabricantes. Consulta [docs/ROADMAP.md](docs/ROADMAP.md).

## Arquitectura de datos

```text
upload, captura manual o sincronización
  → parser/conversor/generador
  → JSON estándar canónico
  → validación contra JSON Schema
  → preview/confirmación cuando aplica
  → importador oficial
  → MariaDB
```

Los schemas de [`schemas/`](schemas/) son el contrato público. Preview y generación asistida no escriben dominio. El usuario efectivo siempre proviene de la sesión o Bearer token, nunca del payload.

Más detalle: [contexto del producto](docs/PROJECT_CONTEXT.md) y [arquitectura](docs/architecture/OVERVIEW.md).

## Inicio rápido con Docker

Requisitos:

- El repositorio descargado o clonado.
- Docker Desktop o Docker Engine iniciado con contenedores Linux.
- Docker Compose v2, disponible mediante `docker compose`.

No necesitas instalar Python ni MariaDB en el equipo para este inicio rápido.

Desde la raíz del repositorio, crea `.env` a partir del ejemplo.

En PowerShell:

```powershell
Copy-Item .env.example .env
```

En Bash:

```bash
cp .env.example .env
```

Abre `.env` con tu editor antes de iniciar los servicios. Revisa todos sus valores y reemplaza cada valor `replace-with-...` por un secreto propio y robusto; no utilices los valores de ejemplo como credenciales de una instalación real. `ADMIN_USERNAME` y `ADMIN_PASSWORD` definen las credenciales del administrador que se crea durante el primer arranque si esa cuenta todavía no existe.

`.env` está ignorado por Git y debe permanecer solo en tu instalación: no lo añadas al repositorio, no lo compartas y no copies su contenido a prompts, tickets o logs.

Valida la configuración, construye e inicia los servicios:

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

Con el `APP_PORT=8000` incluido en `.env.example`, abre [http://localhost:8000](http://localhost:8000). Si cambias `APP_PORT`, usa ese puerto en la URL. Inicia sesión con los valores que configuraste en `ADMIN_USERNAME` y `ADMIN_PASSWORD`.

El contenedor `web` aplica las migraciones y crea el administrador inicial antes de iniciar el servidor. Para despliegue LAN/VPN y operación ampliada consulta [docs/ALPHA_DEPLOYMENT.md](docs/ALPHA_DEPLOYMENT.md), pero no necesitas esa guía para completar este inicio rápido. No expongas la aplicación directamente a Internet.

## Desarrollo local

Desde la raíz en PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
Set-Location backend
..\.venv\Scripts\python.exe -m compileall -q app tests
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m flask --app app:create_app db check
Set-Location ..
docker compose config --quiet
```

Las pruebas usan fixtures ficticias. No copies archivos reales a Git ni ejecutes QA destructiva contra los volúmenes persistentes del usuario.

## Documentación

Empieza en el [índice por dominio](docs/DOCUMENTATION_INDEX.md): distingue reglas canónicas, guías, protocolos, roadmap e historia.

- Uso: [primeros pasos](docs/GETTING_STARTED.md), [guía de usuario](docs/USER_GUIDE.md), [flujo diario](docs/DAILY_WORKFLOW.md).
- Importación: [Import Hub](docs/IMPORT_HUB.md), [archivos reales](docs/REAL_FILE_IMPORTS.md).
- Portabilidad: [data portability](docs/DATA_PORTABILITY.md), [backup integral](docs/FULL_BACKUP.md).
- API/companion: [API v1](docs/API_V1.md), [Mobile Sync](docs/MOBILE_SYNC.md), [Companion Protocol](docs/COMPANION_PROTOCOL_1_0.md).
- Operación: [despliegue alpha](docs/ALPHA_DEPLOYMENT.md), [checklist de release](docs/ALPHA_RELEASE_CHECKLIST.md).

Para agentes de desarrollo, [`AGENTS.md`](AGENTS.md) es el router breve. [`docs/ACTIVE_HANDOFF.md`](docs/ACTIVE_HANDOFF.md) solo se lee cuando hace falta continuidad del trabajo actual; no es una historia acumulativa.

## Seguridad y privacidad

- Los datos reales viven en `/data`, MariaDB o volúmenes locales ignorados por Git.
- No se versionan `.env`, dumps, exports, backups ni archivos personales.
- Toda consulta y artefacto sensible se filtra por owner.
- Backups/exports no incluyen contraseñas, sesiones ni tokens.
- La aplicación conserva información; no emite diagnósticos ni sustituye atención médica.
