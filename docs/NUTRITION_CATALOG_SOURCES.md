# Fuentes para catálogo local de nutrición

Consulta: 8 de octubre de 2026. Evaluación documental, sin descargar datasets
completos, sin probar sync ni escribir en NAS. Ninguna fuente queda seleccionada.
Los valores del prototipo son ficticios; no proceden de estas bases.

## Comparación

| Criterio | USDA FoodData Central | Open Food Facts | ANSES Ciqual 2025 |
| --- | --- | --- | --- |
| Licencia | CC0 1.0; atribución solicitada por USDA | Base ODbL, contenidos DbCL, imágenes CC BY-SA. Separar atribución y obligaciones al redistribuir bases derivadas | Licence Ouverte; mencionar fuente y versión y conservar sentido de los datos |
| Formato para snapshot | CSV/JSON con tablas auxiliares | CSV/JSONL; proyecto también documenta Parquet | XLSX publicado en repositorio oficial |
| Genéricos | Foundation, SR Legacy y FNDDS distinguen alimentos/análisis/consumo | Predomina producto comercial, no sustituto fiable de catálogo de genéricos | 3,484 alimentos consumidos en Francia, enfoque de composición |
| Branded/barcode | Branded con GTIN y valores de etiqueta | Cobertura internacional de productos, código y marcas | No asumir catálogo comercial por barcode |
| Micronutrientes | Varía por tipo/food; analíticos y compilados vs etiqueta. No prometer todos los nutrientes de todos los alimentos | Nutriments extensible, disponibilidad depende de etiqueta/contribuciones | 74 constituyentes, vitaminas/minerales; hay faltantes y calificadores |
| Servings | Porciones/pesos específicas de cada tipo de dataset | serving_size y cantidades; nutriments por 100g/porción, estados preparados | Composición por 100g; no se verificó tabla de porciones operativa: no asumir equivalencias |
| IDs | fdc_id + namespace/tipo; los cambios de registro reciben un nuevo FDC_ID | code, origen y revisión local; barcode no garantiza receta inmutable | Código alimentario + edición; no asumir estabilidad de significado entre ediciones |
| Actualización | Foundation semestral, Branded mensual en base; FNDDS por ciclos, SR Legacy final 2018. Cadencia de dump ≠ base/API | Exports diarios documentados, aportes comunitarios | Edición 2025 publicada; no asumir periodicidad garantizada |
| Tamaño documentado | CSV: Foundation abril 2026 3.7M comprimido/32M expandido; SR Legacy 6.7M/54M; full abril 2026 460M/3.1G | Dump completo grande; bytes actuales no verificados. Medir manifiesto/HEAD y expansión al planear sync | XLSX francés 2025: 1.5 MB publicado. Índices y snapshot normalizado requieren medición posterior |
| Offline | Sí, una vez adaptado el download local | Sí, con export filtrado local | Sí, tras adaptar XLSX local |
| Idioma/localidad | Principalmente inglés, alimentos/medidas de EEUU | Datos multilingües; cobertura/calidad heterogénea para productos locales | Francés/entorno alimentario francés; traducción y relevancia mexicana pendientes |
| Límites | No combinar bases químicas distintas; FDC_ID no es identificador eterno de una receta; tipos tienen cobertura diferente | Calidad no garantizada; faltantes de micros, variantes, etiquetas y valores preparados; ODbL exige revisar distribución/atribución | No usar faltantes/trace como cero; porciones y productos mexicanos no demostrados |

Esta matriz combina evidencia y evaluación de adecuación al proyecto. Las filas
de offline describen viabilidad de adaptación, no integración ya implementada.
No se ha medido cobertura del menú del usuario ni tamaños de índices. No se
califica «completo» un alimento por tener calorías/proteína solamente.

## Evidencia oficial y trazabilidad

- **FDC formatos y tamaños:** [USDA Downloadable Data](https://fdc.nal.usda.gov/download-datasets/).
  La tabla permite snapshots por tipo en CSV/JSON; se transcriben tamaños tal como
  se publican, sin convertir M/G a MiB/GiB ni validar bytes descargados. SR Legacy
  no recibe actualizaciones. El total comprimido no equivale a espacio de DB.
- **FDC tipos/cadencias:** [USDA Data Documentation](https://fdc.nal.usda.gov/data-documentation/).
  Foundation usa datos analíticos; FNDDS incluye composición/porciones para alimentos
  de encuesta; Branded deriva de fabricantes/etiquetas; SR Legacy es histórico.
- **FDC licencia:** [USDA API Guide](https://fdc.nal.usda.gov/api-guide/).
  Datos CC0; el proyecto debería conservar atribución además del manifest local.
- **FDC identidad:** [USDA Help](https://fdc.nal.usda.gov/help/).
  Cambios de registro pueden recibir nuevo FDC_ID; conservar la revisión importada
  y relaciones originales, sin deduplicar automáticamente por GTIN/nombre.
- **FDC base/unidades:** [Download Field Descriptions](https://fdc.nal.usda.gov/portal-data/external/dataDictionary)
  y [Foundation Foods Documentation](https://fdc.nal.usda.gov/docs/Foundation_Foods_Documentation_Apr2024.pdf).
  FoodNutrient y FoodPortion aportan mapping/gramos; revisar cada tipo antes de aceptar equivalencias.
- **OFF licencia, confiabilidad y exports:** [documentación oficial de Product Opener](https://openfoodfacts.github.io/openfoodfacts-server/api/).
  Distingue ODbL/DbCL/imágenes, declara límites de calidad y recomienda export local
  para grandes volúmenes. No se propone API de búsqueda en uso diario.
- **OFF esquema nutricional:** [Product-Nutrition Schema](https://openfoodfacts.github.io/documentation/docs/Product-Opener/schemas/schemas/product_nutrition/).
  Campos por 100g/serving/prepared y unidades normalizadas; el adaptador debe verificar
  base y unidad original y no mezclar producto preparado con vendido.
- **OFF formatos:** [repositorio oficial de exports](https://github.com/openfoodfacts/openfoodfacts-exports/blob/main/README.md)
  y [tutorial oficial de indexado local](https://openfoodfacts.github.io/search-a-licious/users/tutorial/).
  Se documenta JSONL grande y exportaciones; no se descargó el sample ni el dump.
- **Ciqual edición/licencia/faltantes:** [documentación ANSES 2025](https://ciqual.anses.fr/cms/sites/default/files/inline-files/Table%20Ciqual%202025%20doc%20FR_2025_11_19.pdf).
  La sección de reutilización exige fuente/versionado. Describe 30% de medias
  faltantes en conjunto: no atribuir ese porcentaje a cada nutriente/food concreto.
- **Ciqual publicación/tamaño:** [repositorio oficial de la edición 2025](https://entrepot.recherche.data.gouv.fr/dataset.xhtml?persistentId=doi%3A10.57745%2FRDMHWY).
  Metadatos oficiales indexados: 3,484 alimentos/74 constituyentes y XLSX 1.5 MB.
  La apertura directa del repositorio dio timeout durante la consulta; los metadatos
  fueron visibles en búsqueda. No se verificó esquema de columnas descargando XLSX.

No se incluyen referencias nutricionales normativas en esta investigación; elegir
un catálogo de alimentos no elige automáticamente valores de referencia clínica.

## Decisión propuesta para la siguiente fase

Investigar primero un subset **genérico** FDC frente a Ciqual para recetas:
FDC tiene licencia simple y porciones por tipo; Ciqual tiene snapshot compacto
y contexto europeo. Esto es una prioridad de evaluación, **no selección de fuente**.
OFF merece evaluación separada para productos locales/marcas, con la revisión de
licencia y separación del catálogo derivado que corresponda antes de redistribuirlo.
No publicar datos personales para satisfacer condiciones de ninguna fuente.

Antes de decidir: usar lista QA representativa de cocina mexicana, estados
crudo/cocido, lácteos, porciones caseras y productos locales; medir matches,
disponibilidad por nutriente, unknown/trace, unidades, IDs/revisiones, licencia
de cada asset, coste de normalización/traducción, tamaño de índice y tiempo de
búsqueda en NAS. No hay benchmark ni puntuaciones inventadas en esta entrega.

Arquitectura neutral propuesta: `FoodCatalogSource` con sync explícito y métodos
search/detail/nutrients/servings sobre snapshot. Añadir futuras fuentes manteniendo
namespace, provenance y equivalencias revisadas; no mezclar nutrientes de distintos
alimentos para «rellenar» coverage. Los alimentos personales permanecen owner-only.
Runtime sin Internet; sync únicamente tras revisión, validación y activación atómica.
