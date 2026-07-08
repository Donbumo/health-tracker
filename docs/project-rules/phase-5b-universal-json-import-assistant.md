# Fase 5B - Importador asistido universal de JSON no estándar

## Estado

Bloque transversal del proyecto, parcialmente implementado en modo read-only.

Este bloque no reemplaza los importadores estándar. Su función es actuar cuando el sistema recibe un JSON bien estructurado, pero que no coincide exactamente con los schemas internos del sistema.

Estado verificado al 2026-07-08: ya existen `SchemaDetector`, `UniversalJsonImportAssistant`, `StandardJsonGenerator` y `AssistedImportService` para preview/generación en memoria. La escritura real, jobs persistidos y restore/importación final asistida siguen fuera de este bloque salvo implementación posterior explícita.

## Objetivo

Agregar al proyecto una capa de importación asistida capaz de recibir archivos JSON bien organizados, creados por una IA, una app externa, una báscula, un reloj, una hoja de cálculo convertida o un backup manual.

El sistema debe evitar fallar de forma abrupta cuando el archivo no coincide con un schema interno. En lugar de mostrar únicamente un error de schema inválido, debe detectar que el archivo requiere asistencia y guiar al usuario por un flujo de mapping, preview, validación e importación segura.

## Principio central

El sistema debe ser:

```text
Flexible para recibir archivos
Estricto para validar
Claro para previsualizar
Seguro para importar
Auditable para rastrear
```

## Flujo esperado

```text
Intentar detectar schema estándar
        ↓
Si coincide, importar normalmente
        ↓
Si no coincide, ejecutar UniversalJsonImportAssistant
        ↓
Detectar estructuras candidatas
        ↓
Sugerir mapping
        ↓
Mostrar preview
        ↓
Generar JSON estándar interno
        ↓
Validar contra schema oficial
        ↓
Importar con el importador normal del módulo
```

## Regla principal

`UniversalJsonImportAssistant` nunca debe escribir directamente en la base de datos.

Solo debe producir:

```text
detección
mapping sugerido
preview
JSON estándar interno generado
advertencias
```

La escritura final siempre debe pasar por el importador oficial del módulo.

## Módulos objetivo

Debe aplicar a todos los módulos principales, no solo a pesajes:

- Pesajes y composición corporal.
- Nutrición diaria.
- Alacena virtual.
- Alimentos.
- Recetas.
- Gasto energético diario.
- Entrenamientos realizados.
- Rutinas planeadas.
- Estudios médicos.
- Marcadores de laboratorio.
- Sueño.
- Síntomas.
- Presión arterial.
- Glucosa.
- Datos de dispositivos.
- Archivos consolidados creados por IA u otras apps.

## Problema que resuelve

Un usuario puede subir un archivo como este:

```json
{
  "metadata": {},
  "perfil": {},
  "metas": {},
  "reglas_macros_actuales": {},
  "entrenamiento": {},
  "registros": [
    {
      "fecha": "2026-07-05",
      "peso_kg": 87.25,
      "grasa_corporal_pct": 27.3,
      "musculo_kg": 60.19
    }
  ]
}
```

Ese archivo no es directamente un `weigh_in.schema.json`, porque los pesajes están dentro de `registros` y el archivo trae muchas otras secciones.

El sistema no debe tronar ni importar todo ciegamente. Debe detectar que el archivo no es estándar, pero que contiene datos importables.

## Flujo general de archivo

```text
Archivo subido
        ↓
Guardar original en uploads/raw/user_<id>/
        ↓
Calcular SHA256
        ↓
Crear ImportJob
        ↓
SchemaDetector
        ↓
¿Coincide con schema interno?
        ├── Sí → Importador estándar
        └── No → UniversalJsonImportAssistant
                    ↓
                    Analizar estructura
                    ↓
                    Detectar posibles dominios
                    ↓
                    Sugerir mappings
                    ↓
                    Generar preview
                    ↓
                    Usuario confirma
                    ↓
                    StandardJsonGenerator
                    ↓
                    Guardar JSON normalizado en uploads/processed/user_<id>/
                    ↓
                    Validar contra JSON Schema interno
                    ↓
                    Importador estándar
                    ↓
                    MariaDB
```

## Componentes sugeridos

```text
backend/app/services/importers/
├── schema_detector.py
├── universal_json_import_assistant.py
├── mapping_suggester.py
├── import_preview.py
├── standard_json_generator.py
├── assisted_import_service.py
├── weigh_in_importer.py
├── daily_nutrition_importer.py
├── pantry_importer.py
├── food_importer.py
├── recipe_importer.py
├── recipe_bundle_importer.py
├── daily_energy_importer.py
├── medical_lab_importer.py
├── training_plan_importer.py
└── completed_workout_importer.py
```

Schemas sugeridos:

```text
schemas/
├── assisted_import_preview.schema.json
├── import_mapping.schema.json
├── import_job.schema.json
├── weigh_in_batch.schema.json
├── daily_nutrition.schema.json
├── food_product.schema.json
├── recipe.schema.json
├── recipe_bundle.schema.json
├── daily_energy.schema.json
├── medical_lab.schema.json
├── training_plan.schema.json
└── completed_workout.schema.json
```

## SchemaDetector

`SchemaDetector` debe ser estricto.

Su trabajo es responder:

```text
¿Este archivo ya viene en un formato interno reconocido?
```

No debe intentar ser demasiado inteligente. Si no valida contra un schema interno oficial, debe responder que requiere asistencia.

Ejemplo conceptual:

```python
class SchemaDetector:
    def detect(self, payload, requested_type=None):
        if matches_schema(payload, "weigh_in.schema.json"):
            return {
                "mode": "standard",
                "detected_type": "weigh_in",
                "confidence": 1.0,
            }

        if matches_schema(payload, "daily_nutrition.schema.json"):
            return {
                "mode": "standard",
                "detected_type": "daily_nutrition",
                "confidence": 1.0,
            }

        if matches_schema(payload, "food_product.schema.json"):
            return {
                "mode": "standard",
                "detected_type": "food_product",
                "confidence": 1.0,
            }

        if matches_schema(payload, "recipe.schema.json"):
            return {
                "mode": "standard",
                "detected_type": "recipe",
                "confidence": 1.0,
            }

        if matches_schema(payload, "recipe_bundle.schema.json"):
            return {
                "mode": "standard",
                "detected_type": "recipe_bundle",
                "confidence": 1.0,
            }

        return {
            "mode": "assistant_required",
            "detected_type": requested_type or "unknown",
            "confidence": 0.0,
        }
```

## UniversalJsonImportAssistant

Cuando el schema exacto no coincide, entra el asistente universal.

Debe analizar:

- Claves de primer nivel.
- Arreglos internos.
- Objetos repetitivos.
- Campos con nombres reconocibles.
- Tipos de datos.
- Fechas.
- Unidades.
- Presencia de macros.
- Presencia de micronutrientes.
- Presencia de alimentos.
- Presencia de recetas.
- Presencia de peso/composición corporal.
- Presencia de entrenamientos.
- Presencia de estudios médicos.
- Presencia de datos de reloj o actividad.

Ejemplo de detección:

```json
{
  "mode": "assistant_required",
  "source_shape": "consolidated_health_source",
  "candidate_domains": [
    {
      "target_type": "weigh_in_batch",
      "path": "registros",
      "count": 41,
      "confidence": 0.92
    },
    {
      "target_type": "user_goals",
      "path": "metas",
      "count": 1,
      "confidence": 0.80
    },
    {
      "target_type": "nutrition_rules",
      "path": "reglas_macros_actuales",
      "count": 1,
      "confidence": 0.76
    },
    {
      "target_type": "training_preferences",
      "path": "entrenamiento",
      "count": 1,
      "confidence": 0.72
    }
  ]
}
```

## Detección por dominio

### Pesajes y composición corporal

Pistas comunes:

```text
fecha
hora
peso
peso_kg
weight
weight_kg
imc
bmi
grasa_corporal_pct
body_fat_percent
agua_pct
body_water_percent
musculo_kg
muscle_mass_kg
masa_osea_kg
bone_mass_kg
grasa_visceral
visceral_fat
metabolismo_basal_kcal
bmr
bmr_kcal
```

Destino:

```text
weigh_in_batch.schema.json
```

### Nutrición diaria

Pistas comunes:

```text
fecha
desayuno
comida
cena
snacks
extras
kcal
calorias
proteina_g
grasa_g
carbos_netos_g
carbohidratos
fibra_g
azucares_g
sodio_mg
micronutrientes
totales
meals
items
```

Destino:

```text
daily_nutrition.schema.json
```

### Alacena virtual y alimentos

Pistas comunes:

```text
alacena
pantry
productos
foods
ingredientes
marca
nombre
por_100g
por_porcion
serving_size
calorias
proteina
grasa
carbohidratos
fibra
sodio
etiqueta
```

Destino:

```text
food_product.schema.json
```

Debe permitir importar productos sueltos, alimentos con etiqueta y productos con datos incompletos.

Si faltan datos críticos, debe permitir guardarlos como borrador o producto incompleto, pero no usarlos automáticamente para cálculos exactos hasta que estén validados.

### Recetas

Pistas comunes:

```text
receta
recipe
ingredientes
preparacion
pasos
rendimiento
porciones
macros_por_receta
macros_por_porcion
peso_final
```

Destino:

```text
recipe.schema.json
recipe_bundle.schema.json
```

Debe poder distinguir entre:

```text
producto de alacena
receta casera
comida registrada
```

### Gasto energético diario

Pistas comunes:

```text
fecha
calorias_totales
calorias_activas
calorias_reposo
pasos
distancia
reloj
watch
gasto
energy
active_energy
resting_energy
```

Destino:

```text
daily_energy.schema.json
```

### Entrenamientos realizados

Pistas comunes:

```text
fecha
rutina
sesion
ejercicios
sets
series
reps
peso
rir
rpe
descanso
duracion
frecuencia_cardiaca
calorias
```

Destino:

```text
completed_workout.schema.json
```

### Rutinas planeadas

Pistas comunes:

```text
plan
rutina
dias
ejercicios
series_objetivo
reps_objetivo
rir_objetivo
rpe_objetivo
descanso_objetivo
version
bloques
```

Destino:

```text
training_plan.schema.json
```

### Estudios médicos

Pistas comunes:

```text
laboratorio
fecha
marcadores
analitos
valor
unidad
rango_referencia
estado
glucosa
insulina
hba1c
colesterol
hdl
ldl
trigliceridos
tsh
vitamina_d
b12
ferritina
```

Destino:

```text
medical_lab.schema.json
```

## Mapping sugerido

El sistema debe construir un mapping editable.

Ejemplo para pesajes:

```json
{
  "target_type": "weigh_in_batch",
  "source_path": "registros",
  "field_mapping": {
    "fecha": "measured_date",
    "hora": "measured_time",
    "peso_kg": "weight_kg",
    "imc": "bmi",
    "grasa_corporal_pct": "body_fat_percent",
    "agua_pct": "body_water_percent",
    "proteinas_pct": "protein_percent",
    "metabolismo_basal_kcal": "bmr_kcal",
    "grasa_visceral": "visceral_fat",
    "musculo_kg": "muscle_mass_kg",
    "masa_osea_kg": "bone_mass_kg",
    "puntuacion_corporal": "body_score",
    "nota": "notes"
  },
  "extra_payload_policy": "store_in_raw_payload"
}
```

Ejemplo para alacena:

```json
{
  "target_type": "food_products",
  "source_path": "productos",
  "field_mapping": {
    "nombre": "name",
    "marca": "brand",
    "porcion_g": "serving_size_g",
    "kcal": "calories",
    "proteina_g": "protein_g",
    "grasa_g": "fat_g",
    "carbos_netos_g": "net_carbs_g",
    "fibra_g": "fiber_g",
    "sodio_mg": "sodium_mg"
  },
  "extra_payload_policy": "store_in_raw_payload"
}
```

## Preview obligatorio

Antes de importar, el sistema debe mostrar una vista previa.

La vista previa debe incluir:

- Tipo de archivo detectado.
- Módulos candidatos.
- Ruta interna detectada.
- Cantidad de registros.
- Campos detectados.
- Campos ignorados.
- Campos que se guardarán como `raw_payload`.
- Registros duplicados probables.
- Registros incompletos.
- Advertencias de unidades.
- Advertencias de precisión.
- Acciones disponibles.

Ejemplo:

```text
Archivo detectado: JSON no estándar / fuente consolidada
Destino solicitado: Pesajes

Encontramos:
- 41 registros candidatos
- Ruta detectada: registros
- Rango de fechas: 2025-04-30 a 2026-07-05

Campos detectados:
- peso
- fecha
- IMC
- grasa corporal
- agua corporal
- músculo
- masa ósea
- grasa visceral
- BMR
- notas

No se importará en este módulo:
- perfil
- metas
- reglas de macros
- preferencias de entrenamiento
- notas contextuales generales

Acciones:
- Importar todos
- Importar solo completos
- Omitir duplicados
- Actualizar duplicados
- Cancelar
```

## Generación de JSON estándar interno

Después de confirmar, el sistema debe generar un archivo normalizado.

Ejemplo:

```json
{
  "schema_version": "1.0",
  "type": "weigh_in_batch",
  "source": {
    "source_type": "assisted_import",
    "original_filename": "seguimiento_fisico_fuente_consolidada_2026-07-05.json",
    "original_format": "consolidated_ai_health_source"
  },
  "records": [
    {
      "measured_at": "2026-07-05T09:28:00",
      "weight_kg": 87.25,
      "bmi": 26.9,
      "body_fat_percent": 27.3,
      "body_water_percent": 49.8,
      "protein_percent": 19.1,
      "bmr_kcal": 1788,
      "visceral_fat": 11,
      "muscle_mass_kg": 60.19,
      "bone_mass_kg": 3.23,
      "body_score": 52,
      "notes": "Registro ficticio de ejemplo.",
      "raw_payload": {
        "source_example": true
      }
    }
  ]
}
```

El archivo generado debe guardarse en:

```text
data/uploads/processed/user_<id>/
```

o en:

```text
data/uploads/generated/user_<id>/
```

según se decida si se considera conversión de archivo externo o generación interna.

## Estados sugeridos de ImportJob

```text
uploaded
standard_schema_detected
assistant_required
candidate_domains_detected
mapping_suggested
preview_ready
awaiting_user_confirmation
user_confirmed
standard_json_generated
validated
imported
partially_imported
cancelled_by_user
failed_detection
failed_mapping
failed_validation
failed_import
```

## Políticas de duplicados

El asistente debe detectar duplicados probables antes de importar.

### Pesajes

```text
mismo user_id
misma fecha
misma hora si existe
mismo peso aproximado
```

### Nutrición diaria

```text
mismo user_id
misma fecha
mismo tipo de día
```

### Alacena

```text
mismo user_id
mismo nombre normalizado
misma marca si existe
mismos macros principales si existen
```

### Recetas

```text
mismo user_id
mismo nombre normalizado
misma versión o mismos ingredientes principales
```

### Entrenamientos

```text
mismo user_id
misma fecha
mismo nombre de rutina
mismos ejercicios principales
```

### Estudios médicos

```text
mismo user_id
misma fecha de estudio
mismo laboratorio si existe
mismos marcadores principales
```

Opciones de usuario:

```text
omitir duplicados
actualizar existentes
crear nueva versión
importar de todos modos
cancelar
```

## Manejo de datos extra

No todo dato detectado debe importarse al módulo actual.

El sistema debe poder:

```text
importar al módulo actual
guardar como raw_payload
guardar como nota del archivo
sugerir importación a otro módulo
ignorar explícitamente
```

Ejemplo:

Si el usuario sube un JSON consolidado en el apartado de pesajes:

- `registros` puede importarse como pesajes.
- `metas` puede sugerirse para módulo de objetivos.
- `reglas_macros_actuales` puede sugerirse para nutrición/metas.
- `entrenamiento` puede sugerirse para preferencias de entrenamiento.
- `perfil` puede sugerirse para perfil de usuario.
- `notas_contextuales_recientes` puede guardarse como nota o bitácora.
- `resumen_actual` no debe importarse si duplica el último registro de `registros`.

## Seguridad y privacidad

El importador asistido debe respetar las mismas reglas del resto del sistema:

- Nunca mezclar datos entre usuarios.
- Todo import debe asociarse a `user_id`.
- Guardar archivo original.
- Guardar SHA256.
- Registrar fuente.
- Registrar mapping usado.
- Registrar archivo estándar generado.
- Permitir auditoría posterior.
- No subir datos reales a Git.
- No usar ejemplos reales en tests.
- Usar fixtures ficticias.

## Auditoría y trazabilidad

Cada importación asistida debe guardar:

```text
original_file_id
processed_file_id
user_id
requested_target_type
detected_source_shape
mapping_used
records_detected
records_imported
records_skipped
warnings
created_at
confirmed_by_user_at
import_status
```

Esto permite responder después:

```text
¿De dónde salió este dato?
¿Qué archivo lo creó?
¿Qué mapping se usó?
¿Qué campos se ignoraron?
¿Qué campos quedaron como raw_payload?
```

## UI sugerida

Agregar una pantalla genérica:

```text
/imports/<job_id>/assist
```

Flujo de UI:

```text
1. Archivo recibido
2. Formato estándar no detectado
3. Análisis asistido
4. Selección de dominio destino
5. Mapping sugerido editable
6. Preview de registros
7. Confirmación
8. Validación
9. Resultado de importación
```

Rutas sugeridas:

```text
POST /imports/upload
GET  /imports/<job_id>
GET  /imports/<job_id>/assist
POST /imports/<job_id>/mapping
GET  /imports/<job_id>/preview
POST /imports/<job_id>/confirm
POST /imports/<job_id>/cancel
```

También puede integrarse por módulo:

```text
POST /body/weigh-ins/import
POST /nutrition/import
POST /pantry/import
POST /recipes/import
POST /energy/import
POST /medical/import
POST /training/import
```

Todas esas rutas pueden usar internamente el mismo `UniversalJsonImportAssistant`.

## Criterio de aceptación

Este bloque se considera implementado cuando:

1. Un JSON estándar sigue importándose por su importador normal.
2. Un JSON no estándar no truena.
3. El sistema detecta que requiere asistencia.
4. El sistema encuentra estructuras candidatas.
5. El sistema sugiere un mapping razonable.
6. El sistema muestra preview antes de importar.
7. El usuario puede confirmar o cancelar.
8. El sistema genera un JSON estándar interno.
9. El JSON generado valida contra schema.
10. El importador estándar importa los datos.
11. Se guardan original, procesado, mapping y resultado.
12. Se respetan permisos por `user_id`.
13. Hay pruebas con fixtures ficticias para:
    - Pesajes consolidados.
    - Alacena/productos.
    - Nutrición diaria.
    - Recetas.
    - Entrenamiento realizado.
    - Estudio médico.
    - Archivo mixto con varios dominios.

## Ubicación en fases del proyecto

Este bloque debe considerarse transversal, pero puede planearse como:

```text
Fase 5B: Importador asistido universal
```

Debe colocarse después de tener schemas internos básicos y antes de depender de importadores reales complejos.

Relación con fases existentes:

```text
Fase 2: Schemas y captura manual
        ↓
Fase 5B: Importador asistido universal
        ↓
Fase 5: Importadores reales por fuente/dispositivo
        ↓
Fase 6: Exportadores
```

No reemplaza la Fase 5. La fortalece.

La Fase 5 importa formatos conocidos de fuentes reales.

La Fase 5B permite que archivos JSON no estándar, creados por IA, usuarios, hojas de cálculo, backups o apps externas, puedan entrar al sistema sin romperlo y sin contaminar la base de datos.

## Principio final

El sistema debe ser estricto en la base de datos, flexible en la entrada y transparente con el usuario.

El usuario nunca debe ver simplemente:

```text
Error: schema inválido
```

Debe ver algo como:

```text
Este archivo no coincide con el formato estándar, pero encontramos datos que parecen importables.

Detectamos posibles datos de:
- Pesajes
- Metas
- Nutrición
- Entrenamiento

Puedes revisar el mapping sugerido y decidir qué importar.
```
