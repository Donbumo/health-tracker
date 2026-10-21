# Energy Experience 2.0 C — capturas Flask reales

Fixtures ficticias, SQLite temporal y login real; ningún dato personal ni NAS. [Informe](../../docs/ENERGY_EXPERIENCE_2_0_C.md), [matriz QA](qa/report.json).

32 PNG: ocho vistas × dos temas × mobile 390 / desktop 1366. Las primeras siete vistas integran la matriz de seis anchos; contradicción añade cuatro verificaciones específicas.

| Vista | Mobile dark / light | Desktop dark / light |
| --- | --- | --- |
| Identificación | [Dark](qa/identify-dark-390.png) · [Light](qa/identify-light-390.png) | [Dark](qa/identify-dark-1366.png) · [Light](qa/identify-light-1366.png) |
| Preview | [Dark](qa/preview-dark-390.png) · [Light](qa/preview-light-390.png) | [Dark](qa/preview-dark-1366.png) · [Light](qa/preview-light-1366.png) |
| Operaciones de importación | [Dark](qa/operations-dark-390.png) · [Light](qa/operations-light-390.png) | [Dark](qa/operations-dark-1366.png) · [Light](qa/operations-light-1366.png) |
| Confirmación de importación | [Dark](qa/confirmation-dark-390.png) · [Light](qa/confirmation-light-390.png) | [Dark](qa/confirmation-dark-1366.png) · [Light](qa/confirmation-light-1366.png) |
| Decidir por campo | [Dark](qa/decide-dark-390.png) · [Light](qa/decide-light-390.png) | [Dark](qa/decide-dark-1366.png) · [Light](qa/decide-light-1366.png) |
| Revisar decisiones | [Dark](qa/decision-operations-dark-390.png) · [Light](qa/decision-operations-light-390.png) | [Dark](qa/decision-operations-dark-1366.png) · [Light](qa/decision-operations-light-1366.png) |
| Confirmar decisiones | [Dark](qa/decision-confirmation-dark-390.png) · [Light](qa/decision-confirmation-light-390.png) | [Dark](qa/decision-confirmation-dark-1366.png) · [Light](qa/decision-confirmation-light-1366.png) |
| Archivo contradictorio | [Dark](qa/import-conflict-dark-390.png) · [Light](qa/import-conflict-light-390.png) | [Dark](qa/import-conflict-dark-1366.png) · [Light](qa/import-conflict-light-1366.png) |

Las vistas de contradicción desplazan hasta el primer campo para mostrar valor previo de fuente, canónico pendiente y propuesta. Las demás son primer viewport. C es sólo propuesta para PR; sin merge ni despliegue.
