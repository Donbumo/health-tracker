# D — cierre asistido: Narrador, zoom nativo y TTL

Fecha: 23-10-2026, zona `America/Mexico_City`. Base revisada de PR #25: `061c460661f3daa922bceb50710b0d31a224044e`. Sin merge ni despliegue; C permanece como versión productiva. Esta entrega no certifica conformidad WCAG.

## Aislamiento y entorno

[Evidencia del entorno](../design/energy-experience-2-0-d/qa/assisted-environment.json). QA ficticia recreada mediante `scripts/energy/accessibility_qa_app.py`; el proceso imprime URL, PID y etiqueta. Listener verificado: **127.0.0.1:55229 → PID 32944**, Python 3.12, coincide con el PID impreso. No listener 0.0.0.0 ni NAS. SQLite/storage temporales con exactamente los dos usuarios QA del script; sin configuración ni credenciales personales.

Edge dedicado mediante Playwright `launch` + `newContext`, headful y sin perfil persistente solicitado: **155.0.4283.45**, PID **39824**. URL comprobada mediante el contexto: `http://127.0.0.1:55229/energy?date=2040-02-03&period=7`; título «Energía · 2040-02-03 · Health Tracker», etiqueta «QA ficticia D» y 2450 kcal. Ventana devuelta por el inventario: `MSEdge`, identificador 26612294. Las cifras son fixtures sintéticas.

Sistema: **Windows 11 Pro 25H2, build 26200.9711**; `EditionID=Professional`, `DisplayVersion=25H2` y compilación contrastada con la [tabla oficial de Microsoft](https://learn.microsoft.com/en-us/windows/release-health/windows11-release-information). La cadena histórica del registro `ProductName=Windows 10 Pro` se conserva literalmente como dato separado, sin usarla para identificar la versión. Binario instalado de Narrador: **10.0.26100.8972**. Estos datos identifican el entorno; no prueban que Narrador esté activo ni que algo haya sido oído.

El intento anterior del control nativo fue detenido porque no pudo determinar la URL con suficiente confianza. La protección sigue intacta: no se envían combinaciones Windows ni entradas ciegas. Se solicitó confirmación humana de la URL/ventana en primer plano y activación manual de Narrador. El usuario confirmó disponibilidad de Narrador con Edge y que puede escuchar; **eso no equivale a un resultado audible por caso**.

Tras corregir la recuperación, QA se reinició: **127.0.0.1:65440 → PID 32168**, PID/listener nuevamente verificados. La misma ventana Edge dedicada apunta ahora a `http://127.0.0.1:65440/energy?date=2040-02-03&period=7`. El puerto anterior se cerró. Se solicitó confirmación humana de esta URL nueva; no se recibió confirmación de primer plano/Narrador activo ni observaciones por caso. No se observó proceso Narrador en la comprobación previa al reinicio. El seguimiento conserva la identificación de ambas ejecuciones; PID/puertos son evidencia puntual, no configuración fija.

## Matriz audible

Resultados detallados y base de observación en [matriz JSON](../design/energy-experience-2-0-d/qa/assisted-matrix.json). Sólo una confirmación humana específica puede convertir un caso audible en PASS. AX, axe, foco DOM o captura no lo sustituyen.

| Caso | Recorrido y esperado | Estado |
| --- | --- | --- |
| N01 | Título, encabezados y regiones de Energía; salto a main, sin navegación repetida obligatoria. | NOT TESTED |
| N02 | 1900-01-01: fecha/días/estados legibles; día/mes anterior no disponibles y sin activación. | NOT TESTED |
| N03 | 9998-12-31: día/mes siguiente no disponibles; lectura y regreso sin salir del intervalo. | NOT TESTED |
| N04 | Conocido 2450, cero 2040-01-31, ausencia 2041-01-01, parcial 2040-02-04 y conflicto/parcial de ingesta 2040-02-01 distinguibles al escuchar. | NOT TESTED |
| N05 | Nombre de gráfica, explicación y tabla equivalente con encabezados/valores/denominadores; sin anuncio duplicado que impida comprender. | NOT TESTED |
| N06 | Fuentes, decisiones, historial, filtros, páginas y nombre/acción de original protegido. | NOT TESTED |
| N07 | Error de fecha/filtro y campo manual inválido; anuncio, foco, vínculo de corrección y recuperación. | NOT TESTED |
| N08 | Importación: original ficticio → fecha/métricas → operaciones → confirmación; anunciar paso, campos y unidades. | NOT TESTED |
| N09 | Checkbox, confirmar/cancelar y regreso; cancelar sin escritura ni original guardado. | NOT TESTED |
| N10 | Estado/error anunciado de forma comprensible y oportuna; escuchar tras navegación y validación. | NOT TESTED |
| Z01 | Zoom **nativo de Edge 200%**, con menú/atajo humano; lectura, reflow y tablas. | NOT TESTED |
| Z02 | A/B/C al 200%: Tab/Shift+Tab, foco visible, formulario completo y confirmación sin controles inaccesibles/tapados. | NOT TESTED |

La escucha requiere confirmación humana de primer plano y de Narrador activo. Si no se recibe, los casos permanecen NOT TESTED/BLOCKED; no se deducen resultados de la disponibilidad del lector.

## Zoom nativo: método de verificación

El usuario debe elegir 200% en el menú de Edge de **esta ventana QA**, sin cambiar escalado de Windows. Registrar el porcentaje confirmado, `devicePixelRatio`, anchura CSS y screenshot sin aplicar `setViewportSize`, `setPageScaleFactor`, CSS `zoom` ni redimensionado de texto como sustituto. Base inicial: ventana 1366×900, contenido 1342×808 CSS px, DPR 1. La mitad de anchura y DPR 2 son comprobación técnica complementaria; la lectura/foco siguen requiriendo al humano.

Guías oficiales: [accesibilidad/zoom de Edge](https://support.microsoft.com/es-es/accessibility/edge/accessibility-features-in-microsoft-edge), [comandos de Narrador](https://support.microsoft.com/es-es/accessibility/windows/narrator/appendix-b-narrator-keyboard-commands-and-touch-gestures). La tecla Narrador depende de la configuración del usuario. El agente no envía combinaciones de Windows a ventanas no verificadas.

## TTL de C

Prueba reproducible: `scripts/energy/accessibility_ttl_qa.py`, sólo URL loopback explícita y `qa.sqlite` dentro de una carpeta `QA-energy-D-*`. Antes de cualquier POST comprueba que existen exactamente las dos cuentas ficticias. Autenticación/CSRF reales; dos tokens genuinos del servidor, importación y decisiones, llevados a paso 4. Espera **903 segundos reales**; no simula reloj, no cambia TTL ni vuelve a firmar tokens. Snapshot SQLite read-only del dominio y metadata antes/después; tokens, originales, credenciales y hashes de snapshot no se publican.

[Resultado HTTP de caducidad](../design/energy-experience-2-0-d/qa/ttl-real-expiry.json): prueba **completada entre 16:03 y 16:18 de México, 903,02 segundos reales**, contra el comportamiento revisado inicial. Importación y decisiones devolvieron **409**, sin token nuevo automático, sin cambios de dominio ni metadata de archivos. Recuperación nueva: GET/preview 200, pero exigía reintroducir las decisiones y volver a elegir el archivo. El resultado audible del aviso/error es un gate distinto y sigue NOT TESTED.

Hallazgo ya reproducido: el aviso estático de 15 minutos aparece en el paso 4; no en pasos 2/3, aunque el límite ya existe. No hay aviso próximo al vencimiento ni controles para ajustar/desactivar/extender el tiempo. El estado del dominio puede seguir válido aunque la firma caduque.

[WCAG 2.2.1](https://www.w3.org/WAI/WCAG22/Understanding/timing-adjustable.html) también abarca límites introducidos por seguridad; ésta no es por sí sola una excepción. Sin una alternativa de tiempo ni justificación de esencialidad revisada, no se puede cerrar ese criterio como conforme. [3.3.7](https://www.w3.org/WAI/WCAG22/Understanding/redundant-entry.html) exige evitar reentrada en el mismo proceso, con excepciones específicas; una firma vencida no demuestra que los valores sigan siendo inválidos ni que deban borrarse del borrador.

## Corrección aplicada y revalidación

Se corrigió la pérdida de valores manuales de decisiones en D. Un 409 reconstruye el **día actual del propietario**, conserva la propuesta manual escapada y devuelve el paso 2 con enlace de recuperación. No devuelve `review_token`, no escribe y no acepta otra vez la confirmación inutilizable. Las selecciones por índice de fuente vuelven a «Conservar»: podrían apuntar a otra evidencia tras una revisión obsoleta. El usuario debe elegir/revisar las fuentes y repetir revisión y confirmación.

Sólo el POST de revisión explícita **ya existente** puede producir una nueva propuesta firmada. No se añadió acción de renovación, ni se cambió `max_age=900`, serializer, validación, CSRF, ownership, fingerprint, confirmación, escritor ni migración. La importación sigue exigiendo reelección del original tras caducidad; no se guarda antes de confirmar.

| Gate focal final | Resultado |
| --- | --- |
| Expiración, revisión obsoleta y firma inválida; borrador escapado, sin escritura/token automático, nueva revisión explícita | PASS, pruebas Flask con edad de firma controlada de 903 s. No es una segunda espera real de 15 min. |
| Índices de fuente descartados antes de otra elección | PASS. |
| Windows A/B/C/D | **108 PASS, 1 skip**, [JUnit final](../design/energy-experience-2-0-d/qa/assisted-final-focal.xml). |
| Linux Python 3.12 / symlink / canónico / round-trip | **130 PASS**, [JUnit](../design/energy-experience-2-0-d/qa/linux-focal.xml). |
| MariaDB QA local RC/RR + db check | PASS, 0046 sin DDL; [resultado](../design/energy-experience-2-0-d/qa/mariadb.json). |
| Destino remoto, userinfo, path ajeno, carpeta/archivo/usuarios no QA | **6 PASS**, rechazo antes de construir cliente HTTP; [JUnit](../design/energy-experience-2-0-d/qa/ttl-guard-tests.xml). |
| HTTP real de recuperación, 390/1366 y claro/oscuro | **4 PASS**, firma inválida → 409 → borrador/foco → revisión nueva → cancelar sin cambiar canónico. Axe sin violaciones detectadas y sin overflow; [resultado](../design/energy-experience-2-0-d/assisted/recovery-ui.json). No resultado audible ni zoom nativo. |

Capturas revisadas: [móvil oscuro](../design/energy-experience-2-0-d/assisted/screenshots/draft-409-390-dark.png), [móvil claro](../design/energy-experience-2-0-d/assisted/screenshots/draft-409-390-light.png), [escritorio claro](../design/energy-experience-2-0-d/assisted/screenshots/draft-409-1366-light.png), [escritorio oscuro](../design/energy-experience-2-0-d/assisted/screenshots/draft-409-1366-dark.png). Son cuatro capturas adicionales a las 81 de la entrega inicial, todas ficticias.

## Propuesta de tiempo que requiere revisión

La recuperación manual del borrador anterior ya está corregida como presentación, sin alterar la firma. Queda por revisar cómo ofrecer tiempo suficiente antes y durante el vencimiento: aviso previo y control explícito que revalide propietario, fuente y estado vigente, presente diferencias y exija nueva confirmación. No ejecutar con token vencido ni reutilizar decisiones antiguas como autorización. No guardar originales antes de confirmar.

El mecanismo de ajuste/renovación del plazo **no se implementa** en este cierre: afecta a la política de seguridad y el usuario exige una propuesta revisada. No se prolongan tokens. **2.2.1: FAIL como gate de conformidad**, sin ajuste/aviso previo ni excepción de esencialidad demostrada. **3.3.7: recuperación manual corregida**; los valores quedan disponibles en el mismo formulario y se revalida la propuesta. Para las fuentes que cambiaron debe realizarse otra elección; no se supone que el índice anterior siga válido. No se afirma conformidad global de 3.3.7 ni se equipara la reelección de un archivo con teclear manualmente todos sus datos.

## Gate

**Cierre de accesibilidad BLOCKED**: Narrador y zoom nativo NOT TESTED por falta de confirmación/observación humana; ajuste de tiempo FAIL/pendiente de propuesta revisada. No solicitar autorización de merge/despliegue D como si esos gates estuvieran aprobados. La matriz distingue disponibilidad del entorno, escucha, zoom, rechazo seguro y recuperación del trabajo. Se ejecutaron focales afectadas, no la suite completa: no cambiaron rutas funcionales ajenas a la recuperación. C/NAS/flags permanecen intactos; PITR, Android/iOS físico y OFF externo siguen separados.
