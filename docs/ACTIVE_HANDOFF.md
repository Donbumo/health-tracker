# Handoff activo de Health Tracker

Documento vivo para retomar el proyecto sin memoria previa. Antes de cambiar código, leer en este orden:

1. `AGENTS.md`
2. `docs/PROJECT_CONTEXT.md`
3. `docs/ACTIVE_HANDOFF.md`
4. `git status` y `git log --oneline -20`

## Estado actual

Health Tracker es una aplicación Flask privada, self-hosted y multiusuario. Usa SQLAlchemy, Flask-Migrate, MariaDB y Docker Compose. El MVP web funciona en `http://localhost:8000` y mantiene aislamiento por `user_id`.

El último commit que debe incorporarse a `master` antes de esta fase es:

```text
a4d387c feat: harden qa operations and user exports
```

La rama activa para portabilidad es `feature/handoff-data-portability`. Si el hash o la rama difieren, revisar primero el historial; no reescribir ni descartar cambios automáticamente.

## Módulos implementados

- Auth y admin: login por email/username, logout POST con CSRF, roles `admin/user`, creación básica de usuarios y diagnóstico `/admin/system`.
- Uploads: originales por usuario, SHA256, deduplicación, tipo detectado, estado y error de importación.
- Entrenamiento: rutinas JSON, versiones inmutables, activación, historial y exports JSON/CSV.
- Sesiones: captura/importación, versión exacta del plan, series, peso, reps, RIR, RPE, descanso, duración, FC y calorías.
- Progreso: volumen, reps, peso máximo, Epley, comparación, fatiga, estancamiento e identidades/aliases privados.
- Nutrición y energía: persistencia diaria, comidas/items, captura/importación, balance y exports.
- Peso y composición: captura/importación, historial, tendencia y exports.
- Dashboard: resumen diario consolidado de nutrición, energía, peso, entrenamiento y último laboratorio.
- Laboratorios: schema, importación/captura, reportes, marcadores, historial y exports JSON/CSV.
- QA/ops: seed demo, `/healthz`, logs Gunicorn configurables, smoke tests y estados vacíos.
- Portabilidad: `/account/export.json` genera un respaldo JSON del usuario sin hashes de contraseña, secretos, rutas internas ni binarios.

## Ramas recientes

- `feature/web-qa-mvp`: navegación, dashboard QA, seed demo y smoke tests.
- `feature/medical-lab-core`: reportes y marcadores de laboratorio.
- `feature/qa-ops-hardening`: logout preventivo, healthcheck, diagnóstico admin y export completo.
- `feature/handoff-data-portability`: schema del export y preview dry-run; no debe restaurar datos.

## Reglas fuertes

- Leer los tres documentos de contexto antes de modificar.
- No tocar `/data`, volúmenes ni datos reales.
- No crear ejemplos con información personal, médica o de salud real.
- No incluir secretos, tokens, `.env` ni hashes de contraseña.
- Filtrar toda consulta sensible por `user_id`.
- No hacer refactors grandes ni cambiar arquitectura sin autorización.
- Crear migración solo al cambiar tablas o columnas.
- No usar `git reset --hard`, `git clean` ni `docker compose down -v`.
- Agregar pruebas y detener la siguiente fase si fallan.

## Comandos habituales

Desde `backend/` para pruebas locales:

```powershell
python -m compileall -q .
python -m pytest -q
flask db check
```

Desde la raíz:

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose exec web flask db upgrade
docker compose exec web flask seed demo
docker compose exec -T web flask db check
```

`pytest` no forma parte de la imagen de producción. Si se necesita dentro del contenedor, instalar temporalmente `requirements-dev.txt` y documentarlo.

## QA web

- URL: `http://localhost:8000`
- Cuenta ficticia: `demo@example.com` / `demo12345`
- Healthcheck: `/healthz`
- Diagnóstico admin: `/admin/system`
- Export del usuario: `/account/export.json`

Flujos recomendados:

1. Login y logout repetido.
2. Dashboard vacío, parcial y demo.
3. Captura/importación de peso, energía, nutrición y laboratorio.
4. Importación/versionado de rutina y registro de sesión.
5. Progreso por ejercicio y aislamiento con una segunda cuenta.
6. Exports JSON/CSV y export completo de cuenta.
7. Preview dry-run del export cuando esté disponible; verificar que no altera conteos.

## Mapa de módulos y rutas

```text
backend/app/auth/        /login, POST /logout
backend/app/admin/       /admin/users, /admin/system
backend/app/main/        /, /dashboard, /uploads, /healthz,
                         /account/export.json
backend/app/body/        /weigh-ins, historial, import/export
backend/app/wellness/    /daily-nutrition, /daily-energy, /daily-balance
backend/app/training/    /training-plans, versiones e import/export
backend/app/sessions/    /training-sessions e import/export
backend/app/progress/    /progress y análisis
backend/app/medical/     /medical/labs y /medical/markers
backend/app/services/    validación, importadores, exportadores y análisis
schemas/                 contratos JSON Draft 2020-12
```

## Próximas fases recomendadas

1. Formalizar `user_data_export.schema.json` y validar el export al generarlo.
2. Preview dry-run autenticado con resumen, advertencias y cero escrituras.
3. Diseñar restore real en una fase separada, con mapeo de IDs, transacción y rollback explícitos.
4. Añadir streaming o export por lotes antes de usar cuentas con historiales grandes.
5. Mantener fuera de alcance API REST, ZIP, FIT/GPX reales, móvil, reloj, OCR y FHIR hasta autorización.

## Cómo preparar un nuevo agente

Entregarle `AGENTS.md`, `docs/PROJECT_CONTEXT.md`, este archivo, `git status` y `git log --oneline -20`. Pedir cambios por fases pequeñas, exigir pruebas después de cada fase y prohibir restore/escrituras si la tarea solo habla de preview.

## Riesgos conocidos

- El export completo se construye en memoria; historiales grandes pueden consumir RAM.
- Restore/import real aún no existe y no debe inferirse desde el preview.
- `pytest` no está en la imagen de producción y su instalación en Docker es temporal.
- Un timeout previo de Gunicorn durante logout no fue reproducible; las regresiones de logout pasan y los logs operativos quedaron reforzados.
- El contexto histórico en `PROJECT_CONTEXT.md` está desactualizado frente al código; para estado ejecutable mandan pruebas, Git y este handoff.
