# Nutrition 2.1 — corrección final de experiencia

Entrega revisada por el usuario; commit, push y PR autorizados el 2026-10-14. Rama
`feature/nutrition-experience-import-2-1`, base
`6cf6a965c5e426f4c0370d4ad6616edbd549245d`, coincidente con el master remoto
vigente. Sin merge, NAS, producción ni datos personales. La migración 0045, los tres schemas
públicos de Nutrition/export y los cinco archivos del dataset coinciden byte
por byte con el ZIP previamente revisado: nueve archivos sin cambios.

## Seis correcciones

| Área | Comportamiento final | Evidencia |
| --- | --- | --- |
| Dashboard | Tres gráficas temporales de ingesta, gasto y balance. Media móvil visible para cada serie, cobertura de días y eje de balance con signo. | [Gráficas mobile dark](../design/nutrition-intelligence-2-1/qa/energy-trends-dark-390.png), [desktop light](../design/nutrition-intelligence-2-1/qa/energy-trends-light-1366.png), [valores y ventanas](../design/nutrition-intelligence-2-1/qa/chart-report.json). |
| Búsqueda | Palabras completas y traducciones revisadas. Ingredientes simples preceden mezclas/platos; preparación, fuente e identidad visibles. | [Ranking reproducible](../design/nutrition-intelligence-2-1/qa/ranking-report.json), [catálogo mobile](../design/nutrition-intelligence-2-1/qa/catalog-light-390.png). |
| OFF → privado | Seleccionar una propuesta abre nombre, marca, barcode, base, contenido neto y nutrientes precargados. Sigue pendiente; preview firmado y confirmación crean el producto. | [Propuesta](../design/nutrition-intelligence-2-1/qa/off-proposals-light-1366.png), [formulario mobile](../design/nutrition-intelligence-2-1/qa/off_prefill-light-390.png), [preview](../design/nutrition-intelligence-2-1/qa/off-private-pending-light-1366.png), [confirmado](../design/nutrition-intelligence-2-1/qa/off-private-confirmed-light-1366.png). |
| Biblioteca | Búsqueda por nombre/marca y tipo, conteos y páginas de 24 por sección. Sin límite total de 100; queries owner-only. | [Productos página 6](../design/nutrition-intelligence-2-1/qa/library_products_page6-dark-390.png), [125 recetas](../design/nutrition-intelligence-2-1/qa/library_recipes_page6-light-1366.png). |
| Originales | Eliminación explícita de un original no confirmado cierra la revisión. Confirmados, archivos compartidos y referencias de otros dominios se retienen. | [Cancelación y advertencia](../design/nutrition-intelligence-2-1/qa/original_retention-dark-390.png), [original confirmado retenido](../design/nutrition-intelligence-2-1/qa/confirmed_retention-light-1366.png), [eliminación](../design/nutrition-intelligence-2-1/qa/cancelled-original-deleted-light-1366.png). |
| Revisión | Cuatro etapas: identificación, cantidad/composición, declaración y confirmación. Editar una etapa conserva las otras y retira la confirmación anterior. | [Identificación](../design/nutrition-intelligence-2-1/qa/import_identity-light-390.png), [composición](../design/nutrition-intelligence-2-1/qa/import_composition-dark-1366.png), [declaración](../design/nutrition-intelligence-2-1/qa/import_declaration-light-390.png), [confirmación](../design/nutrition-intelligence-2-1/qa/compound_review-light-1366.png). |

## Lectura honesta de las gráficas

Los puntos son valores almacenados, no una interpolación ni una nueva escritura
del historial. Días legacy, nuevos, huecos, subtotales parciales y cero explícito
coexisten en el fixture de 30 días. Un parcial se dibuja como rombo y no forma
parte de la línea de días completos. El desconocido conserva su hueco.

Balance requiere ingesta completa y gasto total disponible en la misma fecha.
Las medias móviles usan sólo valores comparables en los últimos siete días;
se muestra el denominador n/7. Se leen seis días anteriores al período para
calcular correctamente sus primeras ventanas; esos días no entran en los totales
del período. La media de una fecha coincide al cambiar entre 7 y 30 días. La cobertura no se interpreta como cumplimiento
de una referencia ni garantía de completitud fisiológica. Cero explícito sí
participa en una media; ausencia de dato no. Un período totalmente desconocido
no inventa escala o puntos de cero. La validación UI recalcula independientemente
las ventanas y el balance a partir del reporte diario.

Los recortes de gráficas ocultan únicamente la navegación fija al capturar el
elemento, evitando que tape la figura. Las capturas completas conservan el shell
real. Se corrigió la superposición del cero y el extremo del eje de balance;
se inspeccionaron las figuras finales en móvil y escritorio.

## Ranking y equivalencias

Se ejecutan 17 consultas focales, cinco repeticiones cada una, sobre los 13.685
alimentos públicos reales, además de las 55 consultas generales. Diez consultas
tienen un FDC SR explícito de referencia; las diez lo muestran en posición 1.
Esto mide esa lista concreta, no precisión global ni cobertura del mercado.
Cada caso conserva top 5, identidad, fuente, preparación y cinco tiempos.
Mediana observada 107.4 ms; máximo 230.0 ms en SQLite QA
con carga concurrente de tests. Hardware y caché influyen; no es un SLA.

Maíz/corn, arroz/rice, pollo/chicken, frijol/beans y avena/oats son traducciones
de consulta; nunca unen identidades o nutrientes. Tortilla no equivale a chips. Totopos se consulta como tortilla chips; no se
consideran equivalentes los chips de maíz extruidos, como Fritos.
La coincidencia por palabra impide pollo/pollock y maíz/corned beef. Green/snap
beans son ejotes y no se incorporan como equivalencia de frijol maduro.

El filtro de preparación interpreta el nombre publicado: “baked … from raw”
es una preparación final cocida; no se ofrece como pollo crudo. Esta corrección
es de búsqueda/presentación y no cambia IDs, vectores publicados ni snapshots.
Fuentes ambiguas conservan estado mixto. Los nombres de preparación originales
siguen visibles; cocido no establece equivalencia entre hervido, asado y frito.

Una consulta amplia aún puede mostrar alimentos relacionados, por ejemplo
productos con avena. Hay que revisar nombre, preparación, fuente y porción;
no existe selección automática. Marca/barcode no certifican la etiqueta.

## Propuestas externas y retención

La consulta OFF mantiene consentimiento, caché, límites y default false.
La selección firma y liga la propuesta al owner con vencimiento de 30 minutos;
no escribe dominio. El formulario permite corregir valores y después crea un
preview distinto, también firmado, antes de la confirmación. La procedencia
pública original se conserva. Carbohidratos no clasificados no se vuelven
totales/netos automáticamente; cero conocido y ml sin densidad se preservan.

El end-to-end usa una respuesta OFF **simulada y claramente QA** con el formato
normalizado real. No se efectuó una consulta externa ni se envió una imagen o
dieta. No se presenta esa respuesta como verificación online del catálogo OFF.

Cancelar conserva el original por defecto. Antes de confirmar, o tras cancelar,
el usuario puede marcar la advertencia y eliminar el archivo explícitamente.
Se requieren sesión, CSRF, revisión vigente, pertenencia e integridad del archivo.
Se comprueban revisiones compartidas, recibos, tipo de otro importador y todas
las referencias FK a UploadedFile. Un duplicado no oculta una referencia confirmada.

La política `unconfirmed_only_v1` **bloquea** la eliminación de un original
confirmado: no elimina evidencia exigida por auditoría. Texto extraído y decisiones
de revisión se conservan y se advierte al usuario. Una revisión sin su original
no puede confirmarse. No se cambia ni borra un snapshot histórico.

La limpieza física ocurre después de un commit aceptado; un fallo transaccional
no borra el archivo. Si el sistema de archivos rechaza la limpieza posterior,
se devuelve error explícito y se requiere limpieza de almacenamiento autorizada;
no se informa una eliminación física exitosa ni se toca otro directorio.

## Validación y límites

- Pruebas focales finales: **90 PASS** (incluyen once tests nuevos de producto).
- UI Flask/Jinja: **252 PASS**, 21 vistas × seis anchos × dark/light.
- Capturas principales: 390/1366 en ambos temas, viewport mobile, cuatro etapas,
  OFF, biblioteca >100, retención y gráficas; foco visible y ausencia de overflow.
- MariaDB existente: consultas/ranking y política de archivo probados con READ
  COMMITTED y REPEATABLE READ, head 0045, sin DDL ni repetición de migraciones.
- Suite backend final: **1.272 PASS, 34 skipped**; warning esperado del ZIP
  malicioso de prueba. Ver resultado actualizado en [QA](NUTRITION_EXPERIENCE_2_1_QA.md).

Evidencia: [UI](../design/nutrition-intelligence-2-1/qa/ui-report.json),
[tests focales](../design/nutrition-intelligence-2-1/qa/focal-product-tests.xml),
[MariaDB focal](../design/nutrition-intelligence-2-1/qa/mariadb-product-report.json),
[galería](../design/nutrition-intelligence-2-1/gallery.html).

`NUTRITION_INTELLIGENCE_ENABLED=false` y
`NUTRITION_EXTERNAL_LOOKUP_ENABLED=false` siguen siendo defaults. La instancia
QA los habilita explícitamente con fixtures, y sustituye sólo su lookup externo
por la respuesta ficticia. No se modificaron Android/iOS ni sus schemas; la
suite backend cubre compatibilidad existente. No se ejecutó smoke físico nativo.

## Dos ajustes previos al PR · 2026-10-14

El primer bloque de Nutrición muestra fecha, energía y calidad del día antes de
la navegación y el selector. Si la fecha está vacía, identifica explícitamente
el último registro y su fecha; no atribuye ese consumo a hoy. Mantiene añadir
comida, fecha, historial y tendencias. La etiqueta completa/parcial corresponde
exclusivamente a energía; no certifica otros nutrientes. Legacy sin calidad
declarada conserva la presentación conservadora de subtotal conocido.

Las consultas de arroz priorizan el grano frente a harina, pasta y fideos,
salvo que el usuario pida explícitamente uno de esos derivados. No cambia
aliases, IDs, vectores, revisiones ni snapshots. Blanco/integral y crudo/cocido
siguen siendo candidatos diferentes que requieren selección y revisión.

Validación repetida únicamente del alcance afectado:

- **7 tests PASS**: ranking anterior relevante, integral/derivados y resumen
  completo/parcial/desconocido/cero/último registro. [JUnit](../design/nutrition-intelligence-2-1/qa/final-focal-tests.xml).
- **20 verificaciones de viewport PASS**: cinco estados × 390/1366 × dark/light;
  resumen completo en primer viewport, fecha disponible, teclado y sin overflow.
- **10 capturas móviles nuevas**, 390 × 844, inspeccionadas visualmente;
  [día light](../design/nutrition-intelligence-2-1/qa/final-first-day-light-390.png),
  [vacío con último registro dark](../design/nutrition-intelligence-2-1/qa/final-first-empty-dark-390.png),
  [parcial light](../design/nutrition-intelligence-2-1/qa/final-first-partial-light-390.png).
- **14 consultas × tres repeticiones** sobre el catálogo real; primer resultado
  integral simple y derivados explícitos comprobados. Tiempos corresponden a
  páginas HTML completas de Flask, no latencia SQL. [Reporte focal](../design/nutrition-intelligence-2-1/qa/final-focal-report.json).

Los resultados de suite completa, MariaDB, migración, importación y restore
arriba corresponden a la entrega previamente aprobada. No se repitieron estas
áreas ni suites completas para los dos ajustes finales.

El siguiente gate es la revisión del PR. No hay autorización de merge,
despliegue, migraciones productivas ni activación. Pendientes separados:
smoke físico Android/iOS y prueba externa real de Open Food Facts.
