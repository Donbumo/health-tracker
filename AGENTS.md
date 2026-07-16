# AGENTS.md

## Instrucciones principales para agentes de código

Antes de modificar el proyecto, lee primero:

- `docs/project-rules/api-v1.md` cuando la tarea toque `/api/v1`, Bearer, dispositivos o sincronización companion
- `docs/project-rules/companion-protocol.md` cuando la tarea toque perfiles, negociación, packages, deliveries o checkpoints companion
- `docs/AI_WORK_CONTEXT.md`
- `docs/PROJECT_CONTEXT.md`
- `docs/project-rules/canonical-data-contract-import-update.md`
- `docs/project-rules/phase-5b-universal-json-import-assistant.md`
- `docs/project-rules/standard-json-generator-development.md` cuando la tarea toque Fase 5B, detección, aliases, `StandardJsonGenerator`, `UniversalJsonImportAssistant` o `AssistedImportService`
- `docs/project-rules/exporters.md` cuando la tarea toque exports, storage generated, `ExportRecord`, GPX/TCX de salida, PDF o ZWO/ERG/MRC
- `docs/project-rules/web-ui.md` cuando la tarea toque Jinja, navegación, CSS, dashboard o flujos web
- `docs/project-rules/workout-load-entry.md` cuando la tarea toque cargas por serie, unidades, perfiles de ejercicio, `weight_kg` o `load_details`
- `docs/project-rules/workout-session-recovery.md` cuando la tarea toque captura web de sesiones, CSRF recuperable, borradores o `client_submission_id`

`docs/PROJECT_CONTEXT.md` contiene la visión completa del producto, arquitectura, módulos, fases, schemas, importadores, exportadores, reglas de privacidad y estado actual del desarrollo.

`docs/project-rules/canonical-data-contract-import-update.md` contiene la regla transversal para contratos canónicos de datos, importación individual/masiva, aliases, exportación redonda, duplicados y actualización consistente.

`docs/project-rules/phase-5b-universal-json-import-assistant.md` contiene las reglas para el importador asistido universal de JSON no estándar.

`docs/AI_WORK_CONTEXT.md` ordena el contexto operativo actual, precedencia entre documentos y reglas de handoff para agentes.

`docs/project-rules/standard-json-generator-development.md` contiene reglas específicas para desarrollo del generador estándar: schemas como contrato, aliases fuera del JSON generado, no inventar requeridos y preview read-only.

## Reglas de trabajo

- No inventes datos reales de salud, nutrición, entrenamiento, médicos o personales.
- No agregues datos reales al repositorio.
- No subas ni generes archivos reales dentro de Git que pertenezcan a usuarios.
- Todo dato real debe vivir en `/data` o en volúmenes Docker ignorados por Git.
- No toques `/data`.
- No leas, muestres, copies ni resumas `.env`.
- Mantén aislamiento por `user_id`.
- Antes de cambiar modelos o migraciones, revisa si realmente se necesita una migración.
- Si agregas tablas o columnas, crea migración Alembic/Flask-Migrate.
- Si no agregas tablas ni columnas, no generes migraciones innecesarias.
- Conserva compatibilidad con Docker Compose y MariaDB.
- Evita romper pruebas existentes.
- Cuando agregues funcionalidades, agrega o actualiza pruebas.
- Usa fixtures ficticias en tests.
- No uses datos médicos, corporales, alimentarios o personales reales en ejemplos.
- No uses datos personales reales en tests.
- No inventes campos requeridos para satisfacer schemas. Si falta un requerido, genera o procesa solo lo disponible y deja que la validación marque el documento como inválido.
- No uses placeholders como `Unknown`, `N/A`, `dummy`, `fallback`, `1` o `0` para completar datos requeridos.
- No agregues carpetas o archivos por error; si aparece un untracked sospechoso como `chemas`, no lo agregues sin confirmar.
- No reescribas archivos completos sin necesidad. Preserva reglas únicas y parchea solo lo obsoleto, contradictorio o incompleto.
- No hagas commit salvo que el usuario lo solicite explícitamente.

## Pipeline obligatorio de datos

Todo dato debe pasar por un flujo auditable:

```text
Archivo subido
  o
Captura manual
  o
Sincronización desde app/dispositivo
        ↓
Conversor / generador
        ↓
Archivo estándar interno
        ↓
Validación contra JSON Schema
        ↓
Importador oficial
        ↓
MariaDB
```

Ningún importador auxiliar debe escribir directamente a la base de datos si puede generar un JSON estándar y delegar en el importador oficial.

## Regla de contrato canónico

Cada módulo debe tener un único contrato canónico de JSON.

Ese contrato canónico es la fuente de verdad pública para archivos importables/exportables.

La base de datos puede usar nombres internos distintos, pero esos nombres nunca deben filtrarse como contrato externo si ya existe un nombre JSON canónico.

Ejemplo:

```text
UI: Agua corporal
JSON canónico: water_percent
DB/modelo: water_percentage
Aliases externos aceptables: agua_pct, agua_corporal_pct, body_water_percent, water_percentage, water_pct
Campo estándar generado: water_percent
```

Los aliases solo deben usarse en la capa de normalización o importación asistida. El JSON estándar interno siempre debe usar el campo canónico.

## Regla para JSON estándar vs JSON no estándar

Cuando se suba un JSON:

1. Intentar detectar si coincide con un schema interno oficial.
2. Si coincide, usar el importador estándar del módulo.
3. Si no coincide, no debe tronar con un error genérico.
4. Debe marcarse como candidato para importación asistida.
5. El flujo asistido debe usar `UniversalJsonImportAssistant`.
6. El asistente debe producir detección, mapping sugerido, preview, advertencias y JSON estándar generado.
7. El JSON generado por el asistente debe usar nombres canónicos, no aliases.
8. La escritura final debe pasar por el importador oficial correspondiente.

El `UniversalJsonImportAssistant` nunca debe escribir directamente en MariaDB.

## Importación individual, masiva y actualización

Todo módulo debe soportar conceptualmente:

- Importación individual.
- Importación masiva o batch.
- Detección de duplicados.
- Política explícita de create/update/upsert.
- Preview obligatorio para importación asistida o masiva.
- Round-trip: crear manualmente, exportar, reimportar y conservar contrato.

Estrategias permitidas para registros existentes:

```text
skip
merge_missing
overwrite
create_new
fail
ask_user
```

Política recomendada:

```text
Importación automática: skip o merge_missing.
Importación asistida: ask_user.
Importación masiva: preview con nuevos, duplicados, actualizables y conflictivos.
```

## Fase 5B: Importador asistido universal

El proyecto incluye como bloque transversal:

```text
Fase 5B: Importador asistido universal de JSON no estándar
```

Objetivo:

```text
Flexible para recibir archivos
Estricto para validar
Claro para previsualizar
Seguro para importar
Auditable para rastrear
```

La regla de contrato canónico tiene prioridad sobre cualquier ejemplo del importador asistido. Si un ejemplo usa un alias como `body_water_percent`, pero el contrato canónico real es `water_percent`, el asistente debe generar `water_percent`.

## Importadores oficiales

La escritura final debe pasar por importadores oficiales como:

```text
WeighInImporter
DailyNutritionImporter
FoodProductImporter
RecipeImporter
RecipeBundleImporter
DailyEnergyImporter
MedicalLabImporter
TrainingPlanImporter
CompletedWorkoutImporter
```

El asistente universal solo debe preparar datos, sugerir mapping, generar preview y producir JSON estándar interno.

## Reglas de privacidad

- Nunca mezclar datos entre usuarios.
- Todo import debe asociarse a `user_id`.
- Guardar archivo original.
- Guardar SHA256.
- Registrar fuente.
- Registrar mapping usado cuando aplique.
- Registrar archivo estándar generado cuando aplique.
- Permitir auditoría posterior.
- No subir datos reales a Git.
- No usar ejemplos reales en tests.
- Usar fixtures ficticias.

## Comandos esperados de verificación

Cuando sea posible, ejecutar:

```bash
python -m compileall -q .
pytest -q
flask db check
docker compose config --quiet
```

Si el entorno Docker está disponible:

```bash
docker compose up -d --build
docker compose ps
docker compose exec app pytest
docker compose exec app flask db check
```

Para cambios de documentación solamente, al menos ejecutar:

```bash
git diff --check
```

Para cambios de backend, ejecutar además pruebas específicas del área modificada y la suite completa cuando sea razonable. Antes de entregar, revisar:

```bash
git diff --check
git status --short --branch
git diff --stat
git diff --name-only
```

## Estado actual importante

El proyecto ya tiene implementados módulos relevantes para:

- Usuarios y login.
- Uploads con SHA256.
- Captura manual con JSON generado.
- Validación contra JSON Schema.
- Pesajes.
- Nutrición diaria.
- Energía diaria.
- Estudios médicos.
- Alacena / productos.
- Recetas.
- Importación/exportación de recetas.
- Bundle JSON de recetas.
- Uso de recetas en nutrición diaria.
- Rutinas y sesiones de entrenamiento.
- Exportadores JSON/CSV/HTML en entrenamiento.
- Importadores base de entrenamiento.

## Prioridad de referencia

Si hay conflicto entre documentos, comentarios antiguos o c?digo viejo, tomar como referencia:

1. JSON Schemas en `schemas/`
2. Pruebas existentes que codifiquen el contrato esperado
3. `docs/project-rules/canonical-data-contract-import-update.md`
4. `docs/project-rules/phase-5b-universal-json-import-assistant.md`
5. `docs/project-rules/standard-json-generator-development.md`
6. `AGENTS.md`
7. `docs/AI_WORK_CONTEXT.md`
8. `docs/PROJECT_CONTEXT.md`
9. `docs/ACTIVE_HANDOFF.md`
10. Estado real del c?digo para detalles de implementaci?n que no contradigan lo anterior
11. README
12. Comentarios antiguos
