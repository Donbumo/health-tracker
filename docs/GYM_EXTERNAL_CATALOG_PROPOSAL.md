# Propuesta separada: catálogo externo de ejercicios y medios

Estado: propuesta para una fase posterior. No implementada ni incluida en el
despliegue del fix del resolver. No se ha elegido proveedor ni descargado medios.

## Identidades y variantes

Mantener `Exercise.public_id` como identidad propietaria existente. Un registro
externo se identifica por `(source, external_exercise_id)`; su nombre traducido no
es la clave. Separar movimiento, variante, equipo, posición y agarre: una prensa
horizontal no debe heredar automáticamente la demostración de una prensa vertical.
Los IDs externos retirados se conservan como referencias obsoletas, no se reciclan.

La asociación con una identidad personal debe ser explícita, auditable y aislada
por el usuario efectivo del servidor. El futuro mapping persistente registraría
identidad local, referencia externa, variante elegida, revisión y confirmación.
Revisar primero el modelo existente; cualquier migración necesaria pertenece a
esa fase, no al fix actual. No usar aliases como almacén de IDs o URLs de medios.

## Medios y licencias

Cada asset necesita ID propio, tipo (imagen, animación o video), variante
representada, autor, fuente original, licencia y versión, atribución requerida,
condiciones de redistribución/modificación, fecha de comprobación y SHA-256.
La licencia del código de un catálogo no acredita la de sus imágenes.

Revisión humana de procedencia y condiciones antes de incorporar cada lote pequeño.
Si no puede acreditarse alojamiento local, no incorporar el archivo. Conservar
originales, documentar transformaciones y mostrar créditos junto a la demostración.
Retirar un medio incompatible conserva el ejercicio y muestra fallback.

Distribuir un manifiesto versionado con rutas locales verificadas. Nada de hotlinking
ni dependencia de proveedores en tiempo de ejecución. El adaptador normaliza datos
externos hacia el registro de medios existente; no duplica el catálogo propietario.

## Importación y desambiguación

1. Detectar nombres, referencias externas y contexto de variante en un preview
   read-only. Aplicar IDs propietarios y aliases confirmados existentes.
2. Presentar coincidencias exactas compatibles. Las similitudes de texto son
   sugerencias, nunca una decisión automática.
3. Si falta variante, ofrecer selección manual con equipo/posición/agarre y la
   opción «Dejar sin vincular». Identidades ajenas no son seleccionables.
4. Confirmar mediante el servicio oficial antes de persistir el mapping. Conservar
   el nombre importado como procedencia y los snapshots históricos sin reescribirlos.
5. Aplicar el mismo mapping a hero, listado, sesión y modal; sin modificar objetivos,
   registros, cargas, RIR/RPE o historial. Permitir corregir o desvincular el mapping.

## Selección del proveedor y entrega incremental

Comparar candidatos mediante evidencia de IDs estables, variantes diferenciadas,
licencias por asset, atribución viable, alojamiento local autorizado, revisiones y
calidad de demostraciones. No aprobar un proveedor solo por tamaño del catálogo.

Primer lote: movimientos cuya variante esté confirmada por el usuario, con inventario
de cubiertos, pendientes por licencia, ambiguos y sin medio. «Prensa» permanece sin
asignación hasta confirmar su variante. No es requisito para cerrar el resolver.

Validación: fixtures ficticias con aliases, IDs renombrados/retirados, conflictos,
dos usuarios, URLs o archivos rotos, revocación de un asset y distintas variantes.
QA visual en 390 × 844 y desktop comprobará imágenes decodificadas y demostraciones,
atribuciones, fallback, ausencia de overflow y consistencia entre vistas.

La aprobación de esta propuesta y del primer lote precederá su implementación.
No hay autorización implícita para modificar mappings o datos productivos.
