# Carbohidratos y metas históricas DEMO

## Alcance e integración

Corrección de lectores para todas las cuentas y aprovisionamiento **explícito** de siete metas ficticias exclusivamente para `demo@healthtracker.test`. Rama independiente `codex/demo-carbs-goals`, basada en `master` (`ed900b6`). Sin cambios de modelos ni migración: el head sigue siendo `20261018_0046`.

Se inspeccionó PR [#47](https://github.com/Donbumo/health-tracker/pull/47), abierto, con head `2b7876b49fb63c5591a66b2f22539e2ad7a463ec`. Esta rama no incorpora sus commits ni modifica `demo_seed.py`, `demo_fixtures.py`, el importador de pesajes o los servicios de sesiones. El comando nuevo requiere la cuenta histórica verificable que crea #47; el `seed-demo` antiguo de master no crea esa identidad y no debe usarse para este procedimiento.

La simulación `git merge-tree --write-tree` entre esta implementación y ese head no reportó conflictos; no cambió ramas, índice ni checkout. Es una comprobación de integración, no un merge ni autorización para desplegar.

La aceptación ejecuta cuatro módulos de ese commit **sólo en el proceso QA**, cargados mediante `git show` de rutas fijas. Esto permite comprobar la ampliación corporal pendiente sin mezclar implementaciones en el PR. El ref debe ser código local confiable e inspeccionado; si #47 cambia, repetir esta aceptación con el nuevo commit. Revisar e integrar ambos PR por separado antes del despliegue; no hacer cherry-picks automáticos. No se ejecutó ningún cambio en el NAS.

## Diagnóstico reproducido

El catálogo público USDA aporta `carbohydrate_total` y `fiber`, pero no `net_carbs` explícitos para los 16 alimentos usados por DEMO. Los ingredientes, recetas y 196 snapshots preservan esa ausencia. Los 49 resúmenes diarios contienen totales `complete` y netos `unknown`; la cobertura neta 0/7 es coherente con la evidencia disponible.

Resumen sólo mostraba netos y omitía los totales. Además asociaba `nutrition_carbohydrates` a netos, mientras adherencia leía totales pero recurría a netos cuando faltaban; Mobile Today y Progress también mezclaban ambas identidades mediante fallback. No faltaban carbohidratos totales en MariaDB.

| Etapa | Contrato y resultado de la auditoría |
| --- | --- |
| Catálogo y normalización | `food_catalog.py`, `nutrition_sources.py`: nutrientes separados, base/unidades y fuente por alimento. OFF mantiene carbohidratos ambiguos fuera de totales confirmados. |
| Ingredientes y recetas | `nutrition_math.py`, `nutrition_intelligence.py`: escalado por base declarada, cobertura por nutriente; las ausencias no se convierten en cero. |
| Snapshots y consumo | `MealLog.snapshot_json` y snapshots de recetas conservan valores, fuentes y revisiones. No se recalculan ni se reescriben para mejorar cobertura. |
| Proyección diaria | `DailyNutrition.total_carbs_g` y `net_carbs_g` independientes. `comparison_value()` excluye subtotales parciales. Sin cambios de completitud. |
| Estadísticas y gráficas | `nutrition_series.py` y `nutrition_history.py` ya separaban ambos nutrientes y sus medias móviles. Resumen ahora incluye totales como fila principal y mantiene netos separados. El listado antiguo, las filas de comidas y Balance diario también omitían totales; ahora los exponen con etiquetas y unidades independientes. |
| Metas, Coach y adherencia | `nutrition_carbohydrates` compara exclusivamente totales completos. Coach usa relación descriptiva para nutrición; adherencia mide cobertura y expone la razón registrada aparte. |
| API móvil | `carbohydrate_g` de Today/Progress significa totales, sin fallback; Progress devuelve null si son parciales. Los campos explícitos `total_carbs_g` y `net_carbs_g` siguen separados. Un ítem sólo con netos no se declara completo para los macronutrientes principales. |
| Import/export | Los contratos estándar, bundle 2.x y exportadores diarios conservan los dos campos, sin sustitución ni derivación. Se valida el bundle exportado y las rutas diarias JSON, además de las regresiones existentes de importación/round-trip. |

### Por qué no se calculan netos automáticamente

Compartir gramos y disponer de fibra no establece, por sí solo, la definición química de los carbohidratos ni la compatibilidad de calidad entre datos. El contrato vigente no ofrece una regla autorizada de derivación con procedencia para estos snapshots. `nutrition_math` sólo escala nutrientes declarados; no identifica `totales − fibra` como medición de la fuente. No se introduce esa fórmula en un lector ni se añade metadata ficticia. Un neto explícito válido se conserva incluso si difiere de la resta. Una fuente sólo con netos continúa siendo válida para esa serie y desconocida para totales. Fuentes/bases incompatibles y estados parciales siguen sin generar netos.

## Lectura de metas y cobertura

Resumen muestra calorías, proteína, carbohidratos totales, grasa, fibra y netos, con unidades y días disponibles. Los porcentajes de nutrición y pasos sólo aparecen cuando **todos** los días con meta aplicable tienen datos completos. Los días sin meta no entran en el numerador de la comparación. El promedio informativo del periodo conserva todos sus días completos; cuando difiere la población, se muestra también el promedio de los días con objetivo.

Las razones nutricionales pueden superar 100%; no significan un beneficio, mínimo alcanzado ni límite respetado. Las barras se acotan visualmente a 100, pero la cifra mantiene la razón real. El modelo no tiene dirección mínima/máxima/nominal y este cambio no la inventa. Coach conserva lenguaje neutral tanto por encima como por debajo del target, sin elevar la severidad por esa diferencia.

En adherencia, los campos históricos `completed/expected/percentage/status` describen **cobertura de registro** para nutrición. `details.measurement=recording_coverage` lo identifica y añade promedio, target y `registered_percent_of_target`, neutral y sin límite, null si faltan días completos. Ver [ADHERENCE_METRICS.md](ADHERENCE_METRICS.md) y la descripción de `details` en el schema. No se cambian enums ni campos requeridos. Los otros tipos conservan su contrato; adherencia semanal usa ventanas de siete días redondeadas hacia arriba, mientras Resumen expresa frecuencia semanal proporcional a los días aplicables.

Sesiones y registro de peso en Resumen sólo cuentan fechas con objetivo aplicable. Los pesajes se deduplican por fecha local; varios pesajes de un día no incrementan la frecuencia. Una frecuencia semanal se expresa como `conteo × 7 / días aplicables`, con el target medio correspondiente. Esto evita diluir una meta recién iniciada entre días anteriores sin objetivo.

## Siete metas DEMO

| Tipo real `UserGoal` | Target | Periodo |
| --- | --- | --- |
| `nutrition_calories` | 2350 kcal | diario |
| `nutrition_protein` | 155 g | diario |
| `nutrition_carbohydrates` | 265 g totales | diario |
| `nutrition_fat` | 75 g | diario |
| `daily_steps` | 8000 pasos | diario |
| `training_sessions_per_week` | 3 sesiones | semanal |
| `weight_logging_frequency` | 7 registros de fecha distinta | semanal |

Todas empiezan el **2026-10-01**, con la timezone de la cuenta, independientemente de `created_at`. No hay fecha final automática. No se crea agenda ni meta de entrenamientos planeados. Fibra: **30 g diarios es sólo una referencia ficticia de DEMO**; el modelo no admite un tipo fibra. Su valor se conserva informativo, sin meta persistente ni porcentaje inventado.

`services/demo_goals.py` verifica UUID histórico, username, email, nombre y rol de la cuenta. Crea mediante `engagement.create_goal`, con UUID5 estable `health-tracker/demo-goals/v1/{goal_type}`, `source=demo_goals_v1` y revisión inicial 1. Reutiliza sólo coincidencias exactas; una revisión editada, estado cambiado, colisión o meta manual que se solape produce conflicto conservado. No resucita una meta propia archivada o pausada. No recibe un `user_id` del cliente ni cambia usuarios, contraseñas, pesajes, recetas, consumos o energía.

La creación oficial y el sembrador bloquean la fila del owner para serializar inserciones; el sembrador también bloquea sus metas. La transacción la cierra el CLI. Los conflictos son **por tipo y explícitos**: los tipos sin conflicto pueden crearse; el informe detalla `created/reused/conflicts` y el CLI termina con error si hubo conflictos. Una excepción inesperada revierte todo el lote y no imprime errores SQL ni secretos.

## Validación aislada

La aceptación usa la fuente pública USDA filtrada a los 16 alimentos, y los servicios reales del commit #47 citado. Tanto SQLite como MariaDB 11.4 reproducen:

- 49 días de nutrición y energía; 196 comidas y snapshots; 21 sesiones y 378 series.
- Compatibilidad corporal: 49 pesajes y 21 días de composición.
- Siete metas creadas; segunda ejecución reutiliza las mismas siete.
- Huellas de **todas las tablas excepto `user_goals`** iguales antes/después, incluidos timestamps, snapshots, credenciales y otra cuenta ficticia.
- Octubre: totales **255,64 g**, 31/31 días. Noviembre 1–18: **263,81 g**, 18/18. Noviembre 12–18: **266,05 g**, 7/7; razón frente a 265 g **100,40%**. Septiembre no tiene metas aplicables. Netos desconocidos en los 49 días.
- MariaDB: migraciones desde vacío hasta 0046, `db check` sin diferencias; dos sembradores concurrentes crean siete y reutilizan siete tanto en READ COMMITTED como REPEATABLE READ.
- UI Edge/Playwright: 360, 390, 430, 768, 1024 y 1366 px, claro/oscuro; seis nutrientes, siete metas, barras y ausencias correctas, sin overflow, etiquetas recortadas ni errores JS. Capturas inspeccionadas visualmente.
- En esas mismas 12 combinaciones se comprueban además listado nutricional antiguo, detalle diario y Balance diario, con totales visibles y sin desbordamiento global.

Pruebas específicas: **136 passed, 2 skipped** para carbohidratos/metas DEMO, Coach, dashboard, engagement, API móvil, Nutrition Intelligence y exportaciones. Tras completar las vistas antiguas, **31 passed** para regresiones DEMO, balance, smoke web, exportaciones y empty states. Las dos omisiones específicas son suites MariaDB del entorno Docker; la aceptación MariaDB dedicada sí se ejecutó con la base desechable descrita. `compileall`, `git diff --check` y `docker compose config --quiet` pasan (configuración QA ficticia, sin leer `.env`).

Suite completa: **1874 passed, 35 skipped**, sin fallos. El worktree nuevo no incluía las fixtures históricas ignoradas de importación FIT/GPX/TCX/CSV: se generaron los FIT con `examples/qa/real-file-imports/generate_fit_fixtures.py` y se prepararon únicamente las fixtures ficticias ya identificadas por su README. No se añadieron esos archivos ignorados al PR. La advertencia de ZIP duplicado procede del test que comprueba su rechazo.

Evidencia revisable: [capturas y reportes QA](../design/demo-carbs-goals/README.md). Los cambios funcionales están en los lectores de `dashboard/nutrition.py`, `dashboard/summary.py`, `dashboard/goals.py`, `dashboard/provenance.py`, `daily_balance.py`, `engagement.py`, `coach.py`, `mobile_health.py`, los templates/CSS y sus pruebas. El aprovisionamiento nuevo vive en `services/demo_goals.py` y `demo_goals_cli.py`, registrado en `app/__init__.py`; las descripciones de schemas aclaran la semántica existente sin cambiar su forma.

Las pruebas `backend/tests/test_demo_carbs_goals.py` no dependen de refs externos: usan fixtures ficticias para ambos carbohidratos, sólo totales, sólo netos, bases incompatibles, parcialidad, población comparable, metas diarias/semanales, fechas sin meta, UUID/idempotencia, metas editadas/manuales, aislamiento, rollback y Coach neutral. Las demás suites de nutrición, dashboard, metas, API móvil y exportaciones cubren sus rutas y contratos existentes.

Reproducción en PowerShell desde la raíz, usando un Python con las dependencias del backend:

```powershell
$env:PYTHONPATH = (Resolve-Path backend).Path
python scripts/nutrition/qa_demo_carbs_goals.py --demo-ref 2b7876b49fb63c5591a66b2f22539e2ad7a463ec --output "$env:TEMP\demo-carbs-goals-qa.json"
```

El script usa SQLite RAM y storage temporal por defecto. Para MariaDB, exige una **base vacía y desechable** llamada `demo_carbs_goals_qa` en loopback, suministrada mediante `DEMO_GOALS_QA_DATABASE_URI`. Debe ser una instancia tmpfs propia, sin volúmenes del stack habitual. Se rechaza una base no vacía. Nunca apuntar este script al NAS o a datos existentes: su función es crear fixtures y comprobar concurrencia en QA.

Para navegador, añadir `--serve 5197`; en otra terminal configurar `QA_OUTPUT` a un directorio de artefactos temporales y ejecutar `node scripts/nutrition/ui_qa_demo_carbs_goals.cjs` con Playwright disponible. Usa una contraseña fija **exclusivamente ficticia de QA** y origen loopback; no credenciales productivas.

## Actualización futura de la DEMO del NAS

Procedimiento preparado, **pendiente de autorización explícita y revisión de ambos PR**:

1. Verificar la versión integrada, identidad histórica DEMO y head 0046; hacer el backup consistente por el [runbook vigente](ENERGY_0046_RECOVERY_RUNBOOK.md). Registrar conteos e identidades de sus filas históricas y de las metas existentes con consultas acotadas al owner efectivo. No exportar datos de otras cuentas al informe.
2. Desplegar la imagen revisada con estos lectores y el nuevo comando. Este cambio no requiere migración ni regeneración del historial. Comprobar primero Resumen y nutrición diaria: los totales deben aparecer con datos existentes, aun antes de crear metas.
3. Ejecutar **una sola vez de forma explícita**, desde el proyecto Compose autorizado del NAS:

   ```sh
   docker compose exec -T \
     -e DEMO_GOALS_ENABLED=true \
     -e DEMO_GOALS_ENVIRONMENT=production \
     web flask --app app:create_app seed-demo-goals --confirm --confirm-production
   ```

   No necesita `DEMO_USER_PASSWORD`, no cambia la contraseña y no debe volver a ejecutar `seed-demo`. Los flags habilitan sólo esa invocación; no modificar `.env` ni dejar habilitado un sembrador permanente.
4. Revisar `created/reused/conflicts`. Conservar las metas manuales o editadas e investigar cualquier conflicto; no borrarlas ni forzar reemplazos. Repetir el comando debe informar siete reutilizadas cuando no hubo conflictos.
5. Comparar los conteos/identidades previos: deben permanecer 49/49 días, 196 comidas, 21 sesiones y 378 series. Si la ampliación corporal ya estaba aplicada, conservar también sus 49 pesajes/21 composiciones. Si no estaba aplicada, la meta de peso mostrará la cobertura real disponible, sin crear pesajes.
6. Verificar octubre, noviembre, 7 días y un periodo anterior al 1 de octubre; comprobar otro usuario sin metas DEMO nuevas. Los lectores son generales y pueden corregir sus comparaciones de carbohidratos; sus registros no se reescriben.

Ante un problema, detener el procedimiento y conservar el informe. No hay borrado automático de metas ni restore completo que pueda pisar escrituras nuevas. La corrección de lectores y la escritura explícita de metas son operaciones separadas y revisables.
