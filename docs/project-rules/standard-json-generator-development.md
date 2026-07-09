# Reglas para desarrollo de StandardJsonGenerator

## Estado

Regla específica para cambios en `StandardJsonGenerator`, generadores por dominio, `UniversalJsonImportAssistant`, `SchemaDetector` y `AssistedImportService`.

Esta regla complementa:

- `canonical-data-contract-import-update.md`.
- `phase-5b-universal-json-import-assistant.md`.

## Principio principal

El schema es el contrato público.

Cada documento generado debe usar los nombres canónicos definidos por el schema correspondiente. Los aliases externos solo pertenecen a la capa de detección, normalización o mapping asistido.

## Alcance read-only

`StandardJsonGenerator` y el preview asistido deben ser read-only:

- No escriben en MariaDB.
- No crean registros.
- No guardan archivos.
- No crean `UploadedFile`.
- No crean jobs.
- No ejecutan importación real.
- No hacen commit ni cambios en `/data`.

Su responsabilidad es producir una respuesta de preview con:

- candidato seleccionado;
- mapping;
- documentos estándar generados en memoria;
- validación contra schema;
- errores;
- advertencias.

La escritura real debe pasar después por el importador oficial del dominio.

## No inventar valores requeridos

Queda prohibido inventar valores solo para satisfacer un schema.

No usar placeholders como:

- `Unknown`
- `N/A`
- `dummy`
- `fallback`
- `1`
- `0`
- fechas inventadas
- unidades inventadas
- IDs inventados

Cuando falten campos requeridos:

1. Generar únicamente los campos realmente disponibles.
2. Validar el documento generado contra el schema.
3. Devolver `valid: false` con errores claros.
4. Permitir que la UI o el flujo posterior pidan corrección al usuario.

Esto aplica especialmente a:

- `weight_kg` en pesajes.
- `name` en productos.
- IDs y versión de plan en `completed_workout`.
- `unit` en marcadores médicos.
- cualquier fecha requerida por schema.

## Nombres canónicos y aliases

El JSON estándar generado debe usar nombres canónicos.

Ejemplo correcto:

```text
Entrada externa: body_water_percent
Alias detectado: body_water_percent
Campo generado: water_percent
```

Ejemplo incorrecto:

```text
Campo generado: body_water_percent
Campo generado: water_percentage
```

Los aliases externos viven en:

- `UniversalJsonImportAssistant`;
- normalizadores;
- mapping sugerido;
- tests de detección.

No deben filtrarse al documento estándar generado si el schema tiene un nombre canónico distinto.

Si se conservan aliases históricos para compatibilidad, y el schema actual no tiene campo equivalente, el generador debe advertir/ignorar el campo en lugar de crear propiedades no canónicas. Ejemplo actual: algunos aliases antiguos de `training_plan` como `rir_objetivo`, `rpe_objetivo`, `version` o `bloques` son detectables, pero no se escriben al JSON estándar porque `training_plan.schema.json` no define esos campos.

## Validación obligatoria

Todo documento generado debe validarse contra su schema.

La respuesta debe distinguir:

- documentos generados;
- documentos válidos;
- documentos inválidos;
- errores de schema;
- warnings de campos ignorados o no soportados.

Un documento inválido por datos faltantes puede ser un resultado correcto del preview, siempre que no se hayan inventado datos.

## `source_type`

Respetar el enum real de cada schema.

Estado verificado actual:

| Schema | `source_type` permitido |
| --- | --- |
| `weigh_in` | `manual_generated`, `uploaded`, `device_sync` |
| `daily_energy` | `manual_generated`, `uploaded`, `device_sync` |
| `daily_nutrition` | `manual_generated`, `uploaded`, `device_sync` |
| `completed_workout` | `manual_generated`, `uploaded`, `device_sync` |
| `medical_lab` | `manual_generated`, `uploaded` |
| `food_product` | `uploaded`, `manual_generated`, `converted`, `system_generated`, `synced_from_device` |
| `training_plan` | `uploaded`, `manual_generated` |
| `recipe` | `uploaded`, `manual_generated`, `converted`, `system_generated`, `synced_from_device` |
| `recipe_bundle` | `uploaded`, `manual_generated`, `converted`, `system_generated`, `synced_from_device` |

Si una fuente externa no encaja, no ampliar el schema sin autorización. Normalizar a una fuente permitida solo si el código y tests del dominio ya lo hacen explícitamente.

## Paths padre/hijo y estructuras anidadas

Los generadores deben manejar cuidadosamente paths como:

```text
$
registros
labs
labs[0]
labs.markers
labs.marcadores
entrenamientos.ejercicios.series
```

Reglas:

- Un candidato debe leer registros desde el path detectado.
- Si el candidato apunta a hijos anidados pero el documento estándar necesita el padre, el ajuste debe ser explícito y probado.
- No duplicar registros al recorrer padre e hijo.
- No mezclar datos de nodos hermanos no seleccionados.
- Mantener warnings para campos detectados pero no soportados.

Caso conocido: medical lab puede requerir subir desde `markers`/`marcadores` al reporte padre para generar un documento completo.

## Round-trip

Cuando el dominio ya tenga importador/exportador oficial, agregar o mantener pruebas de round-trip cuando aplique:

```text
entrada no estándar ficticia
  -> preview asistido
  -> JSON estándar generado
  -> validación contra schema
  -> importador oficial en prueba separada si corresponde
  -> export estándar
```

El round-trip no debe contaminar nombres canónicos con aliases externos.

## Pruebas mínimas por dominio

Cada dominio con generación estándar debe tener pruebas para:

- estructura plana;
- estructura anidada;
- aliases español/inglés;
- batch cuando corresponda;
- documento válido;
- documento inválido por datos faltantes;
- `AssistedImportService`;
- validación contra schema;
- warnings para campos desconocidos o no soportados;
- aislamiento por `user_id` cuando el flujo llegue a importador o DB.

Para dominios con estructuras jerárquicas, probar paths padre/hijo.

Para documentos con IDs externos o referencias internas, probar que no se inventan IDs.

## Separar generadores por dominio

El archivo monolítico actual puede refactorizarse hacia generadores por dominio sin cambios funcionales.

Reglas para esa separación:

- Un módulo por dominio o por familia de dominio.
- Mantener una interfaz común simple.
- Mantener `StandardJsonGenerator.generate(...)` como dispatch central mientras existan llamadas actuales.
- Cambios al dispatch central mínimos y explícitos.
- No modificar contratos públicos durante un refactor mecánico.
- No mezclar refactor con nuevos dominios si no fue pedido.
- Cada dominio debe conservar sus pruebas antes de avanzar al siguiente.

## Trabajo paralelo con git worktree

Si varios agentes trabajan en paralelo:

- Crear worktrees por rama/dominio.
- Un agente por dominio.
- Evitar que varios agentes editen simultáneamente el dispatch central.
- Coordinar cualquier cambio compartido antes de aplicar patches.
- Rebase/merge solo cuando las pruebas del dominio pasan.

Un agente no debe modificar módulos de otros dominios salvo necesidad demostrada y documentada.

## Dominios actuales del generador

`SUPPORTED_TARGETS` del módulo `standard_json_generator.py` verificado:

- `weigh_in_batch`
- `food_products`
- `daily_energy`
- `daily_nutrition`
- `completed_workout`
- `medical_lab`
- `training_plan`
- `recipe`
- `recipe_bundle`

La importación real posterior al preview no pertenece a `StandardJsonGenerator`; debe mantenerse en servicios separados como `StandardImportExecutor` o equivalentes.

## Criterios de aceptación

Un cambio en el generador se acepta cuando:

1. No escribe DB ni archivos.
2. No inventa requeridos.
3. Usa nombres canónicos del schema.
4. Mantiene aliases fuera del contrato generado.
5. Valida todo documento generado.
6. Conserva warnings útiles.
7. Mantiene compatibilidad con tests existentes.
8. Agrega pruebas del dominio tocado.
9. `git diff --check` queda limpio.
10. Si se tocó backend, pasan pruebas específicas y suite completa.
