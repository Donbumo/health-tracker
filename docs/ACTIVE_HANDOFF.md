# Handoff activo de Health Tracker

Documento temporal para retomar el proyecto sin memoria previa.

Última actualización: 2026-07-08.

Este handoff no reemplaza:

- `../AGENTS.md`
- `AI_WORK_CONTEXT.md`
- `docs/PROJECT_CONTEXT.md`
- `project-rules/canonical-data-contract-import-update.md`
- `project-rules/phase-5b-universal-json-import-assistant.md`
- `project-rules/standard-json-generator-development.md`

Si contradice a schemas, tests, código o reglas canónicas, este archivo pierde prioridad.

## Estado verificado

- Rama base: `master`.
- Rama de trabajo: `refactor/standard-json-generators`.
- Base efectiva verificada: `597e703`.
- Estado del árbol antes del trabajo: limpio.
- Línea base previa conocida: `240 passed`.
- Resultado posterior al refactor: `240 passed`.

## Resumen del bloque

Se refactorizó `StandardJsonGenerator` para separar la generación estándar por dominio sin cambios funcionales intencionales.

`StandardJsonGenerator` conserva:

- API pública `generate(payload, candidate, *, user_id, source_type="uploaded", default_timezone="+00:00")`;
- `SUPPORTED_TARGETS`;
- dispatch central mínimo;
- validación contra JSON Schema;
- estructura de respuesta;
- wrappers privados compatibles para helpers usados antes del refactor.

No se agregaron nuevos dominios.

## Dominios extraídos

Targets soportados actuales:

| `target_type` | `schema_name` | módulo |
| --- | --- | --- |
| `weigh_in_batch` | `weigh_in` | `standard_generators/weigh_in.py` |
| `food_products` | `food_product` | `standard_generators/food_product.py` |
| `daily_energy` | `daily_energy` | `standard_generators/daily_energy.py` |
| `completed_workout` | `completed_workout` | `standard_generators/completed_workout.py` |
| `medical_lab` | `medical_lab` | `standard_generators/medical_lab.py` |

Utilidades compartidas:

- `standard_generators/common.py`

Targets detectados por `UniversalJsonImportAssistant` pero todavía no soportados por `StandardJsonGenerator`:

- `daily_nutrition`
- `training_plan`
- `recipe_bundle`

`recipe` existe como schema/importador/exportador de dominio, pero no es `target_type` directo en `SUPPORTED_TARGETS`.

## Archivos tocados

Código:

- `backend/app/services/importers/standard_json_generator.py`
- `backend/app/services/importers/standard_generators/__init__.py`
- `backend/app/services/importers/standard_generators/common.py`
- `backend/app/services/importers/standard_generators/weigh_in.py`
- `backend/app/services/importers/standard_generators/food_product.py`
- `backend/app/services/importers/standard_generators/daily_energy.py`
- `backend/app/services/importers/standard_generators/completed_workout.py`
- `backend/app/services/importers/standard_generators/medical_lab.py`

Documentación temporal:

- `docs/ACTIVE_HANDOFF.md`

No se modificaron tests en este bloque.

## Restricciones vigentes

- No tocar `/data`.
- Mantener aislamiento por `user_id`.
- No leer, mostrar, copiar ni resumir `.env`.
- No inventar campos requeridos.
- No usar placeholders para pasar validaciones.
- No cambiar contratos JSON públicos.
- No cambiar aliases canónicos salvo bug demostrado.
- No convertir preview en importación real.
- No hacer commit salvo pedido explícito del usuario.

## Validación ejecutada

El venv local no arrancó dentro del sandbox con `.\.venv\Scripts\python.exe`; las validaciones Python se ejecutaron fuera del sandbox con aprobación.

Desde `backend/`:

```powershell
& '..\.venv\Scripts\python.exe' -m pytest tests/test_standard_json_generator.py tests/test_assisted_import_service.py tests/test_universal_json_import_assistant.py -q
```

Resultado:

```text
31 passed
```

```powershell
& '..\.venv\Scripts\python.exe' -m pytest tests/test_medical_lab_importer.py tests/test_medical_lab_schema.py tests/test_standard_json_generator.py tests/test_assisted_import_service.py -q
```

Resultado:

```text
31 passed
```

```powershell
& '..\.venv\Scripts\python.exe' -m compileall -q .
& '..\.venv\Scripts\python.exe' -m pytest -q
```

Resultado:

```text
240 passed
```

## Riesgos o deuda restante

- `standard_json_generator.py` sigue siendo el dispatch central; coordinar cambios si varios agentes trabajan en paralelo.
- La resolución de paths padre/hijo sigue siendo sensible, especialmente en `medical_lab`.
- Los aliases deben seguir viviendo en detección/normalización, no en el JSON generado.
- `source_type` depende del schema de cada dominio.
- Restore/import real aún no existe y no debe inferirse desde el preview read-only.

## Siguiente acción concreta

1. Revisar el diff.
2. Ejecutar `git diff --check`.
3. Si el usuario lo pide, hacer commit del refactor.
4. Próximo bloque recomendado: generación estándar de `daily_nutrition` en una rama separada.
