# Handoff activo de Health Tracker

Documento temporal para retomar el proyecto sin memoria previa.

Última actualización: 2026-07-09.

Este handoff no reemplaza:

- `../AGENTS.md`
- `AI_WORK_CONTEXT.md`
- `docs/PROJECT_CONTEXT.md`
- `project-rules/canonical-data-contract-import-update.md`
- `project-rules/phase-5b-universal-json-import-assistant.md`
- `project-rules/standard-json-generator-development.md`
- `project-rules/confirmed-standard-import.md`

Si contradice schemas, tests, código o reglas canónicas, este archivo pierde prioridad.

## Estado verificado del bloque activo

- Rama de trabajo: `feature/complete-phase-5b-and-qa-imports`.
- Base efectiva verificada: `a2c7664`.
- Árbol antes del trabajo: limpio.
- Suite base verificada antes de modificar: `250 passed`.
- Suite local posterior al cambio: `289 passed`.
- Suite Docker posterior al cambio: `288 passed, 1 skipped` (`tests/test_active_handoff.py`, documentación no copiada a imagen de producción).
- No hubo migraciones.
- No se tocaron schemas, modelos, Docker, `.env` ni `/data`.

## Objetivo implementado

### Milestone A: cierre de Fase 5B

Fase 5B sigue siendo read-only:

- detección;
- mapping asistido;
- generación estándar;
- validación.

Targets finales soportados por `StandardJsonGenerator`:

| `target_type` | `schema_name` | módulo |
| --- | --- | --- |
| `weigh_in_batch` | `weigh_in` | `standard_generators/weigh_in.py` |
| `food_products` | `food_product` | `standard_generators/food_product.py` |
| `daily_energy` | `daily_energy` | `standard_generators/daily_energy.py` |
| `daily_nutrition` | `daily_nutrition` | `standard_generators/daily_nutrition.py` |
| `completed_workout` | `completed_workout` | `standard_generators/completed_workout.py` |
| `medical_lab` | `medical_lab` | `standard_generators/medical_lab.py` |
| `training_plan` | `training_plan` | `standard_generators/training_plan.py` |
| `recipe` | `recipe` | `standard_generators/recipe.py` |
| `recipe_bundle` | `recipe_bundle` | `standard_generators/recipe_bundle.py` |

### Milestone B: importación estándar confirmada

Se agregó `StandardImportExecutor` como fase posterior a 5B:

- recibe documentos estándar;
- vuelve a validar schema y `user_id`;
- construye plan `insert/update/skip/conflict/invalid`;
- exige confirmación explícita;
- firma la confirmación contra usuario, target, payload y plan;
- rechaza tokens reutilizados, vencidos o de otro usuario;
- ejecuta lote atómico;
- hace rollback si falla un elemento durante la escritura;
- devuelve resumen estructurado;
- no cambia el `user_id` destino desde el archivo.
- usa adaptadores internos de persistencia, no importadores oficiales que hacen commit propio, para conservar atomicidad de lote.

Ruta web mínima:

```text
GET/POST /imports/standard
```

Flujo:

```text
login -> subir JSON -> preview -> plan -> confirmar -> commit -> resumen
```

## Archivos principales tocados

- `backend/app/services/importers/standard_json_generator.py`
- `backend/app/services/importers/universal_json_import_assistant.py`
- `backend/app/services/importers/standard_generators/`
- `backend/app/services/importers/standard_import_executor.py`
- `backend/app/main/forms.py`
- `backend/app/main/routes.py`
- `backend/app/templates/imports/standard.html`
- `backend/app/templates/base.html`
- `backend/tests/test_standard_json_generator.py`
- `backend/tests/test_assisted_import_service.py`
- `backend/tests/test_universal_json_import_assistant.py`
- `backend/tests/test_standard_import_executor.py`
- `backend/tests/test_standard_import_web.py`
- `docs/project-rules/confirmed-standard-import.md`

## Restricciones vigentes

- No tocar `/data`.
- No leer ni mostrar `.env`.
- No usar datos reales.
- Mantener aislamiento por `user_id`.
- No inventar requeridos.
- No hacer commit ni push salvo pedido explícito.
- No implementar restore real todavía.
- Restore/import real aún no existe para respaldos completos de usuario.
- No implementar ImportJob/ImportRun sin aprobación de migración.

## Riesgos conocidos

- `StandardImportExecutor` no sustituye restore completo de usuario.
- La auditoría persistente rica queda pendiente; hoy no se agregó tabla nueva.
- El refactor futuro ideal es compartir adaptadores `commit=False` entre importadores oficiales y `StandardImportExecutor`.
- Algunos updates por dominio usan claves naturales existentes; si un dominio necesita reglas más finas, debe endurecerse con pruebas.
- `recipe` y `recipe_bundle` requieren productos existentes cuando se importan realmente.
- `recipe_bundle` se planea por receta embebida; el resumen conserva `recipe_index`.
- `completed_workout` no admite update seguro; los cambios conflictivos se bloquean.
- Se restauraron aliases históricos de `training_plan` (`series_objetivo`, `reps_objetivo`, `rir_objetivo`, `rpe_objetivo`, `descanso_objetivo`, `version`, `bloques`) sin inventar campos fuera del schema.

## Validación ejecutada

```powershell
& '.\.venv\Scripts\python.exe' -m compileall -q backend
& '.\.venv\Scripts\python.exe' -m pytest backend/tests/test_standard_json_generator.py backend/tests/test_assisted_import_service.py backend/tests/test_universal_json_import_assistant.py -q
& '.\.venv\Scripts\python.exe' -m pytest backend/tests/test_standard_import_executor.py backend/tests/test_standard_import_web.py backend/tests/test_standard_json_generator.py backend/tests/test_assisted_import_service.py backend/tests/test_universal_json_import_assistant.py -q
& '.\.venv\Scripts\python.exe' -m pytest backend/tests/ -q
```

Resultados:

```text
80 passed
289 passed
Docker: 288 passed, 1 skipped
```

## Siguiente acción concreta

1. Revisar diff.
2. Ejecutar validaciones finales (`compileall`, suite, `flask db check`, Docker si está disponible).
3. Probar manualmente `/imports/standard` con el usuario demo o un usuario creado desde admin.
4. Si todo está correcto, commit sugerido:

```text
feat: complete phase 5b and confirmed standard imports
```

## Protocolo al cerrar el bloque

Actualizar este archivo con:

- commit final si se crea;
- suite final;
- cualquier riesgo nuevo;
- siguiente fase recomendada.
