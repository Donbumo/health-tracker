# AGENTS.md

## Instrucciones principales para agentes de código

Antes de modificar el proyecto, lee primero:

- `docs/PROJECT_CONTEXT.md`
- `docs/project-rules/phase-5b-universal-json-import-assistant.md`

`docs/PROJECT_CONTEXT.md` contiene la visión completa del producto, arquitectura, módulos, fases, schemas, importadores, exportadores, reglas de privacidad y estado actual del desarrollo.

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

## Regla para JSON estándar vs JSON no estándar

Cuando se suba un JSON:

1. Intentar detectar si coincide con un schema interno oficial.
2. Si coincide, usar el importador estándar del módulo.
3. Si no coincide, no debe tronar con un error genérico.
4. Debe marcarse como candidato para importación asistida.
5. El flujo asistido debe usar `UniversalJsonImportAssistant`.
6. El asistente debe producir detección, mapping sugerido, preview, advertencias y JSON estándar generado.
7. La escritura final debe pasar por el importador oficial correspondiente.

El `UniversalJsonImportAssistant` nunca debe escribir directamente en MariaDB.

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
2. `docs/project-rules/phase-5b-universal-json-import-assistant.md`
3. Pruebas existentes
4. Estado real del código
5. README
6. Comentarios antiguos