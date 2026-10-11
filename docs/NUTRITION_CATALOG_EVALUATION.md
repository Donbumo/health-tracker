# Catálogo inicial: evaluación reproducible USDA / Ciqual

Evaluación local de 2026-10-09. La selección es **USDA FoodData Central, SR Legacy abril 2018, subset genérico de 37 alimentos**, revisión local `2018-04-mx37`. Esta decisión cubre la muestra revisada; no declara un catálogo mexicano exhaustivo ni equivalencia entre formulaciones regionales.

Se encontraron 26 candidatos Ciqual revisados y 18 con preparación ampliamente comparable. Los restantes se conservan como candidatos distintos o sin correspondencia revisada. No se usó puntuación ni matching automático para activar identidades.

## Adquisición y licencia

Antes de descargar se comprobaron tamaños oficiales, licencia y aproximadamente 267 GB libres en el disco local. Se descargó únicamente el archivo compacto SR Legacy y el XLSX Ciqual, con límites de 8 MB y 2 MB, y un presupuesto de expansión de 60 MB. Los originales permanecen en TEMP; el repositorio contiene sólo la extracción acotada y evidencia. No se descargó el dump general FDC ni productos Branded.

[USDA Downloads](https://fdc.nal.usda.gov/download-datasets/) publica SR Legacy 04/2018; [USDA API Guide](https://fdc.nal.usda.gov/api-guide/) indica CC0. Archivo verificado: 6,074,592 bytes; expansión ZIP: 39,791,883 bytes. La diferencia frente a tamaños redondeados publicados se conserva como medición del asset recibido.

[Ciqual 2025, publicación oficial](https://entrepot.recherche.data.gouv.fr/dataset.xhtml?persistentId=doi%3A10.57745%2FRDMHWY) ofrece el XLSX de 1,541,998 bytes: 3,484 filas de alimentos, 84 columnas, 74 constituyentes. [Documentación ANSES](https://ciqual.anses.fr/cms/sites/default/files/inline-files/Table%20Ciqual%202025%20doc%20FR_2025_11_19.pdf) y metadatos de publicación identifican Licence Ouverte. Atribución: ANSES, Table Ciqual 2025. Ciqual se conserva para comparación; no se mezcla con USDA para completar nutrientes faltantes.

[Manifest con URLs, licencias y SHA256](../examples/qa/nutrition-intelligence/source-manifest.json):

- SR: `b80817294b8850530aaedf2e515c02593b1824f763a0ff356e5c2081643e6fd0`.
- Ciqual: `5555c572fa3735991298d832d0427788fa69a11b4fd20a5d580d58942369fbb0`.

## Evidencia de la muestra

Los 37 alimentos USDA tienen porciones explícitas; 36 aportan 27 nutrientes mapeados y uno 23. No se deriva net carbs de otro campo ni se convierte vitamina A IU. Se conservan FDC_ID, descripción original, edición, unidades originales, método de derivación, límites/observaciones y peso por porción. Una porción definida conserva el peso de la cantidad original USDA, cuya cantidad aparece en su etiqueta; no se divide el peso entre esa cantidad.

Ciqual conserva los valores fuente crudos: 9 celdas de traza, 417 bajo límite y 153 ausentes en los candidatos revisados. Son conteos de celdas en esta muestra, no porcentajes del dataset ni ingesta. No se convierten a cero.

Se revisó arroz sin enriquecer (`169757`), descartando el candidato enriquecido como equivalente. Queso fresco no se sustituye por fromage frais; jalapeño no se equipara a piment genérico; nopal, frijol negro y pinto no reciben sustitutos inventados. Asado, a la plancha, hervido y preparación no especificada permanecen diferenciados. La similitud amplia no permite intercambiar IDs, valores o porciones.

| Alimento revisado | FDC_ID | Ciqual candidato | Preparación ampliamente comparable | Nota revisada |
| --- | --- | --- | --- | --- |
| Tortilla de maíz | 175036 | 7813 | No | Corn tortilla candidate: regional formulation and ready-to-bake/fry vs ready-to-fill differ; not identical. |
| Arroz blanco cocido | 169757 | 9104 | Sí | White long-grain rice cooked unenriched without salt vs cooked white rice without salt; broadly comparable edible state, distinct source identities. |
| Frijol negro cocido | 173735 | Sin correspondencia revisada | No | No reviewed equivalent with matching state/preparation; absence is not proof dataset lacks all alternatives. |
| Frijol pinto cocido | 175200 | Sin correspondencia revisada | No | No reviewed equivalent with matching state/preparation; absence is not proof dataset lacks all alternatives. |
| Pechuga pollo asada | 171477 | 36018 | No | USDA roasted vs Ciqual grilled/pan-fried breast: preparation differs. |
| Huevo cocido | 173424 | 22010 | Sí | Comparable broad edible state; source formulations and analytical methods remain distinct. |
| Aguacate crudo | 171705 | 13004 | Sí | Comparable broad edible state; source formulations and analytical methods remain distinct. |
| Jitomate crudo | 170457 | Sin correspondencia revisada | No | Ciqual only regional Martinique raw tomato located; not generic equivalent selected. |
| Leche entera | 172217 | 19024 | No | USDA 3.25% without A/D enrichment; Ciqual whole pasteurized; fat specification differs. |
| Yogur natural entero | 171284 | Sin correspondencia revisada | No | Whole plain yogurt: no sufficiently precise reviewed Ciqual identity selected. |
| Queso fresco | 172223 | Sin correspondencia revisada | No | Mexican queso fresco is not French fromage frais; no substitute. |
| Avena seca | 169705 | 9310 | Sí | Comparable broad edible state; source formulations and analytical methods remain distinct. |
| Plátano crudo | 173944 | 13005 | Sí | Comparable broad edible state; source formulations and analytical methods remain distinct. |
| Manzana con piel | 171688 | 13039 | Sí | Comparable broad edible state; source formulations and analytical methods remain distinct. |
| Naranja cruda | 169097 | 13034 | Sí | Comparable broad edible state; source formulations and analytical methods remain distinct. |
| Papaya cruda | 169926 | 13035 | Sí | Comparable broad edible state; source formulations and analytical methods remain distinct. |
| Mango crudo | 169910 | 13025 | Sí | Comparable broad edible state; source formulations and analytical methods remain distinct. |
| Piña cruda | 169124 | 13002 | Sí | Comparable broad edible state; source formulations and analytical methods remain distinct. |
| Fresa cruda | 167762 | 13014 | Sí | Comparable broad edible state; source formulations and analytical methods remain distinct. |
| Limón verde crudo | 168155 | 13067 | Sí | Comparable broad edible state; source formulations and analytical methods remain distinct. |
| Zanahoria cruda | 170393 | 20009 | Sí | Comparable broad edible state; source formulations and analytical methods remain distinct. |
| Brócoli cocido | 169967 | 20351 | No | Ciqual average cooked vs USDA boiled/drained without salt; not identical. |
| Espinaca cruda | 168462 | Sin correspondencia revisada | No | Ciqual frozen raw spinach candidate differs from fresh; no substitute. |
| Cebolla cruda | 170000 | 20034 | Sí | Comparable broad edible state; source formulations and analytical methods remain distinct. |
| Calabacita cocida | 169292 | 20021 | No | Ciqual cooked courgette unspecified method vs USDA boiled/drained. |
| Pepino con piel | 168409 | 20019 | Sí | Comparable broad edible state; source formulations and analytical methods remain distinct. |
| Papa cocida | 170440 | Sin correspondencia revisada | No | No reviewed equivalent with matching state/preparation; absence is not proof dataset lacks all alternatives. |
| Elote cocido | 169999 | 20049 | Sí | Comparable broad edible state; source formulations and analytical methods remain distinct. |
| Res molida cocida 90/10 | 171794 | 6253 | No | Ciqual 10% ground beef cooked method unspecified vs USDA crumbles pan-browned. |
| Lenteja cocida | 172421 | 20360 | Sí | Comparable broad edible state; source formulations and analytical methods remain distinct. |
| Garbanzo cocido | 173757 | 20507 | Sí | Comparable broad edible state; source formulations and analytical methods remain distinct. |
| Cacahuate crudo | 172430 | Sin correspondencia revisada | No | Ciqual peanut without added salt preparation not precise; no substitute. |
| Semilla calabaza seca | 170556 | Sin correspondencia revisada | No | No reviewed equivalent with matching state/preparation; absence is not proof dataset lacks all alternatives. |
| Nopal cocido | 169388 | Sin correspondencia revisada | No | No reviewed equivalent with matching state/preparation; absence is not proof dataset lacks all alternatives. |
| Chile jalapeño crudo | 168576 | Sin correspondencia revisada | No | Generic piment is not confirmed jalapeno; no substitute. |
| Atún en agua escurrido | 173709 | 26039 | No | Tuna canned in water: Ciqual species unspecified. |
| Pan integral | 172688 | 7110 | No | Whole wheat flour specification differs between countries. |

## Snapshot y reproducción

[Snapshot local](../examples/qa/nutrition-intelligence/catalog-sample.json): 572,570 bytes, 37 alimentos. SHA del archivo: `32a76b7eb02d78ea32383bda8b231366528562b05a108b4ac075b5aa920214e0`. SHA de JSON canónico que persiste el adaptador: `b1b96afe3d58c12c438532d538383a1f4ace4ec6947378ad78f4762bdbf87bd9`.

[Comparación con valores originales](../examples/qa/nutrition-intelligence/comparison.json), [IDs y decisiones revisadas](../examples/qa/nutrition-intelligence/selection.json), [candidatos](../examples/qa/nutrition-intelligence/candidates.json).

Desde la raíz, con Python y openpyxl disponible únicamente en el entorno de evaluación:

```powershell
.\.venv\Scripts\python.exe scripts/nutrition/evaluate_sources.py
```

El script no registra salud personal ni llama a una API con credenciales. Los IDs de `selection.json` son decisiones explícitas; la búsqueda de nombres sólo propone candidatos. Si cambian los bytes de un asset, revisar manifest y diferencias antes de activar otra revisión.

La antigüedad SR Legacy, las formulaciones regionales y el subset pequeño limitan la decisión. Se pueden incorporar fuentes/ediciones posteriores con revisión explícita. Open Food Facts queda fuera de esta entrega. No se midió NAS ni se recomienda activación productiva sin los gates de migración y concurrencia.
