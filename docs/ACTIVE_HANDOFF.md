# Handoff activo de Health Tracker

Documento temporal para retomar el proyecto sin memoria previa.

Ultima actualizacion: 2026-07-10.

Este handoff no reemplaza:

- `../AGENTS.md`
- `AI_WORK_CONTEXT.md`
- `docs/PROJECT_CONTEXT.md`
- `project-rules/canonical-data-contract-import-update.md`
- `project-rules/phase-5b-universal-json-import-assistant.md`
- `project-rules/standard-json-generator-development.md`
- `project-rules/confirmed-standard-import.md`

Si contradice schemas, tests, codigo o reglas canonicas, este archivo pierde prioridad.

## Estado verificado del bloque activo

- Rama de trabajo: `feature/overnight-backend-qa-closure`.
- Base efectiva verificada: `e356001`.
- Arbol antes del trabajo: limpio.
- Suite base local antes de modificar: `304 passed`.
- Baseline Docker conocido antes de esta rama: `303 passed, 1 skipped`.
- Skip Docker esperado: `tests/test_active_handoff.py`, porque `docs/` no se copia a la imagen de produccion.
- No hubo migraciones.
- No se tocaron schemas, modelos, Docker, `.env` ni `/data`.

## Objetivo de esta rama

Cerrar trabajo backend seguro y verificable alrededor de la importacion estandar confirmada, sin cambiar schemas publicos ni implementar restore completo.

### Milestone A: QA automatizado de targets restantes

Targets priorizados en esta rama:

| Target | Cobertura agregada |
| --- | --- |
| `daily_energy` | Preview autodetectado, alias `distancia_km`, insert, repeat/skip, update parcial, batch invalido, `user_id` ajeno. |
| `training_plan` | Preview con parent paths, versionado insert/skip/update, SHA estable, orden invalido, aislamiento. |
| `completed_workout` | Plan/version del usuario, referencias ajenas, mismatch plan/version, campos ampliados, conflict en repeat/update inseguro, rollback tras flush. |
| `medical_lab` | Preview autodetectado, insert/skip/update, reemplazo de markers, valores numericos/texto, invalidos, batch invalido, aislamiento. |

Tambien se endurecio el resumen de commit invalido/conflictivo para conservar el mensaje generico compatible y agregar detalles de las operaciones bloqueadas.

### Milestone B: fixtures manuales de QA

Se agrego paquete ficticio bajo:

```text
examples/qa/standard-import/
```

Incluye README raiz y README por dominio para:

- `daily_energy`
- `training_plan`
- `completed_workout`
- `medical_lab`

Cada dominio contiene fixtures de insert, repeat/update/conflict cuando aplica, invalidos, batch valido y batch mixto. Los fixtures son ficticios y no deben copiarse a `/data`.

## Targets finales del flujo estandar

| `target_type` | `schema_name` | modulo |
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

## Contrato actual de importacion confirmada

`StandardImportExecutor` es la fase posterior a 5B:

- preview, deteccion, mapping y generacion siguen siendo read-only;
- recibe documentos estandar ya generados;
- vuelve a validar schema y `user_id`;
- construye plan `insert/update/skip/conflict/invalid`;
- exige confirmacion explicita;
- firma confirmacion contra usuario, target, payload y plan;
- rechaza tokens reutilizados, vencidos o de otro usuario;
- ejecuta lote atomico;
- hace rollback si falla un elemento durante escritura;
- no cambia el destino desde `user_id` incluido en archivo.

Ruta web minima:

```text
GET/POST /imports/standard
```

Flujo:

```text
login -> subir JSON -> preview -> plan -> confirmar -> commit -> resumen
```

## Restricciones vigentes

- No tocar `/data`.
- No leer ni mostrar `.env`.
- No usar datos reales.
- Mantener aislamiento por `user_id`.
- No inventar requeridos.
- No hacer commit ni push salvo pedido explicito.
- No implementar restore real todavia.
- Restore/import real aÃºn no existe para respaldos completos de usuario.
- Restore/import real aún no existe para respaldos completos de usuario. Esta linea conserva compatibilidad con una prueba historica de handoff.
- No implementar ImportJob/ImportRun sin aprobacion de migracion.

## Riesgos conocidos

- `StandardImportExecutor` no sustituye restore completo de usuario.
- La auditoria persistente rica queda pendiente; no hay tabla nueva de ImportRun/ImportJob.
- Algunos updates por dominio usan claves naturales existentes; si un dominio necesita reglas mas finas, debe endurecerse con pruebas.
- `recipe` y `recipe_bundle` requieren productos existentes cuando se importan realmente.
- `completed_workout` no admite update seguro; los cambios conflictivos se bloquean.
- Los fixtures `completed_workout` usan IDs ficticios de plan/version y QA debe reemplazarlos por IDs propios.
- Docker omite docs, por eso `tests/test_active_handoff.py` puede aparecer como skip esperado en imagen.

## Validacion esperada para cerrar este bloque

```powershell
& '.\.venv\Scripts\python.exe' -m compileall -q backend
& '.\.venv\Scripts\python.exe' -m pytest backend/tests/ -q
flask db check
docker compose config --quiet
docker compose up --build -d
docker compose exec -T web flask db check
docker compose exec -T web python -m pytest -q
git diff --check
git diff --stat
git diff --name-status
git status --short --branch
```

## Siguiente accion concreta

1. Ejecutar validacion local completa y Docker.
2. Probar manualmente `/imports/standard` con fixtures de `examples/qa/standard-import/`.
3. Si todo esta verde, commit sugerido:

```text
test: close backend qa for standard imports
```

## Protocolo al cerrar el bloque

Actualizar este archivo con:

- commit final si se crea;
- suite final local y Docker;
- skip exacto si existe;
- riesgos nuevos;
- siguiente fase recomendada.
