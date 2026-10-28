# Corrección funcional de importación nutricional: consumos declarados

Fecha: 28-10-2026. Base: master `1cf8d830ba801a8c8121cf594b07a0269a6d6e6f` (PR #29).
Rama: `codex/nutrition-import-declared-consumption`. PR correctivo independiente; pendiente de revisión técnica. Sin merge ni despliegue.

## Causa raíz y corrección

El bloqueo era de dominio. `nutrition_import.validate_document` exigía bindings para cada consumo y `nutrition_intelligence.confirm` rechazaba snapshots con ingredientes vacíos. Además, `nutrition_portability.validate_snapshot` repetía esa restricción. Por eso una declaración válida quedaba bloqueada si no había una referencia al catálogo. El schema 2.1 ya permite bindings/ingredientes vacíos y declara por separado nutrientes y composición: no se necesita DDL ni ampliar el JSON público.

La revisión ofrece tres decisiones explícitas: vincular una identidad revisada, crear un producto privado o usar la declaración sólo para este consumo. La tercera conserva `ingredients=[]`: no crea identidades falsas, productos ni recetas. Requiere nombre, fecha/momento válidos, cantidad positiva, base y unidad compatibles y al menos un nutriente absoluto válido. Los nutrientes ausentes permanecen desconocidos. Trace, below_limit, cero y procedencia siguen en la declaración original del snapshot. Un porcentaje no se convierte a cantidad absoluta editando un campo numérico.

La creación contextual reutiliza `new_food` y `mobile_health.create_food` dentro del adaptador transaccional oficial. Nombre, marca, código, base y nutrientes se precargan y pueden corregirse. No escribe dominio al buscar o aplicar decisiones. Una definición existente con mismo nombre/marca bloquea la propuesta: el usuario debe vincularla o usar sólo la declaración. No se sustituye ninguna definición. La procedencia del alimento privado usa campos escalares compatibles con el contrato de exportación; la evidencia original completa sigue en declaración y recibo.

Cada excepción tiene su consulta propia, candidatos y selección. Buscar usa el POST de decisiones de revisión para conservar también los campos de otras filas; no hace escrituras de dominio. También se admiten consultas GET independientes y read-only. `FoodCatalog.search(..., progressive=True)` recupera coincidencias progresivas por términos normalizados, traducciones léxicas revisadas, marca, identificador o código. Prioriza identidad exacta y número de términos coincidentes, conservando las distinciones de preparación del catálogo. La búsqueda ordinaria anterior conserva su modo estricto. Ningún resultado textual confirma identidad; la opción muestra nombre, marca, preparación, fuente y revisión y conserva la revisión seleccionada para su validación.

## Cantidad, base y autoridad

Las unidades de botella/lata/barra/tortilla/sobre/pieza se normalizan a `portion` conservando su nombre original en procedencia. No se deduce su peso del nombre. Una equivalencia a g/ml necesita cantidad, unidad y verificación explícitas; la propuesta aproximada original queda conservada como evidencia. La casilla exige comprobar esa equivalencia, no aceptar una conversión inferida. Sin equivalencia se permite una declaración por la misma porción comercial, conservando masa desconocida. No se mezclan dos nombres distintos de porción como si fueran equivalentes.

`portion_amount` y `portion_unit` existentes representan la cantidad compatible con la base; la cantidad original y equivalencia revisada viajan en `declaration.provenance.consumed_quantity`. El snapshot conserva la base original antes de escalar. Se aplica una sola vez `cantidad / base`, también para 1,5 porciones. Una declaración por comida ya admitida con base portion y gramaje de composición mantiene su semántica anterior. La composición calculada se conserva separada y no se suma a la declaración para producir las calorías.

Para un día existente se agrupa la decisión por fecha: conservar y añadir sólo si son consumos distintos. Si hay agregado legacy, además se exige resolver su autoridad. El lote rechaza decisiones contradictorias para la misma fecha. No sobrescribe el agregado: guarda su baseline mediante el servicio existente y evita sumarlo cuando el usuario declara solapamiento. Los 21 eventos de una fecha nueva se ejecutan como un lote, sin convertir cada evento posterior al primero en un conflicto nuevo.

## Contratos y transacción

| Capa | Cambio |
| --- | --- |
| Extracción | Destino JSON explícito, unidades nominales y equivalencias propuestas; no escribe dominio ni llama IA. |
| Borrador | Consultas por fila, resolución explícita y equivalencia revisada en el JSON técnico existente. Revisión optimista y TTL intactos. |
| JSON público 2.1 | Sin propiedades, enums ni schemas nuevos. Se utiliza el contrato existente de declaración, bindings vacíos, porción y procedencia. |
| Validador/importador | Admite consumo declarado sin bindings únicamente con cantidad/base verificables y nutrientes suficientes. Plan/receta siguen requiriendo composición. |
| Snapshot/restore | Admite consumo declarado sin ingredientes; recalcula desde la declaración congelada y comprueba paridad. No toma valores actuales del catálogo para un consumo histórico. |
| Persistencia | Mismos modelos, Alembic 0046, ejecutor, escrituras oficiales y recibo por archivo. Sin dependencias ni contrato móvil nuevo. |

La confirmación global mantiene owner efectivo, CSRF, firma de documento/plan/revisión, caducidad y consentimiento de consumo. Un evento/archivo produce un recibo; replay no crea consumos adicionales. Un fallo después de hacer flush de un producto y consumos revierte todo el dominio. No hay guardado parcial de dominio. Se pueden conservar decisiones parciales del borrador y reanudarlo como antes.

## Escenario representativo y decisiones humanas

Fixture pública y completamente ficticia: [consumed-21.json](../examples/qa/nutrition-import-ux/consumed-21.json); catálogo sintético separado [consumed-catalog.json](../examples/qa/nutrition-import-ux/consumed-catalog.json). Veintiún registros, misma fecha local, nombres españoles, marcas mexicanas inventadas, macros explícitos, micronutrientes ausentes y estados calificados.

Estado inicial comprobado: **21 detectados, 1 listo, 20 requieren decisión, 0 no importables**. Después de resolver las incertidumbres: **21 guardados, 0 pendientes**. Gate decisivo cumplido: no se bloquea una declaración suficiente por carecer de referencia al catálogo.

QA móvil acepta declaraciones suficientes en grupo, verifica cinco equivalencias y selecciona además un candidato existente para probar esa vía: 21 consumos, 0 productos, 1 recibo. QA escritorio hace lo mismo y elige crear un producto para la barra: 21 consumos, 1 producto, 1 recibo. No se obliga a crear productos para los demás consumos. Una decisión individual de otra fila se conserva al buscar.

La aceptación de declaraciones y el consentimiento final son explícitos. Las cinco equivalencias requieren comprobación del usuario; una fuente aproximada no se verifica automáticamente. La creación del producto es opcional. Si hay datos previos, las decisiones de conflicto y autoridad se añaden explícitamente por fecha. Cantidades, unidades, porcentajes o bases realmente ambiguas siguen bloqueando.

### Resultado por fila en MariaDB QA

Escenario mixto: dos identidades existentes (incluida la única exacta inicial), un producto privado explícito y dieciocho consumos sólo declarados. Los totales nutricionales proceden de las declaraciones aceptadas.

| Fila QA | Cantidad original | Base nutricional | Resolución | kcal guardadas |
| --- | --- | --- | --- | ---: |
| 1. QA arroz cocido | 100 g | 100 g | Identidad existente | 100 |
| 2. QA pechuga de pollo asada | 100 g | 100 g | Identidad existente | 101 |
| 3. QA frijoles de olla | 100 g | 100 g | Declaración sin producto | 102 |
| 4. QA ensalada de jitomate | 100 g | 100 g | Declaración sin producto | 103 |
| 5. QA bebida botella Comercial MX | 1 botella | 100 ml | Declaración sin producto | 624 |
| 6. QA bebida en dos latas Marca Inventada | 2 latas | 100 ml | Declaración sin producto | 993.3 |
| 7. QA barra Amaranto MX | 1 barra | 100 g | Producto privado explícito | 47.7 |
| 8. QA tortillas de maíz | 7 tortillas | 100 g | Declaración sin producto | 187.25 |
| 9. QA sobres de cacao | 5 sobres | 100 g | Declaración sin producto | 43.2 |
| 10. QA cereal porciones sin masa | 1.5 porciones | 1 porciones | Declaración sin producto | 163.5 |
| 11. QA yogur Marca Ficticia | 100 g | 100 g | Declaración sin producto | 110 |
| 12. QA queso panela | 100 g | 100 g | Declaración sin producto | 111 |
| 13. QA aguacate | 100 g | 100 g | Declaración sin producto | 112 |
| 14. QA avena cocida | 100 g | 100 g | Declaración sin producto | 113 |
| 15. QA pan integral Comercial QA | 100 g | 100 g | Declaración sin producto | 114 |
| 16. QA leche semidescremada | 100 g | 100 g | Declaración sin producto | 115 |
| 17. QA atún en agua Marca QA | 100 g | 100 g | Declaración sin producto | 116 |
| 18. QA nopales cocidos | 100 g | 100 g | Declaración sin producto | 117 |
| 19. QA manzana | 100 g | 100 g | Declaración sin producto | 118 |
| 20. QA salsa casera | 100 g | 100 g | Declaración sin producto | 119 |
| 21. QA tostadas horneadas | 100 g | 100 g | Declaración sin producto | 120 |

Total del lote: **3729.95 kcal**. Las 2 latas de 473 ml dan 946 ml y 993,3 kcal según su base ficticia de 100 ml. La barra de 45 g da 47,7 kcal, sin sumar nuevamente su composición. Las 1,5 porciones sin masa dan 163,5 kcal y mantienen masa/cobertura por masa desconocidas. El día legacy QA conserva sus 200 kcal de baseline disjunto y queda en 3929.95 kcal; el snapshot del día previo permanece idéntico.

## Validación y evidencia

- SQLite: 188 pruebas del área de Nutrition/importador PASS; 102 pruebas de restore/backup y vistas Unified/Energy PASS. Bloque final: 75 PASS, incluidas 19 pruebas de consumos, tras los últimos ajustes; [resultados finales](../design/nutrition-import-consumed/qa/checks.json). Última verificación de consumos: 19 PASS sin warnings; se solapa con el bloque focal. No se suman repeticiones como pruebas nuevas.
- MariaDB QA local aislada: 0046, `db check` PASS en READ COMMITTED y REPEATABLE READ. Fixture 21, selección existente, producto privado, nutrientes declarados, conversión/porción sin masa, mismo día, baseline legacy, owner/CSRF/firma/consentimiento, GET sin DML/DDL, rollback tras flush, confirmación concurrente 200/409 sin duplicados, replay, revisión del JSON estándar sin bindings y exportación/restore PASS. Runtime desplegado de #29 con código de esta rama montado read-only para QA; **no se afirma haber probado una imagen productiva nueva**.
- Navegador real Flask/Edge: dos flujos completos, móvil 390 claro y escritorio 1366 oscuro, y 12 combinaciones de 360/390/430/768/1024/1366 con claro/oscuro. Sin overflow ni errores JS. Verificación de filas/productos/recibo directamente en la base sintética. Cache-Control private, no-store. Cuatro POST de navegador (subir, buscar preservando decisiones, aplicar revisión agrupada, confirmar) y un replay adicional. No son conteos de teclas, selects, casillas ni equivalen a confirmar individualmente veinte alimentos.
- Compilación y Compose con configuración QA sintética PASS. Sin suites globales ni campaña general de accesibilidad; las pruebas de restore/backup responden al cambio concreto de validación de snapshots.
- GET de las 21 comidas guardadas, micros 7/30/90, Nutrition, biblioteca, dashboard y Energy con guard SQL sin DML/DDL PASS. El parámetro longitudinal del dashboard es `as_of`; `date` conserva su redirección legacy a Today.

Evidencia: [navegador y conteos reales](../design/nutrition-import-consumed/qa/browser.json), [MariaDB RC](../design/nutrition-import-consumed/qa/consumed-mariadb-READ_COMMITTED.json), [MariaDB RR](../design/nutrition-import-consumed/qa/consumed-mariadb-REPEATABLE_READ.json), [resumen móvil listo](../design/nutrition-import-consumed/qa/ready-mobile.png), [guardado móvil](../design/nutrition-import-consumed/qa/saved-mobile.png), [guardado escritorio](../design/nutrition-import-consumed/qa/saved-desktop.png), [preview móvil](../design/nutrition-import-consumed/qa/preview-mobile.png). Todo el contenido es ficticio. No se accedió al archivo operativo, a su revisión pendiente ni al NAS durante esta corrección.

## Reproducción

Desde la raíz, con el entorno Python del proyecto:

```powershell
.venv/Scripts/python.exe -m pytest -q backend/tests/test_nutrition_import_consumed.py
.venv/Scripts/python.exe scripts/nutrition/qa_consumed_ui.py
# En otra terminal con Playwright disponible en NODE_PATH:
node scripts/nutrition/ui_qa_consumed.cjs
```

El servidor de navegador usa loopback 8036, SQLite y storage temporales y cuentas QA fijas. Reiniciarlo crea un entorno nuevo. El script MariaDB `scripts/nutrition/mariadb_consumed_qa.py` exige la base local QA autorizada y head 0046 antes de crear datos ficticios; se ejecuta en contenedor efímero con `/qa` read-only y `/evidence` para los JSON agregados, una vez por aislamiento. Las credenciales de QA se inyectan fuera del repositorio y no se imprimen. No usar estos arneses contra una cuenta personal.

## Integración y despliegue preparados, pendientes de revisión

1. Revisión técnica de este PR y aceptación del gate de 21 filas; congelar HEAD aprobado. Revalidar base, reglas, conflictos y HEAD antes del squash, sin bypass.
2. Sincronizar GitHub/Windows/NAS por fast-forward y preservar informes operativos no versionados. Confirmar producción #29 saludable y conservar su imagen compatible.
3. Crear un backup consistente nuevo de DB/storage mediante el procedimiento operativo conocido, verificar checksum y restore aislado. Confirmar catálogo, flags y Alembic 0046. No alterar migraciones, volúmenes, secretos ni configuración efectiva.
4. Construir desde el squash aprobado, registrar ID/digest y validar esa imagen exacta con MariaDB QA RC/RR y smoke focal. Recrear únicamente web con Compose principal y comprobar el ID realmente ejecutado.
5. Smoke autenticado HTTP/HTTPS de importación, Nutrition 2.1/3 A/B, micros, Unified, Energy y legacy. Escribir sólo fixtures en QA; no abrir ni confirmar la importación pendiente real durante los smokes. Verificar logs, no-store e integridad histórica.
6. Ante un gate crítico, recuperar sólo la imagen anterior compatible; nunca restaurar backups antiguos sobre escrituras nuevas. Registrar cierre y observación productiva.

Este cambio se entrega para revisión; todavía no está instalado en producción. No se inicia Nutrition Intelligence C.
