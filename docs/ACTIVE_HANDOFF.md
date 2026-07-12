# Handoff activo de Health Tracker

Documento temporal para retomar el proyecto sin memoria previa.

Ultima actualizacion: 2026-07-11.

Este handoff no reemplaza:

- `../AGENTS.md`
- `AI_WORK_CONTEXT.md`
- `docs/PROJECT_CONTEXT.md`
- `project-rules/canonical-data-contract-import-update.md`
- `project-rules/phase-5b-universal-json-import-assistant.md`
- `project-rules/standard-json-generator-development.md`
- `project-rules/confirmed-standard-import.md`
- `project-rules/account-restore.md`
- `ACCOUNT_RESTORE.md`
- `DATA_PORTABILITY.md`

Si contradice schemas, tests, codigo o reglas canonicas, este archivo pierde prioridad.

## Bloque activo

- Rama de trabajo: `feature/backend-complete-roundtrip`.
- Base efectiva verificada: `fd23e7b`.
- Base esperada por el usuario: `master` posterior a `feature/import-ai-prompt-helpers`.
- Arbol antes del trabajo: limpio.
- Baseline local previa conocida: `370 passed`.
- Baseline local tras primer pase de este bloque: `374 passed`.
- Baseline local tras segundo pase de este bloque: `399 passed`.
- Baseline Docker tras segundo pase: `398 passed, 1 skipped` (`tests/test_active_handoff.py`, porque `docs/` no se copia a la imagen).
- No se tocaron schemas, modelos, migraciones, Docker, `.env` ni `/data`.
- No se hizo commit ni push.
- Regla fuerte: No tocar `/data`.

## Objetivo del bloque

Implementar portabilidad backend end-to-end para Alpha privada:

```text
export completo -> preview restore -> confirmacion firmada -> commit atomico -> uso real en pantallas -> export repetible
```

## Implementado en esta rama

- Servicio `AccountRestoreService`.
- Rutas:
  - `GET /account/data`
  - `GET/POST /account/restore`
  - `POST /account/restore/confirm`
- Export completo ahora incluye seccion `recipes`.
- Restore merge seguro desde `user_data_export`.
- Remapeo en memoria de IDs antiguos a IDs del usuario autenticado para:
  - `training_plans`
  - `training_plan_versions`
  - `training_sessions`
- Auditoria saneada con `ImportRun.target_type = user_data_restore`.
- Data center de cuenta con export, restore, import estándar, historial y último audit run.
- Límites defensivos de JSON: tamaño, profundidad, nodos, arrays, strings, claves y secciones.
- Validación de schema version antes de schema general para rechazar exports futuros con mensaje claro.
- Token de restore ligado a versión, modo, usuario, schema, payload y plan; la web evita reutilización accidental por sesión.
- Recetas restauradas validan referencias a productos existentes o incluidos en el mismo export.
- Pruebas de round-trip, idempotencia, token manipulado/reutilizado, límites, referencias faltantes, flujo web y pantallas post-restore.

## Secciones del export y politica actual

| Seccion | Restore |
| --- | --- |
| `food_products` | insert/update/skip por nombre + marca |
| `recipes` | insert/update/skip por nombre; ingredientes por nombre/marca de producto |
| `weigh_ins` | insert/update/skip por usuario + fecha/hora + fuente |
| `daily_energy` | insert/update/skip por usuario + fecha |
| `daily_nutrition` | insert/update/skip por usuario + fecha |
| `medical_lab_reports` | insert/update/skip por usuario + fecha + laboratorio |
| `training_plans` | insert/skip/update por nombre y SHA de versiones |
| `training_sessions` | insert/skip; update inseguro sigue siendo conflicto |
| `daily_balances` | omitido, derivado |
| `uploads` | omitido, metadata sin binarios |

## Garantias vigentes

- El usuario/email/rol del export se ignoran.
- El `user_id` efectivo siempre proviene de la sesion autenticada.
- Preview no escribe DB ni guarda archivos.
- Confirmacion se firma contra usuario, modo, version, schema, payload y plan.
- Commit es atomico; ante error hace rollback.
- `pending` queda persistido antes de mutaciones de dominio y `failed` se escribe con transaccion limpia tras rollback.
- No se guardan payloads crudos, tokens, trazas ni datos sensibles en `ImportRun`.
- Restore no toca `/data` ni restaura archivos binarios.

## Riesgos y pendientes

- No hay restore ZIP ni restore de binarios de uploads.
- No hay borrado masivo; el modo actual es merge.
- La equivalencia semantica round-trip ignora IDs, timestamps y derivados.
- `training_sessions` conserva update como conflicto salvo repeticion equivalente.
- Si se agregan nuevos dominios al export, deben añadirse explicitamente a restore y pruebas.
- `AccountRestoreService` sigue siendo un merge, no una sincronizacion espejo.
- La proteccion anti-replay de tokens es por sesion web; tokens viejos tambien se invalidan por expiracion y hash de payload/plan.
- Nota de compatibilidad con prueba historica: la frase `Restore/import real aún no existe` ya no describe este bloque para restore de `user_data_export`; sigue aplicando a restore ZIP/binarios.
- Nota de compatibilidad legacy: `Restore/import real aÃºn no existe`.

## Validacion esperada

```powershell
& '.\.venv\Scripts\python.exe' -m compileall -q backend
& '.\.venv\Scripts\python.exe' -m pytest backend/tests/ -q
docker compose config --quiet
docker compose up --build -d
docker compose exec -T web flask db check
docker compose exec -T web python -m pytest -q
git diff --check
git diff --stat
git diff --name-status
git status --short --branch
```

Si pytest no esta instalado en la imagen:

```powershell
docker compose exec -T --user root web sh -lc "pip install --no-cache-dir -r requirements-dev.txt && python -m pytest -q -rs"
```

Skip Docker esperado si aparece: `tests/test_active_handoff.py`, porque `docs/` no se copia a la imagen de produccion.

## Siguiente accion concreta

1. Ejecutar validacion Docker final.
2. Probar manualmente:
   - crear/usar cuenta QA;
   - exportar `/account/export.json`;
   - restaurar en otra cuenta desde `/account/restore`;
   - abrir dashboard, peso, nutricion, energia, recetas, rutinas, sesiones, progreso y laboratorios;
   - repetir restore y confirmar que no duplica.
3. Si todo queda verde, commit sugerido:

```text
feat: add account data restore roundtrip
```
