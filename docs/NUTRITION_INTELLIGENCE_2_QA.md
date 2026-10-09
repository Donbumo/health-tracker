# Nutrition Intelligence 2.0 — entrega y QA

8 de octubre de 2026. **Dirección visual y arquitectónica aprobada por el usuario.**
Los tres ajustes UI/UX de cierre se implementaron y verificaron. Readiness: sí como
base de diseño para la implementación posterior. Se detiene sin implementar backend.

## Ajustes de cierre aprobados

1. Meal Review mobile: nombre/momento en una fila y tarjetas de ingrediente
   compactas. Identidad, cantidad/unidad y confirmación explícita siguen visibles;
   contador de pendientes 4 → 3 → 0, registro bloqueado mientras haya pendientes.
   El estado de foto con cuatro ingredientes a 390 px pasa de 2715 a **2053 px**
   de alto (24.4% menos); inputs 16 px y targets ≥44 px conservados.
2. Datos parciales: **Subtotal conocido** / **Sin dato conocido**, presentación
   neutra y ninguna barra o porcentaje frente a objetivo/referencia. Sólo datos
   completos con referencia QA participan en comparación. No se alteró el cálculo.
3. Cada tarjeta de micronutrientes aclara: «Disponibilidad de datos por masa.
   No indica cumplimiento de referencia ni garantiza completitud nutricional».
   El porcentaje nunca afirma completitud del día real ni diagnóstico.

Contratos conceptuales, snapshots históricos, protección contra doble conteo y
confirmación permanecen sin cambios. Ningún archivo de backend/Android/schema
público ni migración fue editado.

## Evidencia de verificación

- Edge headless / Playwright, fixtures ficticias, archivos locales `file://`.
- `node design/nutrition-intelligence-2/qa.cjs`: **15 comprobaciones funcionales,
  204 combinaciones responsive/tema**, cero errores de página, cero requests HTTP.
- 17 vistas/estados × 6 anchuras (360, 390, 430, 768, 1024, 1366) × 2 temas.
- Ningún overflow horizontal; controles visibles de al menos 44×44 px;
  inputs/selects/textarea ≥16 px. Foco visible, Tab/Enter y preservación del input
  mientras se recalcula. Pares representativos de texto ≥4.5:1 en ambos temas.
- Pruebas semánticas: 180 g pollo QA → 297 kcal/55.8 g proteína; cero conocido
  distinto de unknown; serving definida (taza QA 158 g); ml sin densidad bloqueado;
  cantidades inválidas bloqueadas; foto pendiente exige aceptación explícita.
- Template y catálogo editados no cambian los valores de snapshots anteriores;
  repetir copia ingredientes consumidos. Search distingue crudo/cocido, vacío;
  alimento personal deja nutrientes no informados como desconocidos.
- Micros completos pueden mostrar referencia QA por separado de coverage;
  parciales y día vacío permanecen no evaluables. Search funciona offline.
- Cierre: subtotal parcial sin barra de objetivo/porcentaje de referencia/estilo
  de déficit; caveat por tarjeta; confirmación explícita por teclado (cantidad →
  unidad → cambiar → eliminar → confirmar con Enter) en 390/1366 y dark/light.
  Foco conserva el campo de cantidad, pendientes decrecen y el registro sigue
  bloqueado tras confirmar sólo un ingrediente.
- `node --check` para app.js, fixtures.js, qa.cjs y preview.cjs.
- Inspección estática de heads Alembic: un head `20260928_0043`; sin DB.
- Comandos Git mínimos de documentación y verificación staged ejecutados antes
  del commit. Se incluye sólo el diseño, documentación y QA ficticia de esta rama;
  el ZIP de revisión anterior queda como archivo local ignorado, fuera del commit.
  SHA, publicación remota y estado Git final se verifican y reportan en el cierre.

Resultados completos: [qa-results.json](../design/nutrition-intelligence-2/qa-results.json).
Galería: [gallery.html](../design/nutrition-intelligence-2/gallery.html).

## Capturas y revisión visual

**102 PNG:** para cada uno de los 17 estados hay dark/light full-page a 390 y
1366, más viewport móvil 390×844 en ambos temas. Full-page incluye la barra fija
en la posición del viewport inicial; eso no es un elemento insertado dentro del
contenido. Usar las capturas `-viewport` para revisar composición del teléfono.

Estados capturados: today, add, search, detail, saved, micros, user-food, review,
photo-candidates, photo-review, search-empty, user-food-detail, empty-day,
empty-micros, complete-day, complete-micros y text-candidates.

Se inspeccionaron visualmente capturas reales representativas de Today móvil dark,
Today desktop light, Photo Review móvil dark, Search/Detail desktop dark,
Add móvil dark, Photo Candidates móvil dark, Micros móvil light y Food Detail
móvil light; también Saved, estados completos y Review desktop. Se revisaron
jerarquía, wrapping y visibilidad de acciones. Para el cierre se inspeccionaron
Meal Review y Micronutrients en 390/1366 dark/light y Today con subtotal parcial.
La dirección cuenta con aprobación del usuario. No se afirma certificación WCAG, prueba con lector
de pantalla, teléfono físico ni QA Android productiva.

| Captura seleccionada | Enlace |
| --- | --- |
| Today mobile dark | [390×844](../design/nutrition-intelligence-2/screenshots/today-dark-390-viewport.png) |
| Add Meal mobile | [Página completa](../design/nutrition-intelligence-2/screenshots/add-dark-390.png) |
| Photo Recognition | [Página completa](../design/nutrition-intelligence-2/screenshots/photo-candidates-dark-390.png) |
| Meal Review mobile | [Página completa](../design/nutrition-intelligence-2/screenshots/photo-review-dark-390.png) |
| Food Search mobile | [390×844](../design/nutrition-intelligence-2/screenshots/search-dark-390-viewport.png) |
| Food Detail mobile light | [Página completa](../design/nutrition-intelligence-2/screenshots/detail-light-390.png) |
| Saved Meals | [390×844](../design/nutrition-intelligence-2/screenshots/saved-dark-390-viewport.png) |
| Micronutrients completos | [Página completa](../design/nutrition-intelligence-2/screenshots/complete-micros-light-390.png) |
| Día vacío | [390×844](../design/nutrition-intelligence-2/screenshots/empty-day-dark-390-viewport.png) |
| Today desktop light | [1366](../design/nutrition-intelligence-2/screenshots/today-light-1366.png) |
| Review desktop dark | [1366](../design/nutrition-intelligence-2/screenshots/photo-review-dark-1366.png) |
| Search/Detail desktop dark | [1366](../design/nutrition-intelligence-2/screenshots/search-dark-1366.png) |

## Reporte de los 30 puntos solicitados

| # | Punto | Resultado |
| --- | --- | --- |
| 1 | Nutrition actual audit | Código real auditado: modelos, servicios, schemas, imports, endpoints, Dashboard, AI/Operator/Coach, metas, Android y export/backup; tabla de evidencia en arquitectura. |
| 2 | Existing reusable pieces | FoodProduct, Recipe/RecipeIngredient, NutritionItem snapshots de macros, Decimal, servicios owner-only, idempotencia/revisión, cache Android y reads AI. |
| 3 | Missing concepts | Catálogo externo canónico, micros genéricos, provenance por revisión, servings múltiples, coverage por nutriente y snapshot completo del consumo. |
| 4 | Food architecture | Scope catálogo/personal, estado/preparación y revisión fijada; namespace externo sin dedup agresiva. |
| 5 | Nutrient architecture | Nutrient + FoodNutrient por filas; base/unidades/calificador y documento snapshot versionado; sin columnas SQL por cada micro. |
| 6 | Provenance | Fuente, ID, revisión, nombre, revisión nutricional y verified_at; método/originales por valor; user explícito. |
| 7 | Coverage | Peso conocido/total cuando todas las masas están resueltas, método y conteos explícitos; subtotal distinto de total y abstención ante faltantes. |
| 8 | Serving model | Conversión específica Food/revisión a g/ml; no volumen→masa sin densidad; no porciones globales inventadas. |
| 9 | Meal/template/log | Draft, Recipe evolucionada/revisada y snapshot del evento separado; repeat copia, historia no mutable. |
| 10 | Text input flow | Candidatos QA fijos → revisión → confirmación; todo pendiente. Sin AI real. |
| 11 | Photo input flow | Archivo local opcional, candidatos QA con incertidumbre, una revisión; sin lectura/subida/análisis de imagen. |
| 12 | Saved meals | Selección y registro en dos acciones, edición de cantidades y guardado de template simulados. |
| 13 | Daily nutrition | Hero, objetivos QA, meals por tipo, repeat/edit y frecuentes por conteo demo; no insights inventados. |
| 14 | Micronutrients | A revisar/en rango sólo con referencia QA y dato completo; unknown/cobertura parcial separados. |
| 15 | Food search | Catálogo QA offline, fuente, crudo/cocido, filtro personal/catálogo y sin coincidencias. |
| 16 | Food detail | Base 100 g, macros, quick add, fuente/revisión y minerales/vitaminas/otros disponibles. |
| 17 | Empty states | Día vacío, búsqueda vacía, builder vacío, micro unknown y alimento personal sin micros. |
| 18 | Catalog source comparison | FDC, OFF, Ciqual comparados con documentación oficial; licencias/tamaños/IDs/servings/limitaciones. Ninguna fuente escogida ni dataset descargado. |
| 19 | Legacy compatibility | Proyección exclusiva, agregado diario con autoridad explícita, evitar doble conteo, preservar carbs netos/totales y exports/API Android versionados. Sin borrar historia. |
| 20 | Mobile | 390×844 primero; QA en 360/390/430; barra de navegación y targets táctiles. |
| 21 | Desktop | Today, Review y Search/Detail en dos columnas; 768/1024/1366 verificados. |
| 22 | Dark/light | Variables de tema y switch; todas las vistas/estados verificados en ambos. |
| 23 | Accessibility | Etiquetas, skip link, regiones, aria-current/status, teclado, foco, targets y texto; límites de QA declarados arriba. |
| 24 | Files | Docs de arquitectura/fuentes/QA e índice; carpeta design con HTML/CSS/JS, fixtures, harness, preview local, README, galería y resultados. |
| 25 | Screenshots | 102 PNG QA reales, enlaces anteriores y galería. |
| 26 | Tests/checks | 15 funcionales, 204 responsive/tema, syntax Node, integridad de enlaces y checks Git. Suite productiva no ejecutada porque no se modificó backend. |
| 27 | Backend changes | **0** archivos productivos modificados. |
| 28 | Migration | **Ninguna**. Sin DB, NAS ni volúmenes persistentes. |
| 29 | Git status | Rama design/nutrition-intelligence-2. Cierre autorizado con commit `design: define nutrition intelligence experience` y push de esta rama; SHA/remoto/Git limpio se verifican en el reporte final. Sin merge/tag/NAS. |
| 30 | Readiness | **Sí**, dirección aprobada y tres ajustes verificados; base lista para la implementación posterior planificada. Stop gate de backend permanece aplicado. |

No hay modificaciones a backend, Android, schemas públicos ni datos existentes.
El historial, las referencias clínicas y la adquisición de catálogos se diseñaron
como pasos posteriores y no se ejecutaron.
