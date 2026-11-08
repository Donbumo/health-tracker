# Health Tracker AI: balance energético por fechas

## Auditoría y causa raíz

Auditoría realizada sobre `origin/master` `bb7f535`, siguiendo `AGENTS.md`,
`backend/AGENTS.md`, `schemas/AGENTS.md`, `PROJECT_CONTEXT.md`, `AI_FOUNDATION.md`
y `HOW_TO_ADD_AI_SUPPORT_FOR_A_NEW_DOMAIN.md`. No se consultaron datos personales,
archivos de entorno ni almacenamiento persistente.

| Superficie | Servicios y modelos existentes |
| --- | --- |
| `/daily-balance` | `daily_balance.daily_balance`, `nutrition_intelligence.comparison_value`, `energy_days.view`; `DailyNutrition`, `DailyEnergy`, `EnergyDay` |
| `/energy` | `energy_history.consultation`, `nutrition_history.history`, `energy_days.views` y `nutrition_series.build_points` |
| `/nutrition/` | `nutrition_history.history`, serie canónica y snapshots nutricionales; no recalcula consumos históricos |
| Tools AI | `AIToolRegistry`, schemas con `additionalProperties: false`, validación `Draft202012Validator`, handlers ligados al `User` autenticado |
| Autorización AI | Manifests de dominio → `AICapabilityRegistry.resolve/definitions_for` → plan y allowlist por turno → `AIConversationService._execute_tool` |
| Provider | `FakeAIProvider` para QA sin red; adaptador Responses existente con consentimiento remoto, schema y evidencia |

El gasto **ya estaba disponible** en `NutritionTrendService`: incluso
`get_nutrition_summary` devuelve `metrics.energy.expended_total`. Por tanto,
atribuir el problema a registros inexistentes sería incorrecto. Se identificaron
estas limitaciones reproducibles:

1. Las lecturas agregadas AI aceptaban presets, sin contrato para una fecha
   arbitraria como el 26 de octubre. El manifest de Energía remitía al resumen
   general; no había una tool específica con detalle diario y exclusiones.
2. La respuesta del provider fake para nutrición presentaba proteína e ingesta,
   omitiendo el gasto que el read model sí suministraba. Su respuesta general
   tampoco presentaba el balance. Esto explica la omisión reproducible en QA;
   no demuestra por sí solo una causa idéntica en todos los modelos remotos.
3. `DashboardDateRange.as_dict()` devuelve `previous_from/to=null` cuando no se
   solicitó comparación. Es un indicador de configuración, no una consulta al
   historial. Además, el router libre fake de nutrición/peso omitía propagar el
   booleano de comparación. Ahora lo propaga; el contexto del plan también
   transmite periodo y comparación como defaults al provider.
4. El sanitizador general limita listas a 100 elementos. La tool nueva conserva
   sus hasta 366 puntos tanto al producir el resultado como al entregarlo al
   provider. Se mantiene el límite original para las demás herramientas.

## Reutilización y alcance

`EnergyBalanceService` carga filas owner-only mediante
`NutritionTrendService.load` y utiliza `nutrition_series.build_points`.
Este último aplica `comparison_value` a ingesta y la proyección de `energy_days`
a gasto total: preserva conflictos, resoluciones confirmadas, tombstones y fuentes
solapadas. No se introduce otro motor nutricional ni se suman calorías activas al
total. La fachada nueva agrega cobertura, promedios exactos y comparación.

`daily_balance` conserva su contrato y utiliza las mismas autoridades de dominio.
Las pruebas contrastan su resultado con la herramienta y ejercitan el GET web.
No cambian tablas, schemas de import/export, migraciones, dependencias ni contratos
móviles. El head sigue siendo `20261018_0046`.

## Contrato de la herramienta

Nombre: `get_energy_balance`. Lectura de dominio sin escrituras; la auditoría de
la conversación sigue usando el mecanismo AI existente.

| Entrada | Regla |
| --- | --- |
| `date_from` | Obligatoria, fecha ISO `YYYY-MM-DD`, inclusiva |
| `date_to` | Obligatoria, fecha ISO inclusiva, igual o posterior a la inicial |
| `compare_previous` | Booleano opcional, default `false` |
| `include_daily` | Booleano opcional, default `false` |
| `comparison_mode` | Enum opcional `auto` (default), `equal_days` o `calendar_month` |

No admite otras propiedades ni `user_id`. Fechas entre 1900 y 9998, máximo 366
días por periodo. Una comparación cuyo periodo anterior salga de los límites se
rechaza. La zona se obtiene del usuario autenticado, o de `APP_TIMEZONE` si no
configuró una; `America/Mexico_City` se conserva cuando está configurada.
Las fechas diarias ya guardadas no se reinterpretan como timestamps UTC.

Salida JSON segura, con Decimal serializado como string sin redondeo:

| Campo | Semántica |
| --- | --- |
| `period` | Desde/hasta, días inclusivos, zona, etiqueta y límites anteriores cuando se compara |
| `metrics.consumed_kcal` | Suma de ingesta registrada disponible, incluidos subtotales parciales identificados |
| `metrics.expended_kcal` | Suma de gasto total canónico conocido, sin sumar fuentes ni gasto activo |
| `metrics.comparable_consumed_kcal/expended_kcal` | Totales restringidos al mismo conjunto de días con ambas métricas comparables |
| `metrics.balance_kcal` | Suma de balances sólo de esos días comparables; `null` si no hay ninguno |
| `metrics.complete_balance_kcal` | Balance completo registrado únicamente si todos los días tienen ambas métricas comparables; en otro caso `null` |
| `averages` | `value` y denominador `days` por ingesta comparable, gasto conocido y balance pareado; sin cuantización |
| `coverage` | Días solicitados, ingesta registrada/conocida, gasto conocido, ambas conocidas y cobertura completa/parcial/desconocida |
| `excluded_days` | Todos los días excluidos del balance y motivos: ingesta parcial/desconocida, gasto desconocido/en conflicto |
| `daily` | Lista completa si se solicita; fechas, valores, estados, cobertura y fuentes; en otro caso `null` |
| `extremes` | Días con menor y mayor balance conocido, incluso sin pedir toda la lista diaria |
| `sources` y evidencia AI | Metadata segura agrupada, periodo propio, fuentes de los valores seleccionados y cálculo de Health Tracker; resoluciones explícitas como `user_override` |
| `comparison` | Periodo anterior con la misma estructura, modo, deltas de promedios/denominadores y deltas completos cuando proceden |
| `warnings/limitations/calculation` | Alcance parcial, límites de registro e identificación del cálculo propio |

Cero real se conserva como cero. Ausencia es `null`. Un subtotal nutricional
parcial puede contribuir a la ingesta registrada, pero nunca implica déficit ni
entra en su promedio comparable. Un conflicto de gasto no se resuelve eligiendo
una fuente por nombre. El balance no resta totales de coberturas distintas.

## Comparaciones

Por defecto, el periodo anterior es contiguo y tiene igual cantidad de días.
La excepción explícita es **un único mes calendario completo**, que compara con
el mes calendario completo inmediatamente anterior, aunque tenga distinta duración.
Un rango de varios meses mantiene la semántica de ventana de igual longitud.
`equal_days` fuerza una ventana de igual duración, aunque coincida con un mes
completo. `calendar_month` exige un único mes completo. Esta opción adicional
desambigua intenciones que las cuatro entradas propuestas no podían distinguir:
por ejemplo, del 1 al 30 de noviembre como mes calendario o como últimos 30 días.
El provider recibe esa instrucción y la regresión de chat conserva la ventana
móvil con `equal_days`.

| Periodo actual | Periodo anterior | Modo |
| --- | --- | --- |
| 2026-10-26 | 2026-10-25 | `equal_days` |
| 2026-11-01 a 2026-11-07 | 2026-10-25 a 2026-10-31 | `equal_days` |
| 2026-10-01 a 2026-10-31 | 2026-09-01 a 2026-09-30 | `calendar_month` |
| 2026-11-01 a 2026-12-31 | 2026-09-01 a 2026-10-31 | `equal_days` |

Cada delta identifica denominadores y estado `complete`, `partial_sample` o
`unavailable`. Puede existir comparación completa de ingesta y sólo comparación
parcial de gasto/balance. Los promedios de muestras parciales son descriptivos;
no equivalen a comparar el balance completo de ambos periodos. Los deltas de
totales completos se omiten cuando falta cobertura de la métrica correspondiente.

La semántica de `DashboardDateRange.previous_period()` para consumidores antiguos
se conserva; la excepción de calendario pertenece a esta herramienta.

## Descubrimiento, autorización e invocación

El manifest de Energía resuelve resumen, tendencia, comparación y cobertura a
`get_energy_balance`. Los planes correspondientes de Nutrición y Resumen la
incluyen entre sus lecturas autorizadas. El provider decide la lectura pertinente
dentro del plan; no se amplía una allowlist por una llamada inventada.
Las instrucciones comunes explican cuándo utilizarla, el significado de los
balances parciales y por qué `previous_from/to=null` no demuestra falta de datos.

La matriz de integración ejecuta las cinco preguntas de la solicitud desde chat
libre y desde planes de Energía, Nutrición y Resumen: veinte recorridos reales de
`AIConversationService` con provider fake, llamada auditada `completed`, fechas,
zona y resultado comprobados. El caso ficticio del 2026-10-26 recupera gasto
2450.01 del dominio de energía e ingesta 2100.123: balance exacto -349.887.

Otra prueba usa el adaptador Responses con transporte HTTP simulado: schema
autorizado, `tool_choice=required`, `store=false`, llamada entrante, ejecución,
`function_call_output` con el resultado y respuesta final. No hay llamadas a una
nube real ni se afirma aceptación por un modelo remoto concreto.

## Verificación

Pruebas en `backend/tests/test_ai_energy_balance.py`:

- Día completo, cada lado ausente, ambos ausentes y cero real.
- Semana completa/parcial, subtotales nutricionales, gasto activo sin total,
  conflictos, eliminados, fuentes duplicadas y resolución confirmada.
- Meses de distinta duración, año nuevo, febrero bisiesto, rangos multimes,
  fechas inclusivas y 366 puntos sin truncar en el provider.
- Zona individual México/Tokio, aislamiento de dos usuarios, rechazo de
  `user_id`, rangos inválidos y consultas de dominio sólo `SELECT`.
- Decimal en totales y promedios con más precisión que la escala de los días.
- Matriz de enrutamiento, schema Responses, rechazo de tool fuera del plan,
  obligatoriedad de lectura, contexto de comparación y coherencia web diaria.

La prueba local admite un puerto de la instancia MariaDB QA descartable mediante
`AI_ENERGY_QA_DB_PORT`; no acepta URI arbitraria, exige base `energy_balance_qa`,
usuario `qa` y verifica el nivel de aislamiento antes de crear/eliminar sus
tablas sintéticas. No se debe configurar esa opción para una base persistente.
`scripts/ai/energy_balance_mariadb_check.py --port <puerto-QA>` aplica las
migraciones existentes y ejecuta `flask_migrate.check` sobre una instancia nueva
con el mismo alcance verificado y almacenamiento de archivos temporal.

Resultados de QA, 2026-11-07:

| Comprobación | Resultado |
| --- | --- |
| Suite focal final: todas las pruebas AI + balance diario + energía diaria/canónica | **334 passed, 5 skipped**, 83.44 s |
| Nuevas regresiones en MariaDB, READ COMMITTED | **59 passed**, 47.45 s |
| Nuevas regresiones en MariaDB, REPEATABLE READ | **59 passed**, 49.12 s |
| MariaDB descartable, migraciones existentes y `flask_migrate.check` | **PASS**, MariaDB 11.4.12, head `20261018_0046`, cero operaciones nuevas |
| Compilación Python de app/tests y script QA | **PASS** |
| Docker Compose config y `git diff --check` | **PASS** |
| Suite completa ejecutada durante la revisión | **1779 passed, 35 skipped, 1 failed**, 591.76 s |

El único fallo de la suite completa es
`test_context_router_and_active_handoff_are_compact_and_separated`: el handoff
local, modificado antes de esta tarea, tiene 160 líneas frente al máximo de 80.
Se verificó la misma comprobación con el contenido versionado de `origin/master`
en memoria y pasa, sin reemplazar el archivo local. Ese handoff y los demás
cambios ajenos no forman parte del commit. Tras los últimos ajustes se repitió
la suite focal completa y las 59 pruebas nuevas en ambos niveles de aislamiento;
los resultados finales son los de las primeras filas.

MariaDB se ejecutó en un contenedor QA temporal con `/var/lib/mysql` en tmpfs,
sin volúmenes persistentes ni acceso al stack local en uso. La instancia se
eliminó al terminar. Todas las entradas de dominio usadas son ficticias y están
identificadas como tales. No se hizo merge ni despliegue.

## Compatibilidad y límites

La herramienta es aditiva y las herramientas anteriores siguen registradas.
El preset legacy `energy-balance` mantiene su ID y ahora invoca la nueva lectura.
Los catálogos visuales conservan sus presets existentes; la tool admite rangos
arbitrarios por fechas sin añadir un contrato nuevo de deep links.

Cobertura completa significa que las dos métricas son comparables según los
contratos vigentes para todos los días solicitados. No certifica que se hayan
registrado todas las comidas o todo el gasto real. La precisión respeta las
escalas persistidas existentes y Decimal; no recupera precisión que el registro
original no tenía. El máximo de 366 días por periodo limita coste y contexto,
pero pedir detalle diario más comparación puede producir una respuesta extensa.
