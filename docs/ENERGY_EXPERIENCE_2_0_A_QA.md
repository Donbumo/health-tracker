# Energy Experience 2.0 — consulta A y evidencia para revisión

Rama `feature/energy-experience-2-0`, base `9e2f2dc7fea728bfec3c8abf1aed6bc7bb428852` (master vigente verificado). Dirección revisada en [la especificación](ENERGY_EXPERIENCE_2_0.md). Sin merge, despliegue, NAS ni cambios en datos reales.

## Alcance y arquitectura de consulta

- Entrada autenticada `/energy`: resumen con gasto principal, ingesta y balance de contexto; períodos 7/30/90; calendario dinámico; hoy/último; actividad y tendencias independientes.
- `energy_history.consultation` compone `nutrition_history.history` y `energy_days.views/view`. Ingesta, balance, medias y denominadores de Nutrition se reutilizan exactamente, sin reimplementar su política. `mean` compartido calcula las medias de actividad. La geometría de barras no cambia valores.
- Consultas owner-only con rango máximo de 96 días (90 + 6 de calentamiento), mes seleccionado y MAX independiente de última fecha activa; sólo se materializa el último día. Los registros de más de 100 días siguen accesibles por fecha. No se descarga todo el historial nuevo.
- Cero conocido, ausente, conflicto y subtotal parcial se distinguen con texto/símbolos. Subtotales fuera del balance; fuentes nunca sumadas; no se calculan totales desde componentes ni pasos. Medias con n/7 visible incluso en días sin observación, sin interpolar barras.
- Tabla equivalente por gráfica: fecha, valor/unidad, estado, fuente, media y denominador. HTML/Jinja y controles nativos; toda consulta funciona sin JavaScript. CSS acotado a `.ee-page`, usando tokens existentes dark/light.
- `/daily-energy` permanece operativo, con enlaces de ida/regreso. Captura manual, Import Hub, import JSON, detalle, edición, borrado y exportación conservan sus rutas y servicios.

Sin cambios a EnergyDay, DailyEnergy, EnergyEvidenceEvent, migración 0046, schemas públicos, UUID/revisiones móviles, catálogo, snapshots ni export/restore. Sin flags nuevos ni activación de flags existentes.

## Backend y MariaDB

| Gate | Evidencia |
| --- | --- |
| Nuevas pruebas de A | 16 PASS, `backend/tests/test_energy_experience.py` |
| Regresión focal de Energía/Nutrition 2.1/export/restore | 73 PASS |
| Suite backend completa | 1316 PASS, 34 skipped; 320.62 s; una advertencia esperada del fixture ZIP duplicado |
| Compilación Python | `compileall -q app tests` PASS |
| Compose | `docker compose config --quiet` PASS |
| MariaDB QA | READ COMMITTED y REPEATABLE READ PASS; [reporte](../design/energy-experience-2-0/qa-flask/mariadb.json) |
| Alembic | Head `20261018_0046`; `flask_migrate.check` (misma operación que `flask db check`) sin operaciones nuevas, en ambos aislamientos |

Fixtures sintéticas: 125 días, cero conocido, fuente complementaria, contradicción, resolución, fuente retirada, día eliminado, subtotal nutricional parcial y gasto desconocido. La prueba compara **cada observación, media y denominador** contra Nutrition y cada balance contra Daily Balance en 7/30/90. Incluye warm-up, hoy vacío, último fuera del rango, acceso a día antiguo, meses/años y zona horaria (cambia hoy, no las fechas históricas).

En SQLite se instrumentan todas las sentencias SQL durante consultas/GET y se comparan todas las columnas de EnergyDay, DailyEnergy, DailyNutrition y eventos antes/después: cero INSERT/UPDATE/DELETE y estado idéntico. MariaDB repite huella completa del propietario QA, observaciones y HTTP, con cero escrituras de consulta en RC/RR. Otro propietario no ve datos ni última fecha; `user_id` de URL no concede autoridad. GET legacy de listado/import/manual/detalle/editar/eliminar también probado sin escrituras.

MariaDB se validó en la instancia LOCAL existente y schema QA aislado `nutrition_intelligence_qa_20261009`, usuario QA restringido; ningún DDL ni migración ejecutados. Imagen compatible Python 3.12 ya existente, proceso QA efímero sin puertos ni volúmenes persistentes nuevos. Configuración privada de conexión suministrada por archivo externo, sin leerlo ni imprimirlo. Los únicos inserts son fixtures ficticias de cuentas QA nuevas; nunca se utiliza la DB principal.

## Evidencia visual real de Flask

[Reporte HTTP](../design/energy-experience-2-0/qa-flask/report.json): **36/36 PASS**, seis anchos (360/390/430/768/1024/1366) × dos temas × tres períodos. **14 capturas** reales HTTP sobre SQLite temporal con fixtures QA. Cero errores HTTP o JavaScript. Teclado, controles nativos, foco visible, tamaños de input y ausencia de overflow PASS. Contraste de texto ≥4.5:1 y controles/gráficas/foco ≥3:1 en los pares de tokens medidos; no es auditoría WCAG completa.

El QA detectó el foco claro heredado por debajo de 3:1. Se corrigió sólo dentro de la nueva pantalla y se repitió la matriz final. Revisión visual manual realizada en resumen móvil dark y escritorio light, calendario mobile dark, conflicto/parcial mobile light y tendencias desktop dark. Todas las capturas corresponden al código final de la plantilla.

| Vista Flask | Dark | Light |
| --- | --- | --- |
| Resumen móvil 390 | [PNG](../design/energy-experience-2-0/qa-flask/overview-dark-390.png) | [PNG](../design/energy-experience-2-0/qa-flask/overview-light-390.png) |
| Resumen escritorio 1366 | [PNG](../design/energy-experience-2-0/qa-flask/overview-dark-1366.png) | [PNG](../design/energy-experience-2-0/qa-flask/overview-light-1366.png) |
| Calendario móvil 390 | [PNG](../design/energy-experience-2-0/qa-flask/calendar-dark-390.png) | [PNG](../design/energy-experience-2-0/qa-flask/calendar-light-390.png) |
| Calendario escritorio 1366 | [PNG](../design/energy-experience-2-0/qa-flask/calendar-dark-1366.png) | [PNG](../design/energy-experience-2-0/qa-flask/calendar-light-1366.png) |
| Hoy vacío móvil 390 | [PNG](../design/energy-experience-2-0/qa-flask/empty-today-dark-390.png) | [PNG](../design/energy-experience-2-0/qa-flask/empty-today-light-390.png) |
| Conflicto/parcial móvil 390 | [PNG](../design/energy-experience-2-0/qa-flask/partial-conflict-dark-390.png) | [PNG](../design/energy-experience-2-0/qa-flask/partial-conflict-light-390.png) |
| Tendencias escritorio 1366 | [PNG](../design/energy-experience-2-0/qa-flask/activity-trends-dark-1366.png) | [PNG](../design/energy-experience-2-0/qa-flask/activity-trends-light-1366.png) |

Resumen captura primer viewport. Calendario/tendencias conservan el desplazamiento hasta la sección. Los fixtures Flask son distintos de los del prototipo: no se espera igualdad de sus cifras de demostración.

## Comparación con el prototipo y pendientes

El [prototipo revisado](../design/energy-experience-2-0/index.html) demuestra gasto protagonista, barras/medias con denominador, cinco tendencias, calendario dinámico y filtros/páginas ficticios de historial. Su [QA separado](../design/energy-experience-2-0/qa/report.json) conserva 60 combinaciones PASS y diez capturas actualizadas. No se presentan como evidencia de Flask.

Flask A usa la navegación/tokens reales existentes y enlaces/secciones HTML en vez de copiar las pestañas y acciones simuladas de cinco áreas. La diferencia es intencional: sólo consulta está implementada. El enlace a acciones legacy mantiene revisión explícita y servicios oficiales.

- **B:** historial owner-only con filtros/paginación real en servidor y originales con autorización/hash; fuentes retiradas y decisiones auditables. Sólo contrato/prototipo en este PR, ningún endpoint nuevo de B.
- **C:** presentación guiada de confirmación e importaciones; no implementada. No cambiar escritores estabilizados dentro de A.
- **D:** cierre de integración, rendimiento sobre historiales reales y accesibilidad completa. La composición actual conserva lecturas auxiliares acotadas de Nutrition; no se presume una prueba de carga de producción.
- Smoke físico Android/iOS y prueba externa real de Open Food Facts permanecen separados. Los contratos no cambian; esto no acredita dispositivos ni servicio externo.
- Revisión final antes de integrar; no merge ni despliegue autorizados por esta entrega. No se comprobó ni modificó NAS/producción durante A.

## Reproducción

Desde `backend/`, ejecutar `..\.venv\Scripts\python.exe -m pytest -q tests/test_energy_experience.py` y las suites focales de Energy/Nutrition. Para UI, iniciar `scripts/energy/experience_qa_app.py` con la venv existente; imprime una URL loopback efímera. Pasarla como `ENERGY_QA_URL` a `scripts/energy/experience_ui_qa.cjs` con Node/Playwright/Edge existentes. No usar el servidor principal ni cuentas reales.

`scripts/energy/experience_mariadb_qa.py` requiere la conexión QA privada ya existente, backend/schema montados read-only y salida de evidencia aislada. Rechaza schema o usuario distintos de QA y exige head 0046 antes de crear fixtures. No contiene credenciales reales ni ejecuta migraciones.

El informe operativo previo `ENERGY_18_PRODUCTION_CLOSEOUT.md` permanece local sin versionar y fuera del PR. Es un archivo preexistente preservado; el diff de A incluye únicamente diseño, consulta y evidencia QA sintética.
