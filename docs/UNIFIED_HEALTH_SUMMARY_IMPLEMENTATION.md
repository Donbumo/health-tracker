# Resumen de salud unificado — implementación y revisión

25-10-2026. Rama `codex/unified-health-summary`, base `38c6085565f49f560c9c4a1fefc18356bd1e3000`. Implementación para PR independiente contra master; **sin merge, despliegue, NAS ni acceso a datos personales**. El cierre operativo D adjunto corresponde al trabajo anterior del 24-10, no a operaciones repetidas durante esta implementación.

## Integración

`/dashboard` conserva autenticación, navegación compartida, respuesta `private, no-store`, peso, composición, actividad, entrenamiento, objetivos, insights y Coach. `/today` conserva su función diaria y `dashboard?date=...` sigue redirigiendo allí.

El día principal es el final del rango global. `as_of` permite consultar otra fecha civil con los presets existentes, en timezone de la cuenta. 7/30/90 mantienen esa fecha al cambiar de periodo; los rangos personalizados y comparación anterior permanecen disponibles. El servidor rechaza fechas fuera de 1900–9998; al inicio de 1900 acota el rango visible, sin fabricar días. Los seis días previos afectan sólo a las medias.

Se extrae **el bucle existente** de `nutrition_history` a `nutrition_series.build_points`, junto con `mean` y la selección canónica de gasto. Nutrition y Energy siguen usando ese mismo resultado; el dashboard retira su media energética anterior y adapta ahora los puntos compartidos. Las lecturas se hacen con owner efectivo y rangos acotados, sin consultas por día. Comparaciones, insights y snapshot de Coach reciben el mismo bloque del dashboard.

La ingesta visible puede ser subtotal parcial; `consumed` sigue siendo exclusivamente comparable. Gasto procede de `energy_days.views`; no se suman evidencias. Balance y media de balance usan parejas válidas, incluyendo cero. Las medias conservan precisión Decimal; el redondeo final es de presentación. Las medias agregadas tradicionales del periodo mantienen su formato de dos decimales.

No cambian modelos, migraciones, JSON 1.0/1.1, Android/iOS, Mobile Sync, importadores, escritores, export/restore, snapshots ni dependencias. Los flags conservan sus valores; la consulta tampoco habilita Nutrition Intelligence cuando está desactivado.

## Comparación con el prototipo aprobado

| Referencia | Flask real |
| --- | --- |
| Tres tarjetas y medias visibles | Valores del día y tres medias con denominadores propios; móvil usa dos tarjetas y balance a ancho completo. |
| Fecha fija QA | Selector GET real, timezone y validación servidor; mismo rango para los demás indicadores. |
| Navegación simulada | Layout Jinja y menú existente; enlaces oficiales a Hoy, Nutrición, Energía y fuentes/decisiones. |
| Barras y medias precalculadas ficticias | Backend canónico; JavaScript sólo formato y geometría. Barras parciales con contorno discontinuo y texto explícito. |
| Balance con signo | Gráfica independiente, eje cero y media de parejas comparables. |
| Tabla | HTML equivalente con valores, estados, tres medias, denominadores y fuentes; scroll interno con teclado. |
| Temas y disposición | Variables del tema existente, gráficas apiladas en pantallas estrechas. Encabezado móvil compactado tras revisar capturas. |

El prototipo permanece como referencia ficticia independiente. Ningún archivo de fixtures de diseño se importa desde la aplicación. Un día vacío conserva su fecha y ausencia; los enlaces a los dominios permiten consultar su historial, sin sustituirlo automáticamente por un día anterior.

## Evidencia focal

Datos exclusivamente sintéticos, SQLite y storage temporales fuera del repositorio; servidor Flask real en loopback. No se utilizó MariaDB principal, NAS, cuentas reales, tokens productivos ni originales personales.

| Comprobación | Resultado |
| --- | --- |
| Área afectada: dashboard, Nutrition 2.1, daily dashboard, Coach y consulta Energy | **124 PASS**, 1 prueba MariaDB excluida explícitamente; 34,17 s. |
| Archivo nuevo, incluyendo dos casos adicionales posteriores | **14 PASS**, 5,14 s; 12 ya incluidos arriba, **126 casos backend únicos** en total. |
| Revalidación final de dashboard + archivo nuevo tras compactar la plantilla | **49 PASS**, 1 prueba MariaDB excluida; 8,79 s. |
| Geometría y helpers de gráficas JS | **6 PASS**. |
| Flask real, 360/390/430/768/1024/1366, dark/light | **12 layouts PASS**, cero overflow de página. |
| Escenarios móvil: parcial, conflicto, vacío, cero | **4 PASS**, capturas reales. |
| Periodos 7/30/90 y tabla equivalente | **3 PASS**, longitud exacta y scroll interno. |
| Fecha, enlaces oficiales y teclado del formulario | PASS; tres rutas de detalle responden 200. |
| Errores JavaScript / POST de dominio en QA visual | **0 / 0**; sólo POST de login ficticio. |
| Consulta dashboard observada con listener SQL | Cero INSERT/UPDATE/DELETE/REPLACE; `user_id` cliente ignorado. |
| Consultas por rango | Prueba existente PASS: mismo número para 7 y 365 días, máximo 10. |
| Compilación / diff whitespace | PASS. |

Los nuevos casos contrastan cada punto y sus tres medias/denominadores con Nutrition, Energy y `daily_balance`, incluyendo calentamiento, tombstone, resolución y fuentes múltiples. Cubren ingesta parcial, gasto conflictivo, huecos, cero conocido, propietarios distintos, fechas límite, timezone, rango personalizado y comparación anterior. El caso MealLog verifica proyección una sola vez, snapshot intacto y flag desactivado conservado. Una cobertura disjunta demuestra que la media de balance difiere de la resta de las otras dos medias.

Ejecuciones reproducibles desde la raíz:

```powershell
.venv/Scripts/python.exe -m pytest -q backend/tests/test_unified_health_summary.py backend/tests/test_dashboard_trends.py backend/tests/test_nutrition_experience_21.py backend/tests/test_daily_dashboard.py backend/tests/test_coach.py backend/tests/test_energy_experience.py -k 'not mariadb'
.venv/Scripts/python.exe -m pytest -q backend/tests/test_unified_health_summary.py
.venv/Scripts/python.exe -m compileall -q backend/app backend/tests
node --test backend/tests/js/dashboard_charts.test.cjs
.venv/Scripts/python.exe scripts/dashboard/unified_health_qa.py
# En otra consola, con Playwright disponible en NODE_PATH:
node scripts/dashboard/unified_health_visual.cjs http://127.0.0.1:PUERTO_IMPRESO
git diff --check
```

[Resultados del navegador](../design/unified-health-summary/flask-qa/checks.json). Capturas Flask:

- [Escritorio dark](../design/unified-health-summary/flask-qa/1366-dark.png) y [light](../design/unified-health-summary/flask-qa/1366-light.png).
- [Móvil dark](../design/unified-health-summary/flask-qa/390-dark.png) y [light](../design/unified-health-summary/flask-qa/390-light.png).
- Primer viewport móvil [dark](../design/unified-health-summary/flask-qa/390-dark-viewport.png) / [light](../design/unified-health-summary/flask-qa/390-light-viewport.png).
- [Parcial](../design/unified-health-summary/flask-qa/390-light-partial.png), [conflicto](../design/unified-health-summary/flask-qa/390-light-conflict.png), [vacío](../design/unified-health-summary/flask-qa/390-light-empty.png) y [cero](../design/unified-health-summary/flask-qa/390-light-zero.png).

## Límites y revisión pendiente

No se repitieron suite general, campañas Energy, Narrador, axe ni zoom nativo. Las capturas no certifican WCAG. Smoke físico Android/iOS y Open Food Facts externo permanecen separados.

No hay migración nueva: `flask db heads` confirma un único head `20261018_0046`. Se intentó además arrancar una DB SQLite temporal con `flask db upgrade` desde cero para efectuar `db check`; se detuvo en la migración histórica **0015**, cuyo `create_foreign_key` usa ALTER no soportado por SQLite. **Ese intento no llegó a 0046 ni permite declarar `db check` PASS para este PR.** No se usaron stamp, cambios de migración ni DB productiva como sustitutos. Los tests y Flask QA usan el esquema ORM temporal de pruebas, como la suite vigente. No se repitió MariaDB/DDL porque esta entrega modifica únicamente consultas y presentación; la evidencia anterior de 0046 se conserva como antecedente, sin atribuirla a esta rama.

Las mediciones son funcionales/locales; no son un benchmark productivo de carga. Revisar el PR y sus capturas antes de autorizar integración; producción permanece en el master previamente desplegado.
