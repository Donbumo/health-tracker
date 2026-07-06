# AGENTS.md

## Instrucciones principales para agentes de código

Antes de modificar el proyecto, lee primero:

- `docs/PROJECT_CONTEXT.md`
- `docs/project-rules/canonical-data-contract-import-update.md`
- `docs/project-rules/phase-5b-universal-json-import-assistant.md`

`docs/PROJECT_CONTEXT.md` contiene la visión completa del producto, arquitectura, módulos, fases, schemas, importadores, exportadores, reglas de privacidad y estado actual del desarrollo.

`docs/project-rules/canonical-data-contract-import-update.md` contiene la regla transversal para contratos canónicos de datos, importación individual/masiva, aliases, exportación redonda, duplicados y actualización consistente.

`docs/project-rules/phase-5b-universal-json-import-assistant.md` contiene las reglas para el importador asistido universal de JSON no estándar.

## Reglas de trabajo

- No inventes datos reales de salud, nutrición, entrenamiento, médicos o personales.
- No agregues datos reales al repositorio.
- No subas ni generes archivos reales dentro de Git que pertenezcan a usuarios.
- Todo dato real debe vivir en `/data` o en volúmenes Docker ignorados por Git.
- Mantén aislamiento por `user_id`.
- Antes de cambiar modelos o migraciones, revisa si realmente se necesita una migración.
- Si agregas tablas o columnas, crea migración Alembic/Flask-Migrate.
- Si no agregas tablas ni columnas, no generes migraciones innecesarias.
- Conserva compatibilidad con Docker Compose y MariaDB.
- Evita romper pruebas existentes.
- Cuando agregues funcionalidades, agrega o actualiza pruebas.
- Usa fixtures ficticias en tests.
- No uses datos médicos, corporales, alimentarios o personales reales en ejemplos.
- No agregues carpetas o archivos por error; si aparece un untracked sospechoso como `chemas`, no lo agregues sin confirmar.

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
python -m compileall .
pytest
flask db check
docker compose config
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

Si hay conflicto entre documentos, comentarios antiguos o código viejo, tomar como referencia:

1. `docs/PROJECT_CONTEXT.md`
2. `docs/project-rules/canonical-data-contract-import-update.md`
3. `docs/project-rules/phase-5b-universal-json-import-assistant.md`
4. Pruebas existentes
5. Estado real del código
6. README
7. Comentarios antiguos