# Nutrition Intelligence 3.0 — entrega A

Base: `730b9f3206ef3bdf8e7f36af129ad45a560b1382`. Rama independiente:
`feature/nutrition-intelligence-3-0-micros`. Fecha QA: 2026-10-26.

La experiencia diaria de `/nutrition/micronutrients` muestra energía, macros,
vitaminas, minerales y otros nutrientes con disponibilidad, cobertura por masa,
fuentes y desglose. El historial enlaza la fecha y el período seleccionados.
Cada MealLog tiene una lectura propia con todos sus ingredientes y declaraciones.
No hay DDL, migraciones nuevas, dependencias, escritores ni cambios de schemas.

## Auditoría de implementación previa

| Componente inspeccionado | Contrato encontrado y decisión A |
| --- | --- |
| `nutrition_math.py` | `NUTRIENTS` define 30 nutrientes/formas, sus unidades y grupos. `ingredient`, `summarize`, `snapshot_summary` y `summarize_parts` usan Decimal. Known cero es exacto; trace/below_limit conservan valor nulo. Reutilizados sin cambios. |
| `nutrition_intelligence.py` | Confirmación oficial guarda ingredientes, cantidades normalizadas, contribuciones, summary y, cuando corresponde, declaración y composition_summary. `daily_summary` elimina proyecciones duplicadas y respeta autoridad/baseline. A lo consume, sin otra fórmula de agregación. |
| `nutrition_history.py` | Historial owner-only, calendario y tendencias de energía. Se integra mediante enlace de fecha/período; no se reconstruye el servicio. |
| `nutrition_series.py` | Comparabilidad y medias de macros/energía; `mean` excluye None. A reutiliza esa media y añade una proyección de micros sobre summaries guardados. No modifica balances ni medias móviles de energía. |
| `food_catalog.py` | Catálogo activo por fuente/revisión validada; revisión inmutable, UUID específico y SHA. `detail(..., revision=...)` ya permite abrir revisiones archivadas. La ruta web ahora transmite esa revisión. Las identidades personales se consultan con owner y muestran su definición actual separada del consumo histórico. |
| `NutritionMeal` / `NutritionItem` | Jerarquía legacy con cantidades opcionales y macros/sodio. Un NutritionItem de proyección no es otro consumo. Sin ingredientes no se infieren vitaminas, masa ni equivalencias desde el producto actual. |
| `MealLog` | Owner, fecha local, zona horaria, proyección única y snapshot JSON del consumo. Suficiente para A; jamás se regenera desde catálogo o receta actual. |
| `FoodProduct` / `Recipe` | Definiciones personales mutables con revisión y JSON nutricional; recetas guardan snapshot e ingredientes. Enlaces verificados por owner; una edición no altera los snapshots consumidos. |
| `/nutrition/micronutrients` anterior | Sólo tarjetas de micros para una fecha. Se amplía con tablas, períodos, contribuciones y una lectura GET de MealLog. |
| Templates Nutrition 2.1 | Se conserva el historial Flask/Jinja y sus flujos de edición/importación. La tarjeta de micros abre la nueva experiencia para su fecha. |
| Dashboard unificado y Coach | Dashboard usa series comparables y summaries persistidos; Coach consume ese mismo dashboard y separa energía parcial. A no modifica sus cálculos, señales, metas ni recomendaciones. |

No se ha demostrado insuficiencia de persistencia para A: los valores consumidos,
calidades, fuentes y revisiones necesarios ya están almacenados. Se añade
`nutrition_micros.py` como fachada de lectura, sin recalcular snapshots.

## Disponibilidad real del catálogo en QA

Se activaron en SQLite efímera y MariaDB efímera los cuatro artefactos públicos
versionados en `examples/catalog/nutrition-2-1/`, antes de añadir fixtures ficticias.
La consulta usa `catalog_query()`: sólo las revisiones activas de esa copia QA.
No se copió una base personal ni se accedió al NAS, `.env`, `/data` o volúmenes
persistentes. Esto acredita las revisiones del catálogo QA; no afirma haber
inventariado el catálogo que esté activo en producción.

| Fuente y revisión QA | Alimentos | Hierro conocido | Vitamina D conocida | Folato DFE conocido | K2 conocida |
| --- | ---: | ---: | ---: | ---: | ---: |
| SR Legacy `2018-04-full-ni21-v1` | 7,793 | 7,713 | 5,185 | 6,482 | 0 |
| Foundation `2026-04-30-ni21-v1` | 363 | 351 | 52 | 0 | 0 |
| FNDDS `2021-2023-ni21-v1` | 5,432 | 5,431 | 5,431 | 5,431 | 0 |
| OFF `2026-10-13-mx100-ni21-v2` | 97 | 26 | 13 | 0 | 0 |

[Auditoría por fuente y nutriente](../design/nutrition-intelligence-3-a/qa/catalog-audit.json)
y [matriz por alimento](../design/nutrition-intelligence-3-a/qa/catalog-inventory.json)
incluyen los 13,685 alimentos, revisiones, base, posibilidad de calcular masa,
unidades canónicas y estados K=known, U=unknown, T=trace, L=below_limit, -=ausente.
La posición de cada carácter corresponde a `nutrient_order`. No se copian
definiciones personales. Los ceros conocidos se cuentan aparte; no son ausencias.

En estas revisiones públicas no hay trazas ni below_limit: su preservación se
valida con fixtures sintéticas explícitas. OFF contiene estados unknown además
de ausencias y conocidos. 28 productos OFF usan ml y 69 g; las tres fuentes USDA
usan g. Volumen sin densidad permite escalar un nutriente por ml, pero impide
calcular cobertura por masa. La matriz declara esa limitación por identidad.

Podemos calcular cantidades escaladas de nutrientes publicados/declarados para
una cantidad y base compatibles, subtotales y cobertura cuando todas las masas
necesarias están disponibles. No conocemos la ingesta de comidas no registradas,
nutrientes ausentes, densidades no declaradas, equivalencias químicas, preparación
no documentada ni la composición real de un plato legacy. La cobertura del
catálogo es disponibilidad de información, no exactitud de una dieta o de una
equivalencia entre alimentos. No se mezclan formas RAE/RE, folato DFE/alimentario
o K1/K2 para aparentar completitud.

## Semántica de pantalla y tendencias

- Completo significa disponibilidad de cantidad exacta para las partes registradas
  o una declaración confirmada con autoridad. No confirma que se registró todo el día.
- Parcial es subtotal conocido; desconocido conserva None. Cero conocido aparece
  como cero, participa en medias y tiene punto en la gráfica.
- Trace y below_limit mantienen su evidencia y límite escalado en el ingrediente.
  Una declaración original conserva sus estados y su factor de porción. La suma
  diaria no inventa una cantidad a partir de esas calificaciones.
- El aporte registrado usa summary efectivo. La composición estimada se presenta
  por separado cuando hay declaración: nunca se añade de nuevo a ésta.
- La cobertura usa `known_weight / total_weight` del servicio existente, con su
  método `mass_weighted_v1`. Si no es calculable se indica, sin usar conteo de
  alimentos como sustituto del peso. No es porcentaje de ingesta recomendada.
- Los períodos 7/30/90 terminan inclusive en la fecha elegida. Cada nutriente tiene
  media de días completos, media separada de subtotales parciales, sus denominadores
  y días desconocidos. No se divide por días naturales rellenando huecos.
- La gráfica une sólo secuencias contiguas completas. Parciales tienen marcador
  hueco independiente; desconocidos no tienen punto. Todo desconocido omite la
  gráfica de cantidades. La tabla diaria accesible conserva fecha, estado y cobertura.
- Tendencias leen summaries diarios persistidos; la fecha seleccionada usa la misma
  autoridad que `daily_summary`. Legacy sin summary sólo aporta sus campos históricos,
  como parciales, sin deducir nuevos nutrientes. A no migra ni completa ese historial.
- La fecha predeterminada procede de la sesión y zona horaria del usuario. MealLog
  usa su fecha local persistida; no se reasigna por la zona actual ni por UTC.

Los links a MealLog y receta aplican owner en servidor. Catálogo abre la revisión
consumida validada, incluso archivada. El enlace personal abre la definición
actual e indica que el snapshot conserva la revisión anterior. Si la identidad
ya no está disponible no se fabrica un enlace. El registro original conserva
agregados legacy que no pueden atribuirse a un ingrediente.

## Validación y evidencia

[Pruebas focales](../backend/tests/test_nutrition_micros.py): **16 aprobadas** en
SQLite sintética. Cubren completos/parciales, combinaciones, cero, trazas, límites
escalados, volumen sin densidad, legacy con/sin detalle, autoridad disjoint/derived,
agregado importado con micros, declaración frente a composición, revisiones de
catálogo archivadas, edición de receta/producto, proyecciones sin doble conteo,
ventanas inclusivas, medias/denominadores, zona horaria, dos propietarios,
GET sin DML y lecturas con escrituras deshabilitadas.

Regresión dirigida de Nutrition 2.1, FoodCatalog, recetas, Energy Experience 2.0,
procedencia energética, dashboard unificado y Coach: **225 aprobadas, 2 omitidas**
(symlinks sintéticos no permitidos en Windows y benchmark MariaDB opt-in del dashboard).
Las tres nuevas pruebas se ejecutaron
después en la suite focal. No se repitió una suite global ni campaña general de
accesibilidad. Compilación y `git diff --check` pasan. Compose se valida sin cargar
`.env`, con interpolación QA ficticia y sin resolver archivos de entorno.

[SQLite QA](../design/nutrition-intelligence-3-a/qa/sqlite-report.json) usa metadata
actual y stamp 0046: no afirma replay de migraciones antiguas en SQLite.
[MariaDB QA](../design/nutrition-intelligence-3-a/qa/mariadb-report.json) usa MariaDB
11.4 en loopback, contenedor propio y tmpfs, sin volumen persistente. Replay del
head existente `20261018_0046` y `flask_migrate.check` pasan. La comprobación no
detecta operaciones nuevas; las lecturas GET emiten cero INSERT/UPDATE/DELETE.
Las cantidades/estados de una misma fecha coinciden entre períodos y motores.

[QA visual](../design/nutrition-intelligence-3-a/qa/ui-report.json): Flask real,
Edge/Playwright, light/dark, anchos 360/390/430/768/1024/1366, siete estados/vistas:
84 combinaciones. Comprueba respuesta, overflow de página, captions, headers y
foco visible. Capturas revisadas en móvil y escritorio; no es certificación WCAG.
Los recortes de elementos ocultan sólo la barra fija para no tapar la figura.

- [Completo · móvil claro](../design/nutrition-intelligence-3-a/qa/complete-light-390.png)
- [Parcial · móvil oscuro](../design/nutrition-intelligence-3-a/qa/partial-dark-390.png)
- [Tendencia · escritorio claro](../design/nutrition-intelligence-3-a/qa/complete-trend-light-1366.png)
- [Tendencia · móvil oscuro](../design/nutrition-intelligence-3-a/qa/partial-trend-dark-390.png)
- [Evidencia de ingrediente · móvil](../design/nutrition-intelligence-3-a/qa/ingredient-light-390.png)

Reproducción: `.venv/Scripts/python.exe scripts/nutrition/qa_micros.py --serve`
y `node scripts/nutrition/ui_qa_micros.cjs` con Playwright ya instalado en el runtime.
`qa_micros.py --mariadb` exige exclusivamente el esquema/puerto QA que declara
el script, en un contenedor nuevo; no usa la configuración persistente de la app.

Entrega B queda sólo en [diseño de enriquecimiento revisable](NUTRITION_INTELLIGENCE_3_B_DESIGN.md).
Este PR requiere revisión técnica antes de integrar. No incluye merge, despliegue,
reconocimiento fotográfico, diagnóstico ni recomendaciones personalizadas.
