# Nutrition 2.1 — catálogo y fuentes

Estado: datos públicos reales normalizados y activados únicamente en QA local.
Consulta cotidiana sin Internet. Total: **13,685 alimentos**,
cuatro fuentes separadas; ningún nutriente ausente se completa desde otra fuente.

| Fuente | Alimentos | JSON local | Licencia declarada por fuente | Revisión local inmutable |
| --- | ---: | ---: | --- | --- |
| usda_sr_legacy | 7,793 | 32.02 MiB | CC0-1.0 | `2018-04-full-ni21-v1` |
| usda_foundation | 363 | 0.97 MiB | CC0-1.0 | `2026-04-30-ni21-v1` |
| usda_fndds | 5,432 | 27.07 MiB | CC0-1.0 | `2021-2023-ni21-v1` |
| open_food_facts | 97 | 0.29 MiB | ODbL-1.0 | `2026-10-13-mx100-ni21-v2` |

USDA conserva SR Legacy completo, Foundation y FNDDS. Foundation contiene 363
identidades válidas; 32 entradas publicadas null/tombstone no generan IDs. Hay
un vector vacío en Foundation y uno en FNDDS: desconocido, no cero.
OFF es una muestra acotada de México de 100 productos solicitados, 97 con
identidad/base admitidas; tres no inventan datos para superar validación.
No representa todo el mercado mexicano. Premier Protein no está disponible en
esta muestra local: la ruta de producto privado sigue disponible.

## Decisiones de adquisición y licencia

Se revisaron tamaños oficiales antes de adquirir conjuntos: los tres archivos
USDA elegidos suman unos 9.9 MiB comprimidos. Se evitó el CSV FNDDS de 1.6 GB
expandido y los dumps branded/full de mucho mayor tamaño. Los JSON locales
sumados ocupan 60.35 MiB. No se usa API key ni una
consulta remota por búsqueda local. El staging observado en SQLite QA tarda
aproximadamente 8 segundos para las cuatro fuentes; no es una medida del NAS.

USDA publica datos en dominio público/CC0; se conserva atribución USDA FoodData
Central. OFF se distribuye separadamente bajo ODbL-1.0, con atribución a sus
contribuidores y su licencia, sin fotos comerciales. La biblioteca privada y
las recetas de usuarios no se envían ni contribuyen automáticamente a OFF.
La partición de fuentes mantiene trazabilidad y obligaciones de cada dataset.

Fuentes primarias: [datasets USDA](https://fdc.nal.usda.gov/download-datasets/),
[guía oficial USDA y licencia](https://fdc.nal.usda.gov/api-guide/),
[API/documentación Open Food Facts](https://openfoodfacts.github.io/openfoodfacts-server/api/).
No se copia una API nutricional comercial ni se atribuye autoridad nutricional
al modelo OCR.

## Normalización y búsqueda

Identidad estable por fuente, revisión y `source_food_id`, con UUID determinista
para cada snapshot local. SHA-256 de originales y normalizados está en
[manifest](../examples/catalog/nutrition-2-1/manifest.json). Cambiar la normalización
requiere otra revisión; no reescribe una revisión validada. Los 37 alimentos
anteriores y sus snapshots históricos permanecen válidos.

Nombres originales se conservan, con 37 nombres españoles previamente revisados
y vocabulario bilingüe para búsqueda. Alias no establecen equivalencia. La
búsqueda permite fuente, preparación/estado, tipo, marca y código. Puede ofrecer
mezclas o platos relacionados: exige confirmar identidad y cantidad, sin selección
ni unión nutricional automática. Porciones son específicas de cada identidad,
no una taza universal. Los nutrientes y formas químicas conservan sus unidades.
Normalización decimal limita precisión a 12 decimales, guarda evidencia original
y nunca redondea un positivo diminuto a cero conocido.

OFF conserva la evidencia de `carbohydrates_100g`, pero no la contabiliza como
carbohidratos totales/netos sin una etiqueta que confirme su semántica. Una unidad
original porcentual tampoco se vuelve una cantidad absoluta. Los valores
comunitarios restantes se presentan como datos no certificados para revisar.

## Búsquedas verificadas

[Reporte reproducible](../design/nutrition-intelligence-2-1/qa/search-report.json):
**55 búsquedas**, incluyendo 53 públicas, una privada ficticia y un control
negativo. Incluye arroz blanco/integral, pollo crudo/asado, frijoles, tortillas,
nopal, frutas, preparaciones, Coca/Bimbo/Nestlé, Premier Protein y un barcode
real del snapshot OFF. 52/53 consultas públicas produjeron candidatos; esto es
cobertura de esta lista de pruebas, no cobertura del mercado ni exactitud de match.
Mediana SQLite QA 105.1 ms; máximo 230.4 ms, consulta limitada a
50 resultados públicos. Hardware y caché de esta máquina influyen.

Falso positivo observado para intención de ingrediente: “arroz” también ofrece
sake y platos mixtos. El ranking pone el nombre literal primero y los filtros
permiten acotar, pero no se declara precisión perfecta ni equivalencia por nombre.
“Arroz blanco cocido” puede ofrecer mezclas de arroz blanco/silvestre; hay que
confirmar preparación/fuente. El control inexistente no devuelve alimentos ni
fabrica un match. No existe ground truth para publicar una tasa de falsos positivos.

## Consulta externa opcional

OFF v2: código exacto o marca estructurada con país México, máximo 12 propuestas,
1 MiB, timeout 8 s, sin redirects. Caché 1 hora, 128 claves y mínimo 30 s por
worker entre consultas. Con los dos workers predeterminados queda por debajo
de los límites documentados de 10 búsquedas/min y 15 lecturas de producto/min/IP.
Más instancias/workers requieren revisar el límite agregado antes de habilitarlo.
Cada POST exige consentimiento; sólo se envía marca/código, nunca documentos,
imágenes ni la dieta. Se prueba con respuesta pública sintética, sin activar
el servicio externo durante las capturas.

Default: `NUTRITION_EXTERNAL_LOOKUP_ENABLED=false`. Un resultado es propuesta;
incorporación exige revisar la etiqueta y crear explícitamente el producto privado.
El builder reutiliza archivos públicos acotados en TEMP; el snapshot OFF entregado
está versionado, no se descarga el dump global por defecto.

## Ranking focal final

[Reporte de ranking](../design/nutrition-intelligence-2-1/qa/ranking-report.json):
17 consultas × cinco repeticiones; 10/10 identidades FDC SR de referencia en
posición 1. Coincidencia por palabra y traducciones revisadas: no pollo/pollock,
maíz/corned beef ni frijol/ejotes. Tortilla y chips siguen separados. El nombre
“baked … from raw” se presenta como preparación final cocida sin cambiar el
vector o snapshot publicado. Mezclas se ordenan después de ingredientes simples.

Los candidatos conservan preparación, fuente e identidad. Consultas amplias
aún ofrecen alimentos relacionados, por ejemplo productos con avena; no se
establece equivalencia ni se selecciona automáticamente un alimento.
La muestra comercial es la misma de 97 OFF. Una propuesta externa puede
seleccionarse para prefill privado y requiere revisión y confirmación.
Ver [revisión final](NUTRITION_EXPERIENCE_2_1_FINAL_REVIEW.md).
