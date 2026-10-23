# D — evidencia de Flask real, sólo QA ficticia

[Informe de D](../../docs/ENERGY_EXPERIENCE_2_0_D.md) · [Matriz WCAG](../../docs/ENERGY_EXPERIENCE_2_0_D_ACCESSIBILITY.md) · [C operativa antes de D](../../docs/ENERGY_EXPERIENCE_2_0_C_PRODUCTION.md).

81 PNG originales; 390 móvil y 1366 escritorio, dark/light; adicionales de layout equivalente al 200%, texto raíz 200% y colores forzados. Sin datos personales ni secretos. Las capturas completas de confirmación muestran checkbox y acciones al final; otras son viewport para revisar composición/foco. El manifiesto enumera archivo, dimensiones, tamaño y SHA256 de estas **imágenes sintéticas**, no de archivos de salud.

| Caso | Móvil | Escritorio |
| --- | --- | --- |
| Resumen conocido | [oscuro](screenshots/known-390-dark.png), [claro](screenshots/known-390-light.png) | [oscuro](screenshots/known-1366-dark.png), [claro](screenshots/known-1366-light.png) |
| Calendario mínimo | [claro](screenshots/calendar-min-390-light.png), [oscuro](screenshots/calendar-min-390-dark.png) | [oscuro](screenshots/calendar-min-1366-dark.png) |
| Calendario máximo | [oscuro](screenshots/calendar-max-390-dark.png) | [claro](screenshots/calendar-max-1366-light.png), [oscuro](screenshots/calendar-max-1366-dark.png) |
| Parcial/conflicto | [oscuro](screenshots/partial-chart-390-dark.png) | [claro](screenshots/partial-chart-1366-light.png) |
| Gráfica y tabla | [claro](screenshots/table-open-extra-390-light.png) | [oscuro](screenshots/table-open-extra-1366-dark.png) |
| Fuentes | [claro](screenshots/sources-390-light.png) | [oscuro](screenshots/sources-1366-dark.png) |
| Historial/filtros | [oscuro](screenshots/history-filters-390-dark.png) | [claro](screenshots/history-filters-1366-light.png) |
| Pasos de importación | [1](screenshots/import-390-dark.png), [2](screenshots/import-step-2-390-dark.png), [3](screenshots/import-step-3-390-dark.png), [4 completo](screenshots/import-step-4-390-dark.png) | [entrada clara](screenshots/import-1366-light.png) |
| Error y recuperación | [campo](screenshots/review-error-390-light.png), [consulta](screenshots/query-error-390-dark.png) | [filtros](screenshots/history-error-1366-light.png), [fuentes](screenshots/sources-error-1366-dark.png) |
| Confirmación | [completa oscura](screenshots/review-confirm-390-dark.png), [clara](screenshots/review-confirm-390-light.png) | [clara](screenshots/review-confirm-1366-light.png) |
| Accesibilidad adicional | [texto raíz 200%](screenshots/text200-390-light.png) | [layout 200% equivalente](screenshots/zoom200-layout-683-dark.png), [colores forzados](screenshots/forced-colors-1366.png) |

## Reproducción local

Desde la raíz, Python del entorno de desarrollo con dependencias de tests instaladas:

```powershell
.venv/Scripts/python.exe scripts/energy/accessibility_qa_app.py
```

El servidor imprime un puerto loopback aleatorio; crea SQLite/storage **temporales** y 10.000 eventos sintéticos adicionales. Usuario `QA-energy-D`, contraseña ficticia `fictional-energy-D-password`; nunca usar esas credenciales fuera de este servidor. La segunda cuenta QA pertenece a otro propietario. Nutrition está habilitada sólo en este servidor efímero; OFF externo permanece desactivado.

Con Playwright, Edge y axe-core 4.14.0 disponibles en un `NODE_PATH` externo al repositorio (ninguna dependencia productiva añadida):

```powershell
$env:ENERGY_QA_URL='http://127.0.0.1:PUERTO_IMPRESO'
node scripts/energy/accessibility_ui_qa.cjs
node scripts/energy/accessibility_visual_checks.cjs
```

Sustituir el puerto por el impreso. Ambos scripts rechazan un destino distinto del loopback explícito. No leen `.env`. Se recorren A→B→C→B→A; las confirmaciones se preparan pero el runner visual cancela. Las escrituras/rollback/idempotencia se prueban aparte en pytest y MariaDB.

```powershell
.venv/Scripts/python.exe -m pytest -q backend/tests/test_energy_accessibility.py backend/tests/test_energy_experience.py backend/tests/test_energy_guided.py backend/tests/test_energy_provenance.py
```

El runner `scripts/energy/accessibility_container_qa.py` usa exclusivamente el schema QA local preexistente y verifica nombre/usuario/head antes de crear fixtures. Requiere Python 3.12 compatible, backend y schemas read-only, wheels pytest offline, salida `/evidence` y configuración QA privada inyectada al contenedor; **no ejecutarlo con configuración de producción**. Ejecuta focales Linux + RC/RR + db check, sin upgrade/downgrade/stamp/DDL.

## Resultados y límites

- [Flask/Edge](qa/accessibility.json): 250 layouts, 78 scans axe, 12 recorridos/comprobaciones; cero violaciones detectadas.
- [Visual adicional](qa/visual-checks.json): 20 scans adicionales, 30 casos de espaciado, contraste/targets/reduced-motion y colores forzados.
- [Baseline anterior a D](qa/baseline.json): contraste oscuro 2,14:1 y definición inválida reproducidos; se conservan como antes/después.
- [Windows final focal](qa/windows-final-focal.xml): 103 PASS/1 skip. [Linux final](qa/linux-focal.xml): 125 PASS. [MariaDB](qa/mariadb.json): RC/RR y 0046/db check PASS.
- [Suite general](qa/windows-suite.xml): 1.401 PASS/35 skipped antes del refinamiento final de recuperación B; focales finales revalidados. XML saneados: sin hostname ni logs; conservan IDs/resultados/tiempos/razones de skip.

El árbol AX no es un lector de pantalla. Narrador/NVDA y zoom nativo con asistencia están pendientes. El layout equivalente 683×450 y el texto raíz al 200% se documentan como métodos separados, sin afirmar uso del menú de zoom. No se declara certificación WCAG ni autorización de merge/despliegue D. PITR, Android/iOS físico y OFF externo continúan separados.
