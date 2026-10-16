# Nutrition Experience 2.1 — QA y compatibilidad

Estado: entrega revisada; publicación de commit y PR autorizada. Rama
`feature/nutrition-experience-import-2-1`, base/remoto master verificado
`6cf6a965c5e426f4c0370d4ad6616edbd549245d`. No merge,
NAS, producción, worktrees ni stacks nuevos. No se leyó `.env` ni se usaron
datos personales; las cuentas, archivos de dieta y registros son QA ficticios.

## Gates ejecutados

| Gate | Resultado final |
| --- | --- |
| Backend completo de la entrega aprobada | **1.272 PASS, 34 skipped**; warning esperado de ZIP duplicado malicioso en fixture. No repetida tras los dos ajustes focales finales. |
| Ajustes finales autorizados 2026-10-14 | **7 tests PASS**, **20 viewport PASS**, **10 capturas mobile**, **14 consultas × tres repeticiones**; sin errores JS, requests externas ni overflow. |
| Nutrición focal final | **90 PASS** después del ajuste final de la revisión; extracción, interpretación, UI, idempotencia, conservación, migración y ownership. |
| MariaDB local existente | `nutrition_intelligence_qa_20261009`, usuario QA existente, sin privilegios globales nuevos. |
| Migración | Upgrade aditivo 0044 → `20261013_0045`; single head y `db check` sin operaciones pendientes. |
| Upgrade repetido | No-op seguro; no se recreó schema ni se borró contenido anterior. |
| Conservación durante validación final | 75 snapshots QA anteriores comparados por hash y conservados al ejecutar el runner final. |
| READ COMMITTED / REPEATABLE READ | Importación simultánea idéntica: un recibo y un MealLog por owner, 450 kcal una sola vez. |
| JSON / ZIP restore | Servicios oficiales, owner remap, planes, recibos y snapshots conservados en ambos niveles de aislamiento. |
| Rollback | Guard 0045 bloquea antes de DDL con datos privados nuevos; 0044 nunca se downgradó. |
| Feature flag | Default false conservado; flag false bloquea nuevas escrituras y permite leer historia. |
| Historial | Fixture 30 días mixed legacy/MealLog; día vacío, navegación, reciente, calendario, semana/mes y 7/30/90. |
| Catálogo | 13.685 alimentos públicos, cuatro fuentes; 55 consultas representativas con disponibilidad y tiempos reales. |
| Importación | 17 archivos representativos; 14 escenarios solicitados, firmas reales y evidencia de fila/página. |
| UI | 252 combinaciones: 21 vistas × 360/390/430/768/1024/1366 × dark/light; foco visible, controles legibles y sin overflow. |
| Flujos reales | PDF → dos alimentos USDA → plan sin consumo; PNG OCR → producto 100 ml → edición de revisión 2; OFF simulado → prefill → privado; biblioteca con 125 productos/recetas; eliminación no confirmada y retención confirmada. |
| Red de capturas | Cero solicitudes externas y cero errores de JavaScript. |
| Verificación estática | compileall, configuración Compose con variables ficticias y diff check sin errores; no se leyó `.env` ni se inició ningún stack. |

Evidencia machine-readable en `design/nutrition-intelligence-2-1/qa/`:
`backend-tests.xml`, `mariadb-report.json`, `ui-report.json`,
`search-report.json`, `qa-state.json`, `ranking-report.json`, `chart-report.json`,
`focal-product-tests.xml` y `mariadb-product-report.json`. La cuenta del manifest es ficticia y no
contiene contraseñas/tokens. No se distribuye la DB efímera.

Corrección focal de producto: [informe final](NUTRITION_EXPERIENCE_2_1_FINAL_REVIEW.md).
Las consultas nuevas y la política de archivo también pasan en MariaDB con
ambos niveles de aislamiento, sin DDL ni repetir la migración validada.

## Integridad verificada

Los tests verifican unknown frente a cero, trace/below-limit, formas químicas,
subtotal parcial, declaración frente a composición, escalado explícito de
porción y porcentajes de ingredientes con masa total. No se adivina densidad,
porción universal ni semántica total/neto. OFF ambiguo y porcentajes sin base
permanecen como evidencia, fuera de la suma.

Editar un alimento o receta no cambia el snapshot consumido. Editar un plan
crea otra revisión y una revisión obsoleta entra en conflicto. Repetir crea
otro evento con confirmación. No se suma MealLog con su proyección; el agregado
legacy sólo se añade después de resolver autoridad explícita. La masa excesiva
sin rendimiento coherente bloquea posibles platos/componentes superpuestos.

Errores inducidos del segundo write revierten todo el batch y conservan la
auditoría. Reenvío de bytes con otro nombre es idempotente. Otros owners no
leen una revisión privada; falta CSRF bloquea antes de escribir. Los valores
originales, unidades/evidencia y snapshots son exportables mediante el contrato
completo; un evento existente diferente no se reemplaza.

## Compatibilidad Android, iOS y Operator

No se cambiaron requeridos de JSON Schemas mobile v1 ni DTOs nativos. UUID,
revisión, nullable decimal strings, `snapshot_available` y `data_complete`
mantienen el comportamiento vigente. La suite backend cubre rutas mobile,
idempotencia, ownership y guards de mutación de proyecciones con snapshot.

Android conserva campos por 100 g. Para productos ml sin densidad, esos valores
son desconocidos, no una equivalencia inventada; su edición completa está en
Nutrición web. Un PATCH incompatible recibe error 422 dentro del envelope
mobile, sin perder datos ni producir 500. El native client no incorpora todavía
el nuevo OCR/biblioteca ni un editor completo por ml.

iOS no añade un módulo de Nutrition 2.1 en esta rama. Las rutas/contratos de
training, sync y cuenta existentes se conservan, con tests backend y revisión
estática de consumidores. No se ejecutó Xcode, simulador iOS ni smoke físico
en Windows. No se presenta un build nativo como validado.

Operator mantiene sus capacidades y proveedores. Sus tests pasan. Se corrigió
únicamente un falso positivo del test de privacidad: un UUID aleatorio podía
contener los dígitos “520”; el test excluye sólo el UUID opaco validado y sigue
detectando valores clínicos en el resto del log. El logging productivo no cambió.

## Stop gate y riesgos que requieren revisión

La evidencia cumple el flujo local solicitado. Sigue pendiente revisión visual
y funcional del usuario, y evaluación de rollout sobre un backup autorizado.
No se autoriza despliegue, activación, migración productiva ni downgrade 0044.

OCR requiere corrección de layouts no reconocidos; no interpreta imágenes de
plato como recetas exactas. OFF es una muestra México acotada y no certificada.
La búsqueda por palabras puede ofrecer mezclas/platos relacionados; no existe
una tasa de falsos positivos garantizada. La retención de nutrientes por cocción
no se estima desde rendimiento. Los originales permanecen en almacenamiento
privado; cancelar conserva el archivo por defecto. Hay eliminación explícita de originales no confirmados, con advertencia; confirmados y compartidos se retienen. Se mantienen límites de
backup/export existentes, que deben medirse para historias futuras voluminosas.

El usuario autorizó commit, push y PR después de los dos ajustes focales.
La suite completa anterior se conserva como evidencia; sólo se repitieron
los tests, viewport y consultas afectados. Véanse `final-focal-tests.xml`,
`final-focal-report.json` y las diez capturas `final-first-*-390.png`.
El merge y despliegue requieren una decisión posterior. Permanecen separados
el smoke físico Android/iOS y la consulta real externa a Open Food Facts.
