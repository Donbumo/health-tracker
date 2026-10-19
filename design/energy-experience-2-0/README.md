# Energy Experience 2.0 — revisión visual

Propuesta local en `feature/energy-experience-2-0`, basada en el hotfix desplegado `9e2f2dc7fea728bfec3c8abf1aed6bc7bb428852`. Dirección aprobada y prototipo ajustado; entrega Flask A preparada en la misma rama, sin despliegue.

Abrir [index.html](index.html) directamente en el navegador. No requiere servidor, puerto, credenciales, cuenta o conexión. Todos los números corresponden a fixtures ficticias de 2040 y las interacciones viven sólo en memoria.

[Auditoría, arquitectura y entregas](../../docs/ENERGY_EXPERIENCE_2_0.md) · [Cierre productivo #18](https://github.com/Donbumo/health-tracker/issues/18).

## Recorridos

- Fecha anterior/siguiente, «Ir a hoy» y último registro, periodo 7/30/90 y tema dark/light.
- Gasto total protagonista, barras diarias y línea de media móvil con denominador; ingesta/balance como contexto, más tendencias de total/activas/reposo/pasos/distancia con unidades y fuente. Parciales separados, huecos y balance con ambos signos.
- Calendario del mes de la fecha seleccionada, navegación anterior/siguiente entre meses y años; estados textuales y consulta sin escrituras.
- Historial con filtros combinables de fecha, fuente y evento; páginas locales demostrativas. Contrato B: páginas de 25 en servidor, owner-only y originales con autorización/hash. No implementado en Flask A.
- Fuentes: ejemplo del 2 de febrero en conflicto → elegir origen → revisar fecha/campo/cantidad → checkbox explícito → confirmar simulación. El original no cambia.
- Importar: ejemplo ficticio → preview → dos comprobaciones → confirmación. Sólo después aparece actividad parcial; no se infieren calorías. No se leen archivos del usuario.
- Historial filtrable y fuentes retiradas explícitas; un día sin evidencia no inventa orígenes.
- Exportar explica JSON 1.1 frente a CSV/backup de cuenta; el prototipo no genera archivos reales.

## Capturas

| Estado | Mobile 390 | Desktop 1366 |
| --- | --- | --- |
| Resumen dark | [Ver](qa/overview-dark-390.png) | [Ver](qa/overview-dark-1366.png) |
| Resumen light | [Ver](qa/overview-light-390.png) | [Ver](qa/overview-light-1366.png) |
| Fuentes en conflicto | [Dark](qa/sources-conflict-dark-390.png) · [Light](qa/sources-conflict-light-390.png) | Cubierto por QA de layout |
| Hoy vacío | [Dark, último registro visible](qa/empty-today-dark-390.png) | Cubierto por estado de datos |
| Importación | [Revisión light, foco en comprobaciones](qa/import-review-light-390.png) | Cubierto por QA de layout |
| Calendario | Cubierto por QA de layout | [Dark](qa/calendar-dark-1366.png) |
| Historial | Cubierto por QA de layout | [Light](qa/history-light-1366.png) |

Los resúmenes y el estado de hoy se capturaron en el primer viewport. La revisión de importación conserva el desplazamiento natural al control que recibió foco. Las capturas no pertenecen a Flask productivo ni a cuentas reales.

## QA reproducible

```powershell
$env:NODE_PATH=$existingBundledNodeModules
node design/energy-experience-2-0/qa.cjs
```

Playwright existente, Edge headless, archivo local; sin instalación de paquetes, stack ni puertos nuevos. [report.json](qa/report.json): **60 combinaciones PASS**, cinco vistas × seis anchos (360/390/430/768/1024/1366) × dos temas; 10 capturas, cero requests externos y cero errores JavaScript.

Se verifican foco visible (incluidos segmentos de fecha nativa), Tab, flechas/Home/End en pestañas, radio/checkbox, Escape de diálogo, métricas en primer viewport, eje cero de balance, desconocido/cero/parcial, hoy vacío, selección de calendario y confirmación diferida. Revisión visual realizada sobre Resumen mobile dark/escritorio light y fuentes/importación mobile light. No equivale a auditoría WCAG completa.

La evidencia anterior corresponde sólo al prototipo. [Capturas Flask A](qa-flask/report.json) y [QA de implementación](../../docs/ENERGY_EXPERIENCE_2_0_A_QA.md) son separadas: 36 combinaciones de seis anchos × dos temas × tres períodos, 14 capturas reales HTTP. No se modifica schema, migración, flag ni contrato móvil; integración y despliegue pendientes de revisión.
