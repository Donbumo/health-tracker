# D — cierre asistido: Narrador, zoom nativo y TTL

Actualización operativa 24-10-2026: D integrada y desplegada por autorización explícita. [Cierre productivo A+B+C+D](ENERGY_EXPERIENCE_2_0_D_PRODUCTION.md). Los resultados y gates de accesibilidad de este informe conservan su alcance histórico; zoom/TTL son deuda conocida aceptada para ese despliegue, sin certificación WCAG ni cambios de seguridad.

Fecha: 23-10-2026, zona `America/Mexico_City`. Base revisada de PR #25: `061c460661f3daa922bceb50710b0d31a224044e`. Sin merge ni despliegue; C permanece como versión productiva. Esta entrega no certifica conformidad WCAG.

## Aislamiento y entorno

[Evidencia del entorno](../design/energy-experience-2-0-d/qa/assisted-environment.json). QA ficticia recreada mediante `scripts/energy/accessibility_qa_app.py`; el proceso imprime URL, PID y etiqueta. Listener verificado: **127.0.0.1:55229 → PID 32944**, Python 3.12, coincide con el PID impreso. No listener 0.0.0.0 ni NAS. SQLite/storage temporales con exactamente los dos usuarios QA del script; sin configuración ni credenciales personales.

Edge dedicado mediante Playwright `launch` + `newContext`, headful y sin perfil persistente solicitado: **155.0.4283.45**, PID **39824**. URL comprobada mediante el contexto: `http://127.0.0.1:55229/energy?date=2040-02-03&period=7`; título «Energía · 2040-02-03 · Health Tracker», etiqueta «QA ficticia D» y 2450 kcal. Ventana devuelta por el inventario: `MSEdge`, identificador 26612294. Las cifras son fixtures sintéticas.

Sistema: **Windows 11 Pro 25H2, build 26200.9711**; `EditionID=Professional`, `DisplayVersion=25H2` y compilación contrastada con la [tabla oficial de Microsoft](https://learn.microsoft.com/en-us/windows/release-health/windows11-release-information). La cadena histórica del registro `ProductName=Windows 10 Pro` se conserva literalmente como dato separado, sin usarla para identificar la versión. Binario instalado de Narrador: **10.0.26100.8972**. Estos datos identifican el entorno; no prueban que Narrador esté activo ni que algo haya sido oído.

El intento anterior del control nativo fue detenido porque no pudo determinar la URL con suficiente confianza. La protección sigue intacta: no se envían combinaciones Windows ni entradas ciegas. Se solicitó confirmación humana de la URL/ventana en primer plano y activación manual de Narrador. El usuario confirmó disponibilidad de Narrador con Edge y que puede escuchar; **eso no equivale a un resultado audible por caso**.

Tras corregir la recuperación, QA se reinició: **127.0.0.1:65440 → PID 32168**, PID/listener nuevamente verificados. La misma ventana Edge dedicada apunta ahora a `http://127.0.0.1:65440/energy?date=2040-02-03&period=7`. El puerto anterior se cerró. El usuario confirmó expresamente «Nueva QA visible y Narrador activo» para esta URL nueva. El agente no observó el proceso Narrador en su comprobación: la activación y la escucha se documentan sobre la confirmación humana, sin atribuirlas a observación automatizada. El seguimiento conserva la identificación de ambas ejecuciones; PID/puertos son evidencia puntual, no configuración fija.

## Matriz audible

Resultados detallados y base de observación en [matriz JSON](../design/energy-experience-2-0-d/qa/assisted-matrix.json). Sólo una confirmación humana específica puede convertir un caso audible en PASS. AX, axe, foco DOM o captura no lo sustituyen.

| Caso | Recorrido y esperado | Estado |
| --- | --- | --- |
| N01 | Título, encabezados y regiones de Energía; salto a main, sin navegación repetida obligatoria. | PASS humano: «título, encabezados, regiones y salto claros». |
| N02 | 1900-01-01: fecha/días/estados legibles; día/mes anterior no disponibles y sin activación. | PASS humano: «lectura clara y límites anteriores correctos». |
| N03 | 9998-12-31: día/mes siguiente no disponibles; lectura y regreso sin salir del intervalo. | PASS humano: «lectura y límites posteriores correctos». |
| N04 | Conocido 2450, cero 2040-01-31, ausencia 2041-01-01, parcial 2040-02-04 y conflicto/parcial de ingesta 2040-02-01 distinguibles al escuchar. | PASS humano, cinco subcasos: conocido, cero, ausencia, parcial y conflicto; ver respuestas literales en matriz JSON. |
| N05 | Nombre de gráfica, explicación y tabla equivalente con encabezados/valores/denominadores; sin anuncio duplicado que impida comprender. | PASS humano: «gráficas y tablas comprensibles». |
| N06 | Fuentes, decisiones, historial, filtros, páginas y nombre/acción de original protegido. | PASS humano: «fuentes, historial, filtros, páginas y original claros». |
| N07 | Error de fecha/filtro y campo manual inválido; anuncio, foco, vínculo de corrección y recuperación. | PASS humano tras repetición: error HTTP 400, enlace al campo y corrección HTTP 200 al paso 3; propuesta conservada confirmada por escucha. |
| N08 | Importación: original ficticio → fecha/métricas → operaciones → confirmación; anunciar paso, campos y unidades. | PASS humano, pasos 1–4; misma URL/archivo reconfirmados y cada avance HTTP 200 verificado en la pestaña QA. |
| N09 | Checkbox, confirmar/cancelar y regreso; cancelar sin escritura ni original guardado. | PASS humano: controles, estado y foco claros; cancelación y regreso claros. |
| N10 | Estado/error anunciado de forma comprensible y oportuna; escuchar tras navegación y validación. | PASS humano: anuncios oportunos y comprensibles para errores y pasos recorridos. Expiración real audible se registra por separado. |
| Z01 | Zoom **nativo de Edge 200%**, con menú/atajo humano; lectura, reflow y tablas. | BLOCKED: humano informó 200 %, pero la pestaña controlada conserva 1342×808 CSS px y DPR 1, igual que al 100 %. Sin corroboración suficiente; se conserva el bloqueo. |
| Z02 | A/B/C al 200%: Tab/Shift+Tab, foco visible, formulario completo y confirmación sin controles inaccesibles/tapados. | NOT TESTED |

La confirmación de primer plano y Narrador activo ya se recibió. Los resultados audibles se registran por caso según las respuestas humanas; los casos sin respuesta siguen NOT TESTED. La disponibilidad del lector no demuestra por sí sola el resultado de un recorrido.

[Cancelación HTTP observada](../design/energy-experience-2-0-d/qa/assisted-cancel-http.json): regreso al paso 1, selector vacío y proyecciones del canónico/fuentes/eventos sin cambios. La fuente QA propuesta sigue sin eventos. Esta observación HTTP no sustituye una auditoría directa de storage; las pruebas Flask focales existentes cubren ausencia de escrituras y originales antes de confirmar. Escucha de la cancelación confirmada PASS por el usuario en N09. [Repetición del avance manual](../design/energy-experience-2-0-d/qa/manual-correction-advance.json): la discrepancia inicial de paso 2/3 se resolvió al repetir HTTP 400 → enlace al campo → corrección HTTP 200 y confirmar el paso 3 por escucha humana.

## Zoom nativo: método de verificación

El usuario debe elegir 200% en el menú de Edge de **esta ventana QA**, sin cambiar escalado de Windows. Registrar el porcentaje confirmado, `devicePixelRatio`, anchura CSS y screenshot sin aplicar `setViewportSize`, `setPageScaleFactor`, CSS `zoom` ni redimensionado de texto como sustituto. Base inicial: ventana 1366×900, contenido 1342×808 CSS px, DPR 1. La mitad de anchura y DPR 2 son comprobación técnica complementaria; la lectura/foco siguen requiriendo al humano.

[Observación de zoom nativo](../design/energy-experience-2-0-d/qa/native-zoom.json): el usuario informó menú 200 % y lectura correcta; al medir inmediatamente, la ventana estaba minimizada y la pestaña seguía en 1342×808 CSS px, DPR 1, iguales a la base 100 %. Z01 permanece BLOCKED por discrepancia entre informe y observación técnica. Se volvió a mostrar la misma pestaña y se pidió el porcentaje exacto y el título de esa ventana. No se simula zoom ni se relaja el guard.

Guías oficiales: [accesibilidad/zoom de Edge](https://support.microsoft.com/es-es/accessibility/edge/accessibility-features-in-microsoft-edge), [comandos de Narrador](https://support.microsoft.com/es-es/accessibility/windows/narrator/appendix-b-narrator-keyboard-commands-and-touch-gestures). La tecla Narrador depende de la configuración del usuario. El agente no envía combinaciones de Windows a ventanas no verificadas.

## TTL de C

Prueba reproducible: `scripts/energy/accessibility_ttl_qa.py`, sólo URL loopback explícita y `qa.sqlite` dentro de una carpeta `QA-energy-D-*`. Antes de cualquier POST comprueba que existen exactamente las dos cuentas ficticias. Autenticación/CSRF reales; dos tokens genuinos del servidor, importación y decisiones, llevados a paso 4. Espera **903 segundos reales**; no simula reloj, no cambia TTL ni vuelve a firmar tokens. Snapshot SQLite read-only del dominio y metadata antes/después; tokens, originales, credenciales y hashes de snapshot no se publican.

[Resultado HTTP de caducidad](../design/energy-experience-2-0-d/qa/ttl-real-expiry.json): prueba **completada entre 16:03 y 16:18 de México, 903,02 segundos reales**, contra el comportamiento revisado inicial. Importación y decisiones devolvieron **409**, sin token nuevo automático, sin cambios de dominio ni metadata de archivos. Recuperación nueva: GET/preview 200, pero exigía reintroducir las decisiones y volver a elegir el archivo. El aviso estático del paso 4 fue escuchado y confirmado PASS en N08. Segunda prueba real, sólo de importación: [resultado y escucha](../design/energy-experience-2-0-d/qa/ttl-audible-expiry.json), preparada 17:32:15 y enviada 17:47:42 de México tras **927,556 segundos reales**, comprobados con reloj monotónico y de fecha. Flask devolvió **409**, no service worker; foco en el aviso, sin token nuevo y proyecciones HTTP del canónico/fuentes/eventos sin cambios. No se renovó ningún token ni se alteró TTL/reloj. El usuario confirmó PASS audible de caducidad, consecuencias y enlace de recuperación. Ese enlace devuelve HTTP 200, paso 1 y selector vacío; formulario recuperado y trabajo a repetir confirmados PASS por escucha humana. [Captura del error real](../design/energy-experience-2-0-d/assisted/screenshots/ttl-expired-import-observed.png), 1342×808 CSS px/DPR 1 observados, sin atribuir zoom nativo 200 %. Esta segunda observación HTTP no es una comparación SQL/storage: la primera prueba real conserva esa evidencia por separado.

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

Propuesta concreta para revisión, **sin implementar ni aprobar**:

1. Comunicar el plazo desde que empieza a aplicarse y anunciar un aviso a los 14 minutos. Ofrecer al menos 60 segundos para una acción explícita «Necesito más tiempo», accesible por teclado y lector, sin cambiar el foco inesperadamente.
2. Esa acción enviaría una solicitud con CSRF y sesión vigente. El servidor comprobaría propietario, firma todavía válida, propuesta y revisión actual. Sólo si siguen coincidiendo emitiría una propuesta nueva de 15 minutos; no escribiría datos energéticos ni originales, ni realizaría la confirmación final. El token anterior no ganaría vigencia. No habría renovación automática.
3. Permitir al menos diez extensiones explícitas bajo esas mismas comprobaciones. Es la vía de extensión descrita por [WCAG 2.2.1](https://www.w3.org/WAI/WCAG22/Understanding/timing-adjustable.html), que exige aviso, al menos 20 segundos para responder y al menos diez extensiones. La solución propuesta usa 60 segundos; estos parámetros requieren revisión de seguridad y accesibilidad.
4. Si el estado cambió o la firma ya venció, conservar el borrador manual escapado, mostrar diferencias, descartar elecciones de fuente obsoletas y exigir otra revisión y confirmación. Probar límites de tiempo, firma alterada, replay, ownership, CSRF, cambios concurrentes, diez extensiones y anuncios reales. La política actual de originales seguiría vigente: al expirar la importación debe volver a seleccionarse el archivo; cualquier alternativa de retención requiere revisión separada.

El mecanismo de ajuste/renovación del plazo **no se implementa** en este cierre: afecta a la política de seguridad y el usuario exige una propuesta revisada. No se prolongan tokens. **2.2.1: FAIL como gate de conformidad**, sin ajuste/aviso previo ni excepción de esencialidad demostrada. **3.3.7: recuperación manual corregida**; los valores quedan disponibles en el mismo formulario y se revalida la propuesta. Para las fuentes que cambiaron debe realizarse otra elección; no se supone que el índice anterior siga válido. No se afirma conformidad global de 3.3.7 ni se equipara la reelección de un archivo con teclear manualmente todos sus datos.

## Estado de esta actualización

El usuario pidió cerrar autónomamente sin más preguntas. Se conservan los resultados humanos obtenidos y los límites de observación; no se convierte el zoom no corroborado en PASS ni se implementa la propuesta de tiempo sin revisión. Esta actualización sólo modifica documentación y evidencia QA; el código funcional sigue en `c1fa86280d8ebd3ac68223a8568e6be286902cf7`, con los resultados focales de ese estado. No corresponde repetir suites por estos cambios documentales.

## Gate

**Cierre de accesibilidad BLOCKED**: N01–N10 PASS por informes humanos y avances QA focales. Z01 BLOCKED por discrepancia de zoom informado/medido; Z02 NOT TESTED. Expiración real y formulario recuperado PASS humanos. Ajuste de tiempo FAIL/pendiente de propuesta revisada. No solicitar autorización de merge/despliegue D como si esos gates estuvieran aprobados. La matriz distingue disponibilidad del entorno, escucha, zoom, rechazo seguro y recuperación del trabajo. Se ejecutaron focales afectadas, no la suite completa: no cambiaron rutas funcionales ajenas a la recuperación. C/NAS/flags permanecen intactos; PITR, Android/iOS físico y OFF externo siguen separados.
