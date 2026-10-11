# Nutrition Intelligence 2.0 — implementación y reporte

Estado local: implementación preparada en `feature/nutrition-intelligence-2`, con feature flag **desactivado por defecto**. **Todos los gates obligatorios aprobados; lista para PR**. Sin despliegue, merge, NAS, worktrees ni stacks Docker adicionales. Fecha: 2026-10-09.

La base es el diseño aprobado `31c80154eaaa673bb12c5f2e594a715747d3c82b`, que incluye la dirección visual y los tres ajustes finales. La implementación conserva los contratos conceptuales; los formatos públicos efectivos están en schemas. La documentación anterior de diseño permanece como evidencia histórica, con enlaces a esta fase.

## Reporte obligatorio

| # | Área | Resultado / evidencia |
| --- | --- | --- |
| 1 | Fuente de catálogo | USDA FDC SR Legacy 04/2018, elección acotada a 37 alimentos. [Evaluación reproducible](NUTRITION_CATALOG_EVALUATION.md): 26 candidatos Ciqual, 18 preparaciones ampliamente comparables; sin puntuaciones ni equivalencias automáticas. OFF queda posterior. |
| 2 | Dataset / tamaño | Revisión local `2018-04-mx37`, JSON de 572,570 bytes. URLs, licencias, SHA del archivo/canónico y dimensiones de los dos originales documentados en evaluación y manifest. Runtime sin Internet. |
| 3 | Modelos / migración | Ocho tablas aditivas: fuentes, revisiones, alimentos externos, nutrientes, valores, porciones, drafts y MealLog. Se reutilizan FoodProduct, Recipe/RecipeIngredient y DailyNutrition/Meal/Item. Única migración `20261009_0044` desde `20260928_0043`, un head. Boundary upgrade/downgrade SQLite conserva registros ficticios legacy; metadata check pasa. Cadena completa MariaDB 11.4 desde base, ciclo 0043 → 0044 → 0043 → 0044 antes de consumos, upgrade repetido y db check aprobados; ocho tablas, índices y FKs validados. |
| 4 | Nutrientes | Registro de 30 IDs y tabla extensible; energía/macros, net carbs, azúcar, minerales, vitaminas y colina. Decimal con contexto de 40 dígitos, entrada hasta 12 decimales. RAE/RE/retinol, folato alimentario/DFE y K1/K2 separados; sin factor IU universal ni inferencia de net carbs. |
| 5 | Coverage | `mass_weighted_v1`: subtotal exacto conocido, complete/partial/unknown, masa conocida/total, porcentaje nullable, método, conteos y fuentes. Cero conocido distinto de unknown; trace/below_limit conservan calificadores. Masa incompatible o ausente deja porcentaje sin determinar. Los parciales no confirman déficit. |
| 6 | Porciones | Por alimento/revisión y equivalencia explícita; gramos, ml y servings etiquetadas. Conversión volumen/masa exige densidad. Porciones USDA conservan cantidad original en etiqueta y peso por esa porción. No hay taza universal. |
| 7 | Comidas reutilizables | Recipe sigue siendo template. Guardar, usar, editar y repetir con revisión; Saved Meals ordena por frecuencia real de consumos owner-only. Guardar no consume. El reenvío de guardado no duplica ni incrementa dos veces la revisión. La UI antigua evita aplanar templates completos. |
| 8 | MealLog / snapshots | Evento independiente con identidad, revisión, fecha local, timezone, cantidad original/normalizada, fuente, revisión upstream/local y SHA del catálogo, vector y resumen completos. Hora desconocida permanece null. Repetir copia ingredientes consumidos y exige revisión nueva; editar template/catálogo no recalcula historia. |
| 9 | Compatibilidad legacy | Se mantiene DailyNutrition → NutritionMeal → NutritionItem. Calorías/macros previos se conservan y micros sin detalle no se reconstruyen. Los clientes antiguos leen la proyección con tres decimales; snapshot interno conserva precisión completa. |
| 10 | Doble conteo | MealLog y su único item de proyección son el mismo evento. El resumen omite la proyección al usar el snapshot. Días agregados existentes exigen elección explícita: derivar items o conservar agregado declarado disjunto. Baseline original se retiene y se remapea al restaurar. |
| 11 | Daily Nutrition | Flask/Jinja real: Today, Add Meal, empty/legacy states y resumen diario. Feature flag controla nuevos builders/alimentos; readonly y recuperación confirmada de backups preservan datos existentes. No se precargan fixtures productivas. |
| 12 | Food Search / Detail | Búsqueda local, fuentes activas y FoodProduct privados owner-only. Estado/preparación e identidad explícitos, detalle de porciones y provenance. Calificados trace/límite tienen explicación; no se convierten en cero. |
| 13 | Builder / Review | Preview calculado en servidor, edición de cantidades invalida aceptación del ingrediente, pendientes visibles y confirmación explícita de identidad/cantidad. Token enlaza owner, draft, revisión y SHA; CSRF, transacción e idempotencia por evento. |
| 14 | Micronutrients | Tarjetas de subtotal/estado, masa y cobertura con explicación: disponibilidad de datos, no cumplimiento de referencia ni garantía de completitud. Sin barras de déficit ni referencias clínicas nuevas. |
| 15 | Dashboard / Coach / Operator | Tendencias, dashboard completo, Coach y herramienta nutricional de lectura incluyen calidad/subtotales/cobertura. Coach distingue consumo parcial de ausencia de registro con la señal insuficiente existente; no se cambian umbrales. Los parciales quedan fuera de comparaciones; balance diario tampoco calcula déficit con energía parcial. Umbrales y provider/modelo/timeouts intactos. Operator `nutrition.food.create` conserva el servicio oficial existente. |
| 16 | Android | Endpoints, revisión, idempotencia, sync y valores legacy se conservan. DTO con ignoreUnknownKeys admite metadata opcional. Proyecciones canónicas no se pueden editar/duplicar/borrar vía formato antiguo: 409 explícito protege el snapshot. Sin rediseño nativo ni prueba en dispositivo físico en esta entrega. |
| 17 | Export / restore | [Contrato 2.0](../schemas/nutrition_intelligence_2.schema.json), sección opcional del export de cuenta y ZIP oficial: foods/templates/logs/autoridades completos, cálculo validado, remapeo owner-only e historial conflictivo no sobrescrito. Round-trip, reimportación idempotente y ZIP backup/restore pasan. Formatos legacy incompletos se rechazan o anuncian pérdida explícita; portable_package v1 requiere export de cuenta/backup para datos 2.0. |
| 18 | Seguridad | Dos usuarios en pruebas; filtros del owner efectivo para todos los recursos privados; catálogo compartido readonly. Referencias FoodProduct en import diario ahora se validan owner-only en lote. No se guardan payloads personales en logs; QA usa TEMP y datos ficticios. Sin .env, datos persistentes, secretos o archivos personales añadidos. |
| 19 | Performance | SQLite local sintética: 40 alimentos, búsqueda mediana 0.721 ms; 10,000, mediana 3.203 ms. Hasta tres consultas contando carga inicial del owner. Builder de 40 ingredientes: tres consultas, 6.238 / 4.263 ms. Staging del subset oficial de 37: 136.452 ms. Inserción bulk de índice sintético 10k: 88.145 ms; no equivale a staging completo de nutrientes. [Mediciones](../design/nutrition-intelligence-2/production-qa/performance.json). Sin benchmark NAS/MariaDB. |
| 20 | MariaDB / full suite | Focal previo: 169 passed, 4 skips. Focal de cierre: **37 passed** (snapshots y boundary de migración). Full suite final tras la corrección del downgrade MariaDB: **1,217 passed, 34 skipped, 1 warning esperado de ZIP duplicado, 281.62 s**. Se repitió por ese cambio de código productivo, conforme al gate solicitado. MariaDB 11.4 **PASS** en el schema aislado autorizado. [Migración/concurrencia](../design/nutrition-intelligence-2/production-qa/mariadb-results.json) y [persistencia/compatibilidad](../design/nutrition-intelligence-2/production-qa/mariadb-persistence-results.json): READ COMMITTED y REPEATABLE READ, lectura previa al lock, mismo evento/diferentes eventos, revisiones de draft/template, rollback transaccional, ownership, snapshots, micros parciales, unknown/cero/calificados, repeat, Android/Operator, account restore y ZIP. |
| 21 | Mobile / desktop | QA central: 108 combinaciones, anchos 360/390/430/768/1024/1366 y dark/light. Extensión a balance/Today legacy en 390/1366: ocho combinaciones adicionales, **116 en total**, 12 checks funcionales, cero errores de consola y cero solicitudes externas. Teclado Tab/Enter, focus, controles 16 px, targets 44 px y ausencia de overflow. Sin gate zoom 200%. |
| 22 | Capturas QA | [Galería Flask/Jinja](../design/nutrition-intelligence-2/production-qa/gallery.html), separada del prototipo estático. Sólo datos ficticios con banner visible. **48 capturas de página completa y dos viewport**: Today/Add/Search/Detail/Review/Review ready/Micros/Saved/My Food/legacy/balance/Today legacy, mobile390/desktop1366 dark/light. |
| 23 | Commit / Git | Entrega autorizada en `feature/nutrition-intelligence-2`, commit `feat: add nutrition intelligence and reusable meals`. Base de diseño: `31c80154eaaa673bb12c5f2e594a715747d3c82b`. El SHA de entrega, push y estado limpio se verifican tras crear el commit y se reportan en el cierre; este documento forma parte del propio commit. |
| 24 | Bloqueadores / límites | Permisos resueltos mediante administración de la instancia QA local existente: schema nuevo vacío `nutrition_intelligence_qa_20261009`, usuario `progression_qa`, sólo SELECT/INSERT/UPDATE/DELETE/CREATE/ALTER/DROP/INDEX/REFERENCES sobre el nombre exacto escapado. Sin privilegios globales añadidos, sin nuevo contenedor/stack/puerto/worktree. No se consultó ni modificó la BD principal ni el dataset QA anterior. Credencial administrativa configurada usada internamente, sin mostrarla ni leer .env. Sin hardware Android, lector de pantalla o zoom 200%; no son gates exigidos de esta entrega. |
| 25 | Listo para PR | **Sí**: gates funcionales, migración, persistencia, concurrencia, UI y full suite final aprobados. Feature flag conserva default false. Sin merge, despliegue, activación productiva ni NAS. |

## Operación administrativa y recuperación

Administración mediante Flask CLI con acceso al proceso local, nunca desde búsqueda cotidiana:

```powershell
python -m flask --app app:create_app nutrition-catalog sync snapshot-revisado.json --dry-run
python -m flask --app app:create_app nutrition-catalog sync snapshot-revisado.json
python -m flask --app app:create_app nutrition-catalog status
python -m flask --app app:create_app nutrition-catalog activate usda_sr_legacy 2018-04-mx37 --base-revision 1
python -m flask --app app:create_app nutrition-catalog rollback usda_sr_legacy --base-revision 2
```

Son instrucciones de operación posterior; **no se ejecutaron contra producción**. `sync` valida y stagea un archivo local acotado (50 MB / 100k foods máximo); activar cambia el puntero atómicamente con revisión optimista. Una revisión con SHA diferente no puede reemplazar otra ya publicada. Rollback de catálogo conserva revisiones e historia. El rollback de funcionalidad es `NUTRITION_INTELLIGENCE_ENABLED=false`; **no ejecutar downgrade con consumos nuevos**, porque eliminaría sus tablas.

El export completo conserva el contrato externo de cuenta 1.0 y añade una sección interna 2.0 explícita. Se mantienen límites existentes: 10 MiB por archivo de restore y 1,000 registros por sección; el presupuesto de nodos 2.0 es separado y acotado a 500,000, sin relajar los 50,000 nodos legacy, profundidad ni tamaños de strings/arrays. Archivos que exceden presupuesto se rechazan enteros; nunca se truncan ni se inventan campos. Las referencias y revisiones históricas están en el snapshot; la importación no depende de que un catálogo siga activo.

## Verificación reproducible

```powershell
# Desde backend: fixtures ficticias, SQLite efímera
..\.venv\Scripts\python.exe -m pytest -q tests/test_nutrition_intelligence.py tests/test_nutrition_migration.py
..\.venv\Scripts\python.exe -m pytest -q
# Desde raíz, schema QA autorizado vacío: una sola vez para migración y carreras
.\.venv\Scripts\python.exe scripts/nutrition/mariadb_qa.py
# Sobre ese mismo schema: checks sintéticos repetibles, sin reset/downgrade
.\.venv\Scripts\python.exe scripts/nutrition/mariadb_persistence_qa.py
# QA visual local, sin BD real (otra terminal)
.\.venv\Scripts\python.exe scripts/nutrition/qa_app.py
node scripts/nutrition/ui_qa.cjs
.\.venv\Scripts\python.exe scripts/nutrition/performance_qa.py
```

Playwright usa Edge y debe estar disponible en NODE_PATH. La galería y results.json registran los checks visuales. No son resultados Android nativo, lector de pantalla ni hardware físico.

`compileall`, `git diff --check` y verificación de enlaces locales pasan. El status/stat/name-only se revisan antes de stage/commit; no se añaden datos reales ni secretos. `docker compose --env-file <archivo temporal con valores ficticios> config --quiet` pasa sin leer .env ni arrancar contenedores. Metadata `db check` pasa sobre SQLite efímera creada y estampada al head; eso **no prueba la cadena histórica completa**. La cadena SQLite preexistente falla en DDL de FK de migraciones antiguas; el nuevo boundary se prueba aparte. La cadena completa, tipos, índices y locks ya están verificados en MariaDB QA; SQLite no sustituye esa evidencia.

Texto/foto están explícitamente no disponibles: no se suben imágenes, no se analizan con proveedores y no se registra una comida sintética como si fuera detección real.

## Cierre MariaDB QA — 2026-10-09

La instancia existente `ht-progression-qa-20261004`, MariaDB 11.4 en loopback 33381, se reutilizó sin operaciones de lifecycle. Se comprobó el usuario efectivo y la ausencia del schema; se creó únicamente el namespace QA solicitado y se concedieron nueve privilegios de schema. El runner verifica `SELECT DATABASE()` antes de DDL o fixtures; las rutas de archivos de backup/restore están en TEMP. Un flag true se usa exclusivamente en las aplicaciones QA; el default productivo sigue false.

La primera ejecución detectó un campo obligatorio ausente en el seed QA (`users.public_id`), corregido en el runner. El downgrade nuevo detectó después que MariaDB no permite quitar un índice usado por su FK antes de borrar la tabla. La migración ahora elimina directamente las tablas en orden de dependencias; DROP TABLE elimina sus índices. El DDL de MariaDB no es transaccional: se verificó la interrupción, se completó sólo el borrado de cuatro tablas nuevas vacías del schema recién creado y se estampó el baseline tras comprobar columnas legacy y el registro sintético conservado. El ciclo completo posterior pasa. Esto no autoriza ni recomienda downgrade con MealLog consumidos; para rollback funcional posterior usar el flag desactivado.

La concurrencia inicia sesiones independientes con una lectura consistente previa al owner lock: el reenvío simultáneo crea un único evento/proyección; consumos distintos acumulan el total vigente en ambos niveles de aislamiento; revisiones antiguas reciben 409. El rollback del caller deja intacto el conteo de consumos. Los checks adicionales vuelven a leer después de commit, edición y restore, y confirman que food/template edits no alteran los snapshots previos y que repeat crea identidad/evento nuevos con revisión explícita.

El catálogo público acotado de 37 alimentos también se stageó y activó **sólo en QA**, con revisión `2018-04-mx37` y SHA canónico `b1b96afe3d58c12c438532d538383a1f4ace4ec6947378ad78f4762bdbf87bd9`. Metadata e índices siguen coincidiendo después de los consumos, restore y un upgrade repetido al mismo head `20261009_0044`. No se ejecuta downgrade después de esos consumos.
