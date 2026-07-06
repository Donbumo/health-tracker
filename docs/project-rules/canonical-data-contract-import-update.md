# Contrato canónico de datos, importación individual/masiva y actualización consistente

## Estado

Regla transversal obligatoria del proyecto.

Esta regla aplica a todos los módulos que capturan, importan, exportan, muestran o actualizan datos de usuario.

## Objetivo

Crear una regla transversal para que todos los módulos del sistema usen contratos de datos consistentes entre:

- JSON Schema.
- Formularios manuales.
- Generadores manuales de JSON.
- Importadores.
- Exportadores.
- APIs.
- Base de datos.
- Pantallas HTML.
- Importador asistido universal.
- Importaciones individuales.
- Importaciones masivas.
- Exportación completa de usuario.
- Tests.
- Documentación.

El problema detectado en QA con pesajes no debe tratarse como un caso aislado. Es un patrón que puede aparecer en todos los módulos si no existe una regla común.

## Problema detectado

Ejemplo real del patrón:

```text
La UI mostraba: Agua corporal
El modelo/base usaba: water_percentage
El schema/importador/exportador usaban: water_percent
El documento del UniversalJsonImportAssistant proponía: body_water_percent
Resultado: un JSON generado con body_water_percent fue rechazado aunque el sistema sí soportaba agua corporal.
```

Este tipo de inconsistencia queda prohibido.

## Regla principal

Cada módulo debe tener un único contrato canónico de JSON.

Ese contrato canónico debe ser la fuente de verdad pública para archivos importables/exportables.

La base de datos puede usar nombres internos distintos, pero esos nombres nunca deben filtrarse como contrato externo si ya existe un nombre JSON canónico.

Ejemplo correcto en pesajes:

```text
Campo visible en UI: Agua corporal
JSON canónico: water_percent
DB/modelo: water_percentage
Tipo: decimal
Unidad: porcentaje
Rango: 0 a 100
Requerido: no
Aliases asistidos: agua_pct, agua_corporal_pct, body_water_percent, water_percentage, water_pct
Actualizable: sí
Merge: llenar si está vacío; sobrescribir solo con confirmación
```

Ejemplo incorrecto:

```text
Un importador acepta water_percent.
Un exportador escribe water_percentage.
Un asistente genera body_water_percent.
Un formulario manda water_pct.
La documentación dice agua_pct.
```

## Tabla de contrato por módulo

Cada módulo debe declarar una tabla de contrato con estos campos:

- Nombre visible en UI.
- Nombre canónico en JSON.
- Nombre interno en modelo/base de datos.
- Tipo de dato.
- Unidad.
- Rango válido.
- Si es requerido u opcional.
- Aliases aceptados en importación asistida.
- Si se puede actualizar después.
- Política de merge.

Ejemplo:

| Campo visible | JSON canónico | DB/modelo | Tipo | Unidad | Rango | Requerido | Aliases asistidos | Actualizable | Merge |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Agua corporal | water_percent | water_percentage | decimal | porcentaje | 0 a 100 | no | agua_pct, agua_corporal_pct, body_water_percent, water_percentage, water_pct | sí | llenar si está vacío; sobrescribir solo con confirmación |

## Regla de alineación obligatoria

Para cada campo visible o persistido, deben estar alineados:

- JSON Schema.
- Manual JSON o generador manual.
- Formulario.
- Ruta que procesa formulario.
- Importador estándar.
- Exportador estándar.
- Exportación completa de usuario.
- Preview de importación.
- Tests.
- Documentación.

Se considera bug si:

- Un campo existe en UI o DB pero no en schema/importador/exportador.
- Un campo existe en docs pero no en schema real.
- Un campo se exporta con un nombre y se importa con otro.
- Un asistente genera un alias externo como si fuera campo estándar.
- Un formulario usa un nombre distinto al contrato canónico sin normalizarlo.

## Regla de aliases

Los aliases solo deben usarse en la capa de normalización, migración o importación asistida.

Los aliases no deben guardarse como nombres oficiales.

Flujo correcto:

```text
JSON externo no estándar
        ↓
Alias detector
        ↓
Mapping al nombre canónico
        ↓
JSON estándar interno
        ↓
Validación contra schema oficial
        ↓
Importador oficial
        ↓
Base de datos
```

Ejemplo:

```text
Entrada externa: body_water_percent
Alias detectado: body_water_percent
Campo canónico generado: water_percent
Campo DB final: water_percentage
```

El `UniversalJsonImportAssistant` nunca debe generar como estándar un alias externo si ya existe un nombre canónico.

## Regla de schema como contrato público

El JSON Schema de cada módulo debe representar exactamente lo que el sistema acepta y exporta como formato estándar.

Reglas:

- Si el sistema exporta un campo, el schema debe permitirlo.
- Si el formulario manual permite capturar un campo, el schema debe permitirlo.
- Si la UI muestra un campo persistido, el exportador debe poder exportarlo.
- Si un importador acepta un campo estándar, debe estar documentado en el schema.
- Si se decide aceptar aliases, esos aliases deben vivir fuera del contrato estándar o en una sección explícita de normalización asistida.

## Regla de importación individual y masiva

Todo módulo debe soportar conceptualmente dos modos:

- Importación individual.
- Importación masiva o batch.

Aunque la implementación inicial de un módulo solo acepte importación individual, el diseño del contrato no debe impedir el batch futuro.

Forma recomendada:

Documento individual:

```text
schema_version
record_type
user_id
source_type
data
```

Documento masivo:

```text
schema_version
record_type
user_id
source_type
records
```

Donde cada elemento de `records` debe tener la misma forma que `data`.

No debe existir un contrato distinto para individual y batch.

## Regla de create/update/upsert

Todo importador estándar debe definir explícitamente su política cuando recibe un registro que ya existe.

No basta con decir "duplicado".

Estrategias permitidas:

```text
skip
merge_missing
overwrite
create_new
fail
ask_user
```

Definiciones:

- `skip`: omitir si ya existe.
- `merge_missing`: actualizar solo campos vacíos o nulos.
- `overwrite`: sobrescribir campos existentes con los del archivo.
- `create_new`: crear registro nuevo si el dominio lo permite.
- `fail`: fallar explícitamente.
- `ask_user`: mostrar preview y permitir elegir.

Política recomendada:

```text
Importación automática: skip o merge_missing según el dominio.
Importación asistida: ask_user.
Importación masiva: preview con conteo de nuevos, duplicados, actualizables y conflictivos.
```

Para pesajes, la política recomendada es `merge_missing`.

Ejemplo:

```text
El usuario importa un pesaje mínimo con recorded_at y weight_kg.
Después importa el mismo pesaje con grasa, músculo, agua, BMR y notas.
El sistema detecta mismo user_id + recorded_at.
El sistema no debe fallar sin más.
Debe permitir completar campos faltantes.
Si un campo existente tiene valor distinto, debe marcar conflicto o pedir confirmación.
```

## Regla de duplicados por dominio

Cada módulo debe definir su llave natural o lógica de deduplicación.

| Dominio | Llave natural sugerida |
| --- | --- |
| Pesajes | user_id + recorded_at |
| Nutrición diaria | user_id + date |
| Comida individual | user_id + date + meal_type + optional timestamp/name |
| Gasto energético diario | user_id + date + source_type |
| Alacena/productos | user_id + normalized_name + brand opcional + serving/base macro hash opcional |
| Recetas | user_id + normalized_name + version o ingredient_hash |
| Rutinas | user_id + plan_name + version |
| Sesiones de entrenamiento | user_id + performed_at + session_name o workout_plan_id |
| Estudios médicos | user_id + lab_date + lab_name opcional + marker set hash |
| Presión arterial | user_id + recorded_at |
| Glucosa | user_id + recorded_at + context opcional |
| Sueño | user_id + sleep_start + sleep_end + source_type |

## Regla de actualización parcial

Cuando un importador actualiza un registro existente, debe distinguir entre:

- Campo ausente: no tocar.
- Campo presente con `null`: limpiar solo si la estrategia lo permite.
- Campo presente con valor: actualizar según política.
- Campo presente con valor distinto al existente: marcar conflicto si no hay `overwrite`.
- Campo extra no reconocido: guardar en `raw_payload` solo si el schema/módulo lo permite; si no, rechazar con mensaje claro.

## Preview obligatorio para asistido y masivo

Toda importación asistida o masiva debe tener preview antes de tocar datos definitivos.

El preview debe mostrar:

- Registros nuevos.
- Registros duplicados.
- Registros que se pueden completar.
- Registros con conflicto.
- Campos reconocidos.
- Campos ignorados.
- Aliases usados.
- Campos convertidos.
- Campos fuera de rango.
- Errores de validación.
- Acción sugerida.

El usuario debe poder elegir:

- Importar nuevos.
- Completar duplicados.
- Sobrescribir duplicados.
- Omitir conflictivos.
- Cancelar todo.

## Regla de validación antes de base de datos

Ningún importador asistido debe escribir directamente en la base de datos.

Siempre debe generar primero un JSON estándar interno.

Ese JSON estándar interno debe validar contra el schema oficial.

Solo después debe llamar al importador estándar.

Flujo obligatorio:

```text
archivo externo
        ↓
detector
        ↓
normalizador/mapping
        ↓
JSON estándar interno
        ↓
schema oficial
        ↓
importador estándar
        ↓
DB
```

## Regla de exportación redonda

Todo dato importable debe ser exportable con el mismo contrato.

Debe cumplirse round-trip:

```text
Crear manualmente un registro
        ↓
Exportarlo a JSON
        ↓
Reimportarlo
        ↓
Validar que el registro resultante conserva los mismos campos
```

Si ya existe, debe poder detectarse como duplicado o actualizarse según política.

Si un campo se pierde en export/import, debe documentarse como pérdida de información o corregirse.

## Regla de pruebas obligatorias

Cada módulo con importación/exportación debe tener pruebas para:

- Captura manual genera JSON válido.
- Importación individual válida.
- Exportación individual válida.
- Round-trip manual a JSON a import.
- Importación con `user_id` incorrecto rechazada.
- Importación con campo visible en UI persiste y se muestra.
- Importación con alias externo se normaliza al campo canónico, cuando pase por asistente.
- Importación de duplicado con `skip`.
- Importación de duplicado con `merge_missing`.
- Importación de duplicado con conflicto.
- Importación masiva con nuevos, duplicados y errores parciales.
- Exportación masiva o backup conserva el contrato.

## Regla de nombres

Usar `snake_case` en JSON.

No mezclar idiomas en nombres de campos canónicos.

Los nombres visibles pueden estar en español, pero los nombres JSON deben mantenerse técnicos y estables.

Correcto:

```text
UI: Agua corporal
JSON: water_percent
DB: water_percentage
```

Incorrecto:

```text
JSON: agua
JSON: agua_pct
JSON: bodyWaterPercent
JSON: body_water_percent si el contrato real ya es water_percent
```

## Regla de documentación viva

Cuando se agregue o cambie un campo en cualquier módulo, deben actualizarse en el mismo cambio:

- Schema.
- Modelo si aplica.
- Migración si aplica.
- Formulario si aplica.
- Generador manual si aplica.
- Importador.
- Exportador.
- Tests.
- Documentación de contrato.
- Aliases del `UniversalJsonImportAssistant` si aplica.

Si no se actualizan todas las capas, el cambio debe considerarse incompleto.

## Regla de compatibilidad

Si ya existen archivos viejos o externos que usan nombres distintos, no se debe cambiar el contrato canónico para perseguir esos nombres.

Se debe agregar alias en la capa asistida o de migración.

Ejemplo:

```text
Si un archivo externo trae body_water_percent, el asistente lo acepta como alias, pero genera water_percent.
```

## Regla de errores amigables

Cuando un import falla por schema, el mensaje no debe quedarse solo en:

```text
additional properties are not allowed
```

Debe traducirse a algo útil:

```text
Campo no reconocido: body_water_percent.
Campo canónico esperado: water_percent.
Sugerencia: este archivo parece usar un alias conocido; usa el importador asistido o convierte el campo.
```

Si el campo pertenece al módulo pero tiene nombre incorrecto, mostrar mapping sugerido.

## Regla de módulos aplicables

Esta regla aplica a:

- Pesajes.
- Composición corporal.
- Nutrición diaria.
- Comidas.
- Alacena.
- Alimentos.
- Recetas.
- Gasto energético.
- Entrenamientos realizados.
- Rutinas planeadas.
- Estudios médicos.
- Marcadores clínicos.
- Presión arterial.
- Glucosa.
- Sueño.
- Síntomas.
- Dispositivos.
- Exportación/importación completa de usuario.

## Criterio de aceptación global

Un módulo se considera consistente cuando:

- Su schema refleja lo que acepta y exporta.
- Su formulario manual genera el mismo contrato.
- Su importador acepta el mismo contrato.
- Su exportador produce el mismo contrato.
- Su UI muestra los campos persistidos.
- Su importación individual funciona.
- Su importación masiva está implementada o diseñada con el mismo contrato.
- Sus duplicados tienen política explícita.
- Sus actualizaciones parciales no pierden datos.
- Sus aliases externos no contaminan el contrato canónico.
- Sus pruebas cubren round-trip, duplicados y `user_id`.
- Su documentación no contradice al schema real.

## Relación con UniversalJsonImportAssistant

El importador asistido universal es flexible en la entrada, pero estricto en la salida.

Debe aceptar aliases y estructuras no estándar, pero generar JSON estándar interno con nombres canónicos.

Ejemplo obligatorio:

```text
Entrada externa: body_water_percent
Campo canónico generado: water_percent
Campo DB final: water_percentage
```

Nunca debe generar como estándar:

```text
body_water_percent
water_percentage
agua_pct
```

si el contrato canónico real es:

```text
water_percent
```

## Principio final

El sistema debe ser flexible en la entrada, estricto en el contrato interno y seguro en la escritura.

Entrada flexible:

```text
acepta archivos externos, aliases y estructuras no estándar mediante asistente.
```

Contrato estricto:

```text
todo se convierte a JSON estándar interno antes de importar.
```

Escritura segura:

```text
importadores estándar validan user_id, schema, duplicados y permisos.
```

Actualización completa:

```text
tanto registros individuales como masivos deben poder crear, omitir, completar o actualizar datos existentes con una política clara.
```