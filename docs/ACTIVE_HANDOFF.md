# Handoff activo de Health Tracker

Documento temporal para retomar el bloque inmediato sin memoria previa.

Última actualización: 2026-07-08.

Este handoff no reemplaza:

- `../AGENTS.md`
- `AI_WORK_CONTEXT.md`
- `PROJECT_CONTEXT.md`
- `project-rules/canonical-data-contract-import-update.md`
- `project-rules/phase-5b-universal-json-import-assistant.md`
- `project-rules/standard-json-generator-development.md`

Si contradice a schemas, tests, código o reglas canónicas, este archivo pierde prioridad.

## Estado verificado

- Rama base: `master`.
- Rama documental actual: `docs/refresh-ai-context`.
- Rama de trabajo prevista para el siguiente bloque: `refactor/standard-json-generators`.
- Commit base verificado con `git rev-parse --short HEAD`: `0356d33`.
- Último merge conocido: `Merge branch 'feature/standard-json-generator-medical-lab'`.
- Estado del árbol antes del trabajo documental: limpio.
- Línea base verificada: `240 passed`.

Comando usado para verificar pruebas:

```powershell
cd backend
& '..\.venv\Scripts\python.exe' -m pytest -q
```

Resultado:

```text
240 passed
```

## Objetivo inmediato

Separar `StandardJsonGenerator` por dominio sin cambios funcionales.

La meta es reducir riesgo del archivo monolítico actual, manteniendo:

- mismas entradas;
- mismas salidas;
- mismos `target_type`;
- mismos `schema_name`;
- mismas reglas de validación;
- mismos warnings;
- mismos tests pasando.

No agregar dominios nuevos durante el refactor salvo instrucción explícita.

## Estado real de importación asistida

Archivos clave:

- `backend/app/services/importers/schema_detector.py`
- `backend/app/services/importers/universal_json_import_assistant.py`
- `backend/app/services/importers/standard_json_generator.py`
- `backend/app/services/importers/assisted_import_service.py`

Servicios verificados:

- `SchemaDetector` detecta schemas oficiales internos estrictamente.
- `UniversalJsonImportAssistant` detecta candidatos, aliases y mappings sugeridos.
- `StandardJsonGenerator` genera documentos estándar en memoria y valida contra schema.
- `AssistedImportService` orquesta preview read-only.

Todos estos servicios deben permanecer read-only en este bloque:

- no DB writes;
- no archivos;
- no `UploadedFile`;
- no importación real;
- no cambios en `/data`.

## Dominios actuales soportados

`StandardJsonGenerator.SUPPORTED_TARGETS`:

| `target_type` | `schema_name` | Nota |
| --- | --- | --- |
| `weigh_in_batch` | `weigh_in` | batch externo a documentos individuales `weigh_in` |
| `food_products` | `food_product` | productos individuales |
| `daily_energy` | `daily_energy` | documentos individuales |
| `completed_workout` | `completed_workout` | sesiones realizadas |
| `medical_lab` | `medical_lab` | reportes con marcadores |

Targets detectados por `UniversalJsonImportAssistant` pero sin generación estándar implementada todavía:

- `daily_nutrition`
- `training_plan`
- `recipe_bundle`

`recipe` existe como schema/importador/exportador de dominio, pero no es `target_type` directo en `SUPPORTED_TARGETS`.

## Archivos que probablemente se tocarán

Para el refactor por dominio:

- `backend/app/services/importers/standard_json_generator.py`
- nuevos módulos bajo `backend/app/services/importers/standard_generators/` o ruta equivalente simple;
- `backend/tests/test_standard_json_generator.py`
- `backend/tests/test_assisted_import_service.py`

Si solo se mueve código sin cambiar comportamiento, preferir pruebas existentes y pequeños tests de regresión donde el dispatch central pueda romperse.

## Archivos que no deben tocarse en ese bloque

Salvo necesidad demostrada:

- `schemas/*.schema.json`
- migraciones;
- modelos;
- routes;
- templates;
- Docker;
- `.env`;
- `/data`;
- importadores oficiales de escritura;
- exports no relacionados;
- tests de dominios no afectados.

## Restricciones

- No inventar campos requeridos.
- No usar placeholders para pasar validaciones.
- No cambiar contratos JSON públicos.
- No cambiar aliases canónicos salvo bug demostrado.
- No convertir preview en importación real.
- No hacer refactor grande fuera del generador.
- No hacer commit salvo pedido explícito del usuario.

## Riesgos conocidos

- `standard_json_generator.py` es monolítico.
- La resolución de paths padre/hijo puede cambiar resultados si se mueve sin tests.
- Los aliases deben mapear a campos canónicos, no filtrarse al JSON generado.
- `source_type` depende del schema de cada dominio.
- Existe riesgo de inventar requeridos accidentalmente al “arreglar” documentos inválidos.
- Si varios agentes modifican el dispatch central, pueden aparecer conflictos.
- Medical lab tiene lógica especial para subir desde paths de marcadores al reporte padre.

## Criterios de aceptación

El refactor se acepta si:

1. `SUPPORTED_TARGETS` conserva los mismos valores.
2. Cada dominio genera el mismo documento que antes.
3. La validación contra schema conserva los mismos resultados.
4. Los documentos incompletos siguen marcándose inválidos sin inventar campos.
5. `AssistedImportService` conserva sus modos actuales.
6. Las pruebas existentes de Fase 5B pasan.
7. La suite completa pasa.
8. `flask db check` queda limpio si se ejecuta.
9. `git diff --check` queda limpio.

## Comandos exactos de validación

Para cambios de backend:

```powershell
cd backend
python -m compileall -q .
python -m pytest -q tests/test_standard_json_generator.py tests/test_assisted_import_service.py tests/test_universal_json_import_assistant.py
python -m pytest -q
flask db check
cd ..
docker compose config --quiet
git diff --check
git status --short --branch
git diff --stat
git diff --name-only
```

Si Docker está disponible y el cambio toca comportamiento ejecutable:

```powershell
docker compose up --build -d
docker compose exec -T web flask db check
docker compose exec -T web python -m pytest -q
```

## Siguiente acción concreta

Crear o usar la rama:

```powershell
git switch -c refactor/standard-json-generators
```

Si la rama ya existe:

```powershell
git switch refactor/standard-json-generators
git status --short --branch
```

Después:

1. Extraer un generador por dominio empezando por `weigh_in_batch`.
2. Mantener dispatch central mínimo en `StandardJsonGenerator`.
3. Ejecutar pruebas específicas.
4. Repetir dominio por dominio.
5. No agregar `daily_nutrition`, `training_plan`, `recipe` ni `recipe_bundle` hasta que el refactor mecánico esté estable.

## Protocolo para cerrar el bloque

Al terminar:

1. Actualizar este handoff con rama, commit, pruebas y riesgos restantes.
2. Registrar dominios refactorizados.
3. Registrar si hubo cambios funcionales; idealmente debe decir “no”.
4. Registrar comandos ejecutados.
5. Confirmar que no se tocaron schemas, migraciones, `.env`, Docker ni `/data`.
