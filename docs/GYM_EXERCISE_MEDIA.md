# Medios de ejercicios: identidad, cobertura y verificación

Corrección desarrollada en `fix/gym-exercise-media`, base `39d6f1f`.

## Causa comprobada

El resolver anterior indexaba únicamente `name` y `aliases` del JSON visual y
buscaba el nombre mostrado en la tarjeta. No usaba `Exercise.public_id`,
`ExerciseAlias` ni el `exercise_id` conservado en la rutina importada. Un nombre
personalizado podía estar correctamente mapeado por el importador y perder su
imagen. Los HTTP 200 de los assets solo comprobaban transporte, no asociación ni
decodificación en las tarjetas. Los tres assets nunca incluyeron una prensa.

## Asociación actual

Se reutiliza el catálogo propietario existente (`Exercise`/`ExerciseAlias`),
consultado con el usuario efectivo de la sesión. La proyección read-only resuelve
primero el ID existente del snapshot/borrador, o un nombre/alias exacto propietario
cuando no hay ID. Un ID ajeno o desconocido no se recupera por el nombre visible.

Los nombres canónicos y aliases de esa identidad se contrastan con las referencias
visuales verificadas. Solo una coincidencia inequívoca produce el enlace
`internal_exercise_id → media_asset_id`. Hero, tarjeta, thumbnail y botón de modal
reciben el mismo enlace; el navegador lo resuelve por asset ID, no por texto.
Los aliases contradictorios no se resuelven por orden ni similitud.

La vinculación se deriva al renderizar de los aliases actuales: no es un nuevo
mapping persistente y no sobrevive a retirar todos los aliases reconocibles de una
identidad. La UI no altera identidades, prescripciones ni historial.

`media_asset_id` identifica una obra. `source` y `external_exercise_id` quedan
disponibles en el adaptador neutral `catalogEntry`; un nombre de archivo de Commons
ya no se presenta como un ID externo de ejercicio. Una futura integración deberá
validar identidades externas y mappings explícitos antes de producir estos enlaces.
No hay proveedor externo, descarga masiva ni llamadas remotas nuevas en ejecución.

| Caso | Resultado |
| --- | --- |
| A: identidad con medio | `available`; la carga correcta queda como `loaded` |
| B: identidad sin medio | `no_media`; fallback compacto |
| C: import sin resolver / ID no propietario | `unresolved`; no se adivina por nombre |
| D: aliases conflictivos o variante genérica | `ambiguous`; sin asignación automática |
| E: enlace correcto pero imagen ilegible | `asset_error`; imagen oculta y aviso en modal |

El fallback no usa otra ilustración ni «Medio pendiente». El hero sin medio se
compone con texto y CTA, conservando el diseño. «Revisar variante» lleva al editor
existente: preparar preview, seleccionar identidad o crear la variante precisa,
revisar mappings y confirmar. No guarda al abrir el enlace.

## Diagnóstico de importaciones heredadas

Se verificó mediante una sesión autorizada un programa importado cuyo preview
read-only solicita mapping para sus ejercicios: el catálogo propietario está vacío.
No se confirmó el preview ni se alteraron programas, series o identidades. Este
caso es distinto de una identidad existente con alias que el resolver anterior
ignoraba. Sin identidad ni variante precisa, la presentación se abstiene.

`prensa` sin evidencia adicional necesita desambiguación. La etiqueta por sí sola
no distingue prensa horizontal, vertical o inclinada. No se añadió una imagen de
prensa: primero debe identificarse la variante y después verificar autor, licencia
y redistribución del asset compatible. La página ofrece «Vincular ejercicio» para
imports sin resolver y «Revisar variante» para identidades ambiguas, con el preview
y confirmación existentes. No se modifican silenciosamente datos personales.

La información personal inspeccionada no se incorpora a los fixtures ni a Git.

## Inventario verificable

No existe un catálogo global precargado de ejercicios: las identidades pertenecen
a cada usuario. El JSON distribuido es un registro de **tres medios**.

| Medio | Movimiento representado | Licencia |
| --- | --- | --- |
| `everkinetic:bench-press` | Press banca con barra | Everkinetic, CC BY-SA 3.0 |
| `everkinetic:barbell-back-squat` | Sentadilla con barra | Everkinetic / Urutseg, CC BY-SA 3.0 |
| `everkinetic:supinated-barbell-row` | Remo con barra y agarre supino | Everkinetic, CC BY-SA 3.0 |

Los archivos no cambian. Fuentes, hashes y atribuciones:
[ATTRIBUTION.md](../backend/app/static/images/gym/ATTRIBUTION.md).

- Catálogo ficticio local completo: 9 identidades, 5 con medio, 4 sin medio
  (3 sin cobertura y 1 ambigua); 0 imports pendientes después de confirmar.
- Día específico QA: 5 identidades, 3 cubiertas (60%), `prensa` ambigua y un
  movimiento ficticio sin cobertura. D2 prueba un hero sin imagen.
- Los tests cubren además un import/ID sin resolver y aliases contradictorios.
- Las cifras del caso productivo se reportan al usuario por separado; no se
  incorpora contenido personal al repositorio ni se mezcla con el inventario QA.

## Validación

35 tests focales Python: catálogo/aislamiento, importación oficial, web, aliases,
hero/sesión/modal y ausencia del catálogo. 7 tests Node: resolver, IDs duplicados,
estados sin asociación y cálculos existentes. Compilación y sintaxis JS verificadas.
No se cambia esquema ni se necesita migración. No se repite la suite completa:
el cambio Python es una proyección de presentación y reutiliza consultas existentes.

QA en navegador local con fixtures ficticias:

- Imágenes decodificadas (`naturalWidth > 0`), no solo HTTP 200.
- Tres medios comprobados en hero, lista, sesión y modal con atribución.
- Misma identidad entre principal y sesión; alias personalizado reconocido.
- Desconocido y ambiguo sin imágenes; fallo de imagen recuperable sin imagen rota.
- 12 combinaciones (seis anchos, claro/oscuro), más sesión en 390 y 1366.
- Regresión de rediseño: 60 combinaciones. Sin overflow ni errores de consola en
  el recorrido normal. Fallos de medios solo se inyectan en el caso negativo.
- Capturas completas de principal y sesión en 390 × 844 y 1366 × 844, dark mode,
  mediante `scripts/gym/media_qa.cjs`; se inspeccionaron visualmente.

Reproducción: iniciar `scripts/gym/media_qa_app.py` con `FLASK_SKIP_DOTENV=1`,
después `node scripts/gym/media_qa.cjs` (Playwright y Edge). La app crea almacenamiento
temporal nuevo. No usa `.env`, `/data` ni volúmenes productivos. El runner imprime el
directorio de PNG y `report.json`. Cachebuster de Gym: `media-1`.

## Cierre del alcance del resolver

El usuario autorizó integrar y desplegar el fix tras sus checks focales. La falta
de variante de prensa no bloquea esta corrección. El resolver y el fallback se
cierran por separado de la cobertura: hay tres movimientos con ilustraciones,
los movimientos sin un medio compatible siguen pendientes y no se presentan como
resueltos. No se cambian ejercicios personales ni se añaden migraciones o assets.

La ampliación se propone en [GYM_EXTERNAL_CATALOG_PROPOSAL.md](GYM_EXTERNAL_CATALOG_PROPOSAL.md),
sin seleccionar proveedor, descargar catálogos ni modificar datos productivos.
