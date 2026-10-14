# Nutrition Experience 2.1 — implementación local para revisión

Rama: `feature/nutrition-experience-import-2-1`. Base verificada al iniciar:
`origin/master = 6cf6a965c5e426f4c0370d4ad6616edbd549245d`.
Checkout principal; commit, push y PR autorizados tras la revisión del ZIP.
No merge, despliegue, NAS, nuevas
instancias, stacks ni worktrees. Todos los registros de validación son ficticios;
el catálogo compartido contiene datos alimentarios públicos reales.

Últimos ajustes previos al PR: resumen móvil del día/último registro antes de
navegación y fecha; arroz integral simple antes de harinas/pastas derivadas,
respetando consultas explícitas. Evidencia focal y pendientes en
[revisión final](NUTRITION_EXPERIENCE_2_1_FINAL_REVIEW.md#dos-ajustes-previos-al-pr--2026-10-14).

## Experiencia implementada

`/nutrition/` reúne DailyNutrition, NutritionMeal/Item y MealLog. Incluye anterior,
siguiente, selector de fecha, calendario con registros, último día, historial
reciente, resúmenes de semana/mes y períodos 7/30/90. Un día vacío muestra el
historial reciente, aunque esté fuera del período elegido. El desglose legacy
se consulta en esta misma pantalla; las proyecciones de MealLog no se muestran
como otra comida. Edición original, importación existente y exportación siguen
accesibles. Este read model no recalcula ni modifica días anteriores.

Las tendencias separan total/neto, días comparables, subtotales parciales,
medias móviles, gasto y balance disponible. Ausencia es `None`, nunca cero;
el balance requiere ingesta comparable y gasto en la misma fecha. Las barras
rayadas indican subtotales; los huecos indican desconocido. La media usa días
con datos comparables, no todos los días del calendario.

La biblioteca distingue catálogo público, productos privados, recetas y planes
prescritos. Los planes pueden editarse con revisión optimista. Usar un plan
crea un borrador con snapshots fijados y vuelve a exigir revisión de identidad
y cantidad. Guardar un plan o una receta no registra consumo.

## Importación y servicios reutilizados

Importar archivo está integrado en Nutrición y enlazado desde Import Hub. El
adaptador `nutrition_sources` está registrado en ImportAdapterRegistry. La
extracción por contenido/firma es read-only; después se conserva el original
con `store_uploaded_file`, aislado por el owner efectivo. SchemaDetector,
AssistedImportService y StandardJsonGenerator validan el documento revisado.
StandardImportExecutor ejecuta el nuevo target `nutrition_import` y mantiene
ImportAuditService, confirmación firmada, planificación y transacción completa.
Los productos usan el servicio mobile oficial; los días agregados reutilizan
el adaptador de DailyNutrition; los consumos usan MealDraft/confirm y su
proyección legacy; las recetas usan el servicio de snapshots existente.

Flujo: archivo → perfil y destino → correcciones por fila → identidades reales
y cantidades → confirmación → resultado. Se pueden omitir filas, cambiar
vínculos, retirar/añadir ingredientes, cancelar y crear propuestas privadas.
Los porcentajes de ingredientes requieren masa total explícita. No se infieren
proporciones ni IDs por el nombre del plato. Destinos: plan, consumo, producto,
receta o agregado diario. Las fechas existentes bloquean hasta omitir o confirmar
una entrada distinta; un agregado diario nunca reemplaza una fecha existente.

Las unidades, cantidades, tipo de comida y fecha de consumo ausentes bloquean
su confirmación cuando son necesarias. “Carbohidratos” sin total/neto requiere
clasificación explícita o conservarlo sin contabilizar. Una unidad incompatible
no se prellena bajo otra unidad. No se convierten porcentajes de referencia en
cantidades absolutas ni se asumen densidades.

## Declaración y composición

El snapshot 2.1 separa declaración original, valores confirmados, composición
calculada y su calidad. La revisión compara energía/proteína y micros conocidos
antes de guardar. Los micros de ingredientes se presentan como estimados, sin
certificación. Los valores originales permanecen en evidencia y recibos.

La preparación QA de arroz con pollo conserva **450 kcal y 35 g de proteína**;
se vinculan explícitamente 80 g de pechuga asada y 140 g de arroz cocido, usando
IDs USDA reales. La masa restante no se inventa. El cálculo de ingredientes
permanece separado y parcial; no se fuerzan factores para coincidir con el archivo.
Una preparación sin macros declarados también admite subtotales parciales de
los ingredientes identificados. Estos subtotales no confirman déficit.

Cambiar proporciones actualiza la composición y exige revisión otra vez, sin
reescribir el original. Un factor explícito de porción escala el consumo y los
ingredientes. Un rendimiento declarado se conserva como evidencia; no estima
retención de nutrientes ni vuelve equivalentes crudo/cocido. La composición
“completa” exige masa explícita y balanceada. La masa conocida no puede superar
la porción sin rendimiento explícito coherente; esto bloquea sumar un plato
completo junto con sus componentes.

## Productos y cámara

Cámara/galería usa un input `capture=environment` y admite PNG/JPG/WebP. OCR
local con modelos ONNX instalados, sin enviar imagen, PDF o texto a IA externa.
Se revisan nombre, marca, código, contenido neto, base y nutrientes. Una foto
de un plato no determina una receta. Los campos ilegibles se completan manualmente.

El producto privado conserva base explícita g/ml, porción revisada y evidencia.
Los campos legacy por 100 g sólo se proyectan desde una base en gramos. Un
producto por ml sin densidad mantiene esos campos desconocidos; su declaración
completa se edita en Nutrición con token y revisión. La API legacy rechaza una
conversión incompatible con 422, no 500. Editar alimento o receta no modifica
las comidas consumidas anteriores.

Los originales siguen la retención del archivo privado de la cuenta. La
revisión pendiente vence a las 24 h; cancelar no elimina el archivo original.
No hay eliminación automática de fotos. La corrección final añade eliminación
explícita de un original no confirmado, con CSRF, revisión, owner, integridad y
guards de referencias; cierra la revisión y conserva texto/evidencia extraídos.
Los originales confirmados se retienen para auditoría. La gestión de almacenamiento/backup sigue el mecanismo oficial;
esta rama no borra archivos personales ni cambia políticas de retención.
La búsqueda OFF externa es opcional, requiere consentimiento por consulta,
usa caché/límites y envía sólo marca o código público. No incorpora datos
automáticamente. `NUTRITION_EXTERNAL_LOOKUP_ENABLED=false` por defecto.

## Migración y contratos

Único nuevo head: `20261013_0045`, después de `20261009_0044`. Añade cinco
columnas e índice de búsqueda/barcode al catálogo, y tablas owner-only de
revisión, planes y recibos. El backfill sólo normaliza índices del catálogo;
no modifica Food IDs, recetas existentes, DailyNutrition ni snapshots.

0044 no se downgradó. El rollback 0045 se niega antes de DDL si hay registros
privados nuevos. La alternativa operativa es desactivar el feature flag.
`NUTRITION_INTELLIGENCE_ENABLED=false` sigue siendo el valor predeterminado.

El contrato `nutrition_import_2_1.schema.json` es explícito y no genera IDs
ficticios. Export/restore completo acepta bundles 2.0 anteriores y produce 2.1
cuando hay estructuras nuevas; remapea ownership, productos, planes y recibos,
sin reescribir eventos existentes diferentes. Portable v1 bloquea una
exportación que perdería snapshots, micros o planes. Los contratos mobile
existentes no añaden campos requeridos.

## Corrección final de producto

Ver [revisión final](NUTRITION_EXPERIENCE_2_1_FINAL_REVIEW.md): gráficas y medias
móviles visibles, ranking por palabras y preparación, OFF precargado pendiente,
biblioteca con búsqueda/paginación, eliminación segura de originales no
confirmados y revisión en cuatro etapas. No cambia migración, dataset ni
schemas públicos previamente revisados.

## Evidencia y límites de entrega

- [Informe de catálogo](NUTRITION_EXPERIENCE_2_1_CATALOG.md).
- [Informe de importación](NUTRITION_EXPERIENCE_2_1_IMPORT.md).
- [QA y compatibilidad](NUTRITION_EXPERIENCE_2_1_QA.md).
- [Comparación visual](NUTRITION_EXPERIENCE_2_1_VISUAL.md).
- [Galería real Flask/Jinja](../design/nutrition-intelligence-2-1/gallery.html).
- [Fuentes y hashes](../examples/catalog/nutrition-2-1/manifest.json).

Entrega funcional local para revisión. No autoriza despliegue ni activación.
OCR de documentos arbitrarios, fórmulas XLSX, retención de nutrientes por
cocción y smoke físico Android/iOS no se presentan como capacidades verificadas.
Los límites de tamaño del backup vigente siguen aplicando; una historia extensa
con muchos snapshots requiere evaluar su tamaño antes de cualquier rollout.
