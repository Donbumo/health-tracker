# Instrucciones locales de backend

Aplican a todo `backend/` además del `AGENTS.md` raíz.

## Antes de editar

- Identifica el dominio y lee solo su regla en `../docs/project-rules/`.
- Revisa modelos, servicios, rutas y pruebas existentes antes de crear una abstracción o migración.
- Si la tarea toca un contrato JSON, lee también `../schemas/AGENTS.md`.

## Persistencia y seguridad

- Toda consulta owner-only debe filtrar por el `user_id` efectivo de la sesión o Bearer token. Los IDs o `user_id` del payload no conceden autoridad.
- Mantén preview/detección/generación separados de la escritura. Los parsers y generadores no hacen commit.
- Las operaciones batch confirmadas deben ser atómicas o declarar de forma explícita su contrato por elemento; no dejes éxito parcial silencioso.
- Conserva uploads originales, SHA256, fuente y auditoría según la regla del dominio, sin registrar payloads sensibles.
- No serialices ORM directamente hacia contratos públicos; usa allowlists y nombres canónicos.

## Modelos y migraciones

- No generes migración si no cambian tablas, columnas, índices o constraints.
- Si el modelo cambia, crea una migración Alembic aditiva y reversible cuando sea viable.
- Mantén un solo head y compatibilidad con SQLite de pruebas y MariaDB de producción.
- Nunca pruebes migraciones destructivas contra el stack persistente del usuario sin autorización explícita.

## Pruebas

- Agrega o actualiza pruebas con datos ficticios para el comportamiento modificado.
- Incluye aislamiento entre dos usuarios cuando cambien consultas, imports, exports, APIs o archivos.
- Usa la suite específica primero y la completa cuando sea razonable.

Desde `backend/`:

```powershell
..\.venv\Scripts\python.exe -m compileall -q app tests
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m flask --app app:create_app db check
```

Desde la raíz:

```powershell
docker compose config --quiet
git diff --check
```

Usa Docker/MariaDB aislado cuando el cambio dependa del motor, migraciones, concurrencia o comportamiento del contenedor.
