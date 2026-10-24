# Energy Experience 2.0 D — calidad y accesibilidad para revisión

23-10-2026. Rama `feature/energy-experience-2-0-d`, desde master C `fcf901b903ab7e467444e6f9a5fe898624207efa`. C se cerró en producción **antes** de iniciar D: [informe operativo](ENERGY_EXPERIENCE_2_0_C_PRODUCTION.md). D no se fusiona ni se despliega con esta entrega.

## Cambios

- Navegación diaria/mensual deshabilitada en 01/01/1900 y 31/12/9998: sin URL fuera del intervalo, sin elementos deshabilitados en Tab. Los eventos de fechas históricas fuera del rango siguen visibles en B, con sus originales, sin enlace inválido. «Último registro» elige la última fecha navegable del propietario. No se borran ni corrigen datos.
- Estructura válida de las definiciones del día; títulos de página con fecha/paso/página; estados atómicos, calendario con fecha/estado y tablas con caption, encabezados y región desplazable por teclado.
- Contraste de botones oscuros corregido (blanco sobre cian: 2,14:1 antes; 8,04:1 después). Foco de texto de alto contraste también en la navegación compartida **sólo al abrir Energía**; bordes de inputs/select/textarea contrastados. Flechas de 44 px; etiqueta completa de confirmación pulsable.
- Consultas A y filtros/fechas B inválidos muestran error enfocado y recuperación. C conserva elecciones y valores escapados ante error manual, identifica el campo y exige una nueva revisión firmada antes de confirmar; no ejecuta el borrador erróneo. Una eliminación concurrente devuelve 404 al reconstruir el formulario.
- `private, no-store` y `nosniff` también en respuestas Energía legacy, redirecciones, 400/404 y errores CSRF. No se cambia el service worker ni otros dominios.

El escritor canónico, resolución de conflictos, snapshots, firmas/TTL, CSRF, confirmación, transacciones, originales, JSON 1.0/1.1, UUID móviles, Nutrition 2.1 y 0046 siguen intactos. No hay nuevas migraciones ni dependencias productivas. Axe/Playwright se usan fuera del runtime de la aplicación.

## Validación

Todos los datos de D son ficticios. Flask real local con storage/SQLite temporales, dos propietarios y **10.000 eventos sintéticos adicionales**. MariaDB QA LOCAL existente con aserción previa de schema, usuario e isolation; no se usa NAS ni producción para D.

| Gate | Evidencia |
| --- | --- |
| Suite general | 1.401 PASS, 35 skipped; aviso esperado de ZIP duplicado en fixture negativa. Ejecutada antes del último refinamiento de errores B; se revalidó el área afectada en el estado final. |
| Focal final Windows | **108 PASS, 1 skip** (symlink Windows); 37 pruebas nuevas D. A/B/C/D, límites 7/30/90, ownership, errores, recuperación, originales y firmas; [JUnit final asistido](../design/energy-experience-2-0-d/qa/assisted-final-focal.xml). |
| Focal Linux Python 3.12 | **130 PASS**, A/B/C/D + escritor canónico/round-trip; incluye symlink real: [JUnit](../design/energy-experience-2-0-d/qa/linux-focal.xml). |
| MariaDB | READ COMMITTED + REPEATABLE READ; límites, errores sin escrituras, owner-only, `no-store`, preview, confirmación, replay, conflicto 409, rollback, originales y `db check` en 0046: [resultado](../design/energy-experience-2-0-d/qa/mariadb.json). Sin DDL. |
| Flask/Edge | **250 comprobaciones de layout**, 12 comprobaciones/recorridos de teclado y 78 scans axe sin violaciones detectadas; 320/360/390/430/768/1024/1366, dark/light, fechas límite, conocido/parcial/conflicto/hueco/retirado, B, cuatro pasos C y errores. [Resultado](../design/energy-experience-2-0-d/qa/accessibility.json). |
| Accesibilidad visual | Otros **20 scans axe** sin violaciones detectadas y **30 pruebas de espaciado**. Teclado, árbol AX, contraste, targets, reduced-motion y colores forzados: [resultado adicional](../design/energy-experience-2-0-d/qa/visual-checks.json), [auditoría por criterio](ENERGY_EXPERIENCE_2_0_D_ACCESSIBILITY.md). **81 capturas**. |

Revisión visual efectuada de las capturas y detalles a tamaño original: jerarquía, ambos temas, errores enfocados, confirmación móvil completa, calendario límite y gráficas/tablas. [Galería y reproducción](../design/energy-experience-2-0-d/README.md). Sin overflow de página; la tabla ancha desplaza dentro de su región. Las capturas son QA, nunca datos reales.

El zoom se comprobó mediante layout equivalente a 1366×900 al 200% (683×450 CSS px), reflow a 320 CSS px y prueba independiente de tamaño raíz al 200%. **Zoom nativo aún no corroborado**: el usuario informó menú 200 %, pero la pestaña controlada conservó las medidas/DPR de 100 %; Z01 BLOCKED, pendiente resolver la discrepancia con la misma ventana. No se confunde pinch zoom con reflow.

Historial: primera/intermedia/última página y filtros, cinco muestras de navegación HTTP+DOM por caso, máximo 25 eventos renderizados/página; cifras finales en `accessibility.json`. Medición local SQLite secuencial, no benchmark NAS ni carga concurrente. No se cambian consultas/índices de B; el riesgo de scans JSON/DISTINCT documentado en B permanece.

## Gate de revisión y pendientes

D queda para revisión en PR independiente. **No es una certificación WCAG completa**: el árbol AX y axe no sustituyen un lector real. El usuario confirmó **Narrador de Windows con Edge**, QA en primer plano y lector activo; N01–N10 PASS por confirmación audible específica por caso. [Seguimiento asistido y TTL](ENERGY_EXPERIENCE_2_0_D_ASSISTED_CLOSEOUT.md). La lectura de gráficas, tablas, fechas, estados/pasos, errores y controles está registrada por caso; el zoom nativo permanece sin corroborar.

La espera real de 903,02 segundos confirmó 409 sin escritura. Se corrigió la recuperación manual del borrador sin token automático; se mantienen 15 minutos y todas las validaciones. El ajuste del plazo/aviso previo no existe y su propuesta requiere revisión: gate 2.2.1 FAIL. [Informe asistido completo](ENERGY_EXPERIENCE_2_0_D_ASSISTED_CLOSEOUT.md), con cuatro capturas de recuperación y una adicional de expiración real, seis controles del destino QA y cuatro verificaciones UI reales. No autorizar el cierre de conformidad WCAG hasta resolver los puntos manuales y de tiempo.

PITR, smoke físico Android/iOS y Open Food Facts externo siguen como pendientes **separados** de D. No hubo nuevas escrituras productivas, flags modificados ni originales productivos en esta evidencia. El informe local previo de issue #18 permanece fuera de Git.
