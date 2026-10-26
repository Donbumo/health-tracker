# D — auditoría WCAG 2.2 A/AA de A+B+C

Actualización operativa 24-10-2026: D integrada y desplegada por autorización explícita. [Cierre productivo A+B+C+D](ENERGY_EXPERIENCE_2_0_D_PRODUCTION.md). Los resultados y gates de accesibilidad de este informe conservan su alcance histórico; zoom/TTL son deuda conocida aceptada para ese despliegue, sin certificación WCAG ni cambios de seguridad.

Alcance: Energía autenticada, navegación compartida en esas páginas, gráficas/calendario A, fuentes/historial/originales B, importación/decisiones C y errores. No es auditoría de todo Health Tracker ni certificación. Referencia: [WCAG 2.2](https://www.w3.org/TR/WCAG22/). Criterios revisados a continuación; «observado» significa evidencia acotada en QA, no conformidad universal.

Métodos: Flask real con fixtures ficticias; Edge/Playwright; axe-core 4.14.0 (tags A/AA 2.0/2.1/2.2 y best-practice); Tab/Shift+Tab/Enter/Space/flechas; árbol AX CDP; medición sRGB y objetivos; screenshots inspeccionados; reflow y espaciado. JUnit y JSON en [evidencia](../design/energy-experience-2-0-d/README.md). Las incidencias `incomplete` de contraste sobre controles nativos se conservan en JSON; no se cuentan como fallos ni se omiten. Se revisaron capturas y los colores de superficies/controles en ambos temas.

| Criterio | Estado y evidencia/límite |
| --- | --- |
| 1.1.1 | Observado: SVG con nombre/descripción y tabla de datos, símbolos con texto; verificar anuncio con lector real. |
| 1.2.1–1.2.5 | No aplica: no hay medios audio/vídeo en este alcance. |
| 1.3.1 | Corregida definición dt/dd; headings, labels, ol de pasos, caption/th scope/td. AX inspeccionado; navegación real de tabla con lector pendiente. |
| 1.3.2 | Observado: DOM en orden de lectura y Tab sin tabindex positivo; rejillas responsive conservan orden. |
| 1.3.3 | Observado: las instrucciones nombran campos/operaciones; no exigen reconocer sólo posición o color. |
| 1.3.4 | Observado: sin bloqueo de orientación; layouts verticales/horizontales. No dispositivo físico. |
| 1.3.5 | No hay campos de datos personales de propósito normalizado en A/B/C; revisión de autenticación compartida limitada al login QA. |
| 1.4.1 | Observado: conocido/cero/parcial/conflicto/hueco tienen texto/símbolo, tablas y denominadores, no sólo color. |
| 1.4.2 | No aplica: no hay audio automático. |
| 1.4.3 | Corregidos botones oscuros; sRGB + axe + inspección. Texto principal, secundario y warning superan 4,5:1 en superficies medidas. Controles nativos requieren contraste según SO/tema real. |
| 1.4.4 | Evidencia parcial: layout equivalente al 200% + tamaño raíz 200%; pendiente zoom nativo combinado con lector real. |
| 1.4.5 | Observado: texto HTML/SVG, no capturas de texto como controles. |
| 1.4.10 | Observado: reflow a 320 CSS px, no overflow global; tabla bidimensional en wrapper. Ver [criterio de reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html). |
| 1.4.11 | Corregidos bordes de inputs y foco; barras, medias, estados y selección contrastados ≥3:1 en superficies medidas; captura adicional en colores forzados. |
| 1.4.12 | Observado: line-height 1,5; párrafos 2em; letras .12em; palabras .16em, en A/B/C a 320/390/1366, ambos temas; no overflow de página. |
| 1.4.13 | No hay tooltip personalizado dependiente de hover/foco. Titles nativos SVG quedan como complemento; datos íntegros en tabla. |
| 2.1.1 | Observado: fechas/selects, menú, pasos, errores, confirmación, cancelar, filtros y tabla con teclado; archivos mediante input nativo y fixture QA. Selector de archivo del SO/lector pendiente. |
| 2.1.2 | Observado: ciclo Tab completo, Shift+Tab, menú reversible, salida de tabla; sin modal que atrape foco. |
| 2.1.4 | No aplica: sin atajos de una sola letra. |
| 2.2.1 | **FAIL del gate de conformidad**: sin ajuste/aviso próximo al vencimiento ni esencialidad demostrada. Espera real 903,02 s → 409 sin escritura; se conserva ahora el borrador manual. No se modifica TTL. [Resultado y propuesta](ENERGY_EXPERIENCE_2_0_D_ASSISTED_CLOSEOUT.md). |
| 2.2.2 | Observado: no carruseles, autoactualización ni movimiento de datos; smooth scroll respeta reduced-motion. |
| 2.3.1 | Observado: sin contenido intermitente. |
| 2.4.1 | Observado: «Saltar al contenido» recibe primer Tab y Enter enfoca main; nav y secciones identificadas. |
| 2.4.2 | Mejorado: títulos con fecha, paso o página; títulos propios de error. |
| 2.4.3 | Observado: foco visible/ordenado, error recibe foco sin DML; enlace lleva al campo; step POST vuelve a documento con título específico. |
| 2.4.4 | Observado: enlaces nombran destino, original, fecha o fuente. Flechas con nombre accesible. |
| 2.4.5 | Observado: menú global, enlaces entre A/B/C, calendario y listado/historial; no ruta aislada. |
| 2.4.6 | Observado: encabezados, labels visibles por métrica, campo manual y operación, filtros y confirmación. |
| 2.4.7 | Corregido: contorno 3px contrastado, también navegación compartida al abrir Energía; teclado y capturas. |
| 2.4.11 | Observado en recorridos QA: foco en viewport, scroll-margin para topbar y errores enfocados. Validación adicional con zoom nativo/lector pendiente. |
| 2.5.1 | Observado: gestos simples; alternativas HTML a gráficas. |
| 2.5.2 | Observado por inspección: enlaces, botones y submit nativos, sin ejecución de dominio en pointerdown. Preview no escribe. |
| 2.5.3 | Observado: nombres accesibles contienen etiquetas visibles; flechas y menú tienen nombres explícitos. |
| 2.5.4 | No aplica: no sensores ni activación por movimiento. |
| 2.5.7 | No aplica: no arrastre obligatorio. |
| 2.5.8 | Observado: targets de resumen ≥24×24; flechas 44×44, campos/botones ≥44 alto. Días a 320 px pueden ser menores de 44 de ancho, pero >24 y 50 alto; no se afirma target mejorado AAA. Checkbox 22px dentro de etiqueta completa pulsable; confirmación probada con Space. |
| 3.1.1 | Observado: documento lang=es. |
| 3.1.2 | Fuentes y notas pueden contener nombres externos aportados por usuario, sin traducciones falsas. No se verifica pronunciación de todo contenido dinámico con lector real. |
| 3.2.1 | Observado: foco no aplica decisiones ni cambia de fecha automáticamente. |
| 3.2.2 | Observado: consultar/continuar/confirmar explícitos; selects no autoenvían; checkbox solo prepara confirmación. |
| 3.2.3 | Observado: menú compartido consistente en A/B/C. |
| 3.2.4 | Observado: mismas etiquetas/acciones para Energía, fuentes, historial, revisión y cancelar. |
| 3.2.6 | Observado: ayuda/cuenta compartidas mantienen ubicación; no se introduce widget de soporte en D. |
| 3.3.1 | Mejorado: errores A/B con recuperación y error C asociado a campo, foco y estado; validaciones servidor conservadas. |
| 3.3.2 | Observado: intervalo de fechas, unidades, desconocido≠cero, vaciado explícito, límites del archivo, preview y firma temporal explicados. |
| 3.3.3 | Mejorado: sugerencia y vínculo de corrección; valores válidos/draft C preservados. Fuente inválida sigue exigiendo seleccionar operación disponible. |
| 3.3.4 | Observado: preview → operaciones → confirmación explícita; no escribe hasta POST confirmado, CSRF/owner/replay/409/rollback en regresión. |
| 3.3.7 | Flujo normal sin reentrada; corregida recuperación manual tras 409: valores escapados disponibles en el formulario, sin firma automática, nueva revisión explícita. Fuente por índice exige otra elección si la revisión no es utilizable; importación exige reelección del original. Sin afirmación global: [alcance/limitaciones](ENERGY_EXPERIENCE_2_0_D_ASSISTED_CLOSEOUT.md). |
| 3.3.8 | Inspección de alcance: login nativo sin CAPTCHA ni bloqueo de pegado; password manager/lector/autenticación accesible real pendientes, no se certifican. |
| 4.1.2 | Observado: nombres/roles/estados en AX, aria-current paso/fecha, disabled real sin href en límites, validación asociada. Lector real pendiente. |
| 4.1.3 | Observado estructuralmente: status atómico y error role=alert con foco; títulos/pasos identifican cambios de documento. [Mensajes de estado](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html). No se afirma que AX demuestre anuncios audibles. |

4.1.1 no forma parte de WCAG 2.2; se corrigió igualmente la estructura de la lista de definiciones. Esta matriz cubre los 55 criterios A/AA mediante agrupaciones de los medios no aplicables.

## Prueba asistida y gate

El usuario confirmó **Narrador de Windows con Edge**, la QA actual en primer plano y el lector activo. N01–N10 tienen PASS específicos por escucha humana; el avance N07 se repitió y corroboró. Zoom nativo Z01 BLOCKED por discrepancia entre menú 200 % informado y medición inalterada respecto al 100 %; Z02 pendiente. [Cierre asistido, entorno y TTL](ENERGY_EXPERIENCE_2_0_D_ASSISTED_CLOSEOUT.md) conserva las respuestas por caso. La confirmación de disponibilidad no se usa para aprobar otros recorridos. El árbol AX es evidencia semántica, no simulación de un lector.

Completados los casos N01–N10 con Narrador y Edge y la escucha de expiración/recuperación. Antes de cerrar conformidad quedan el zoom nativo 200 % corroborado, su recorrido completo por teclado/formularios y la revisión del ajuste de tiempo. Los tags de axe no equivalen a cobertura total. D permanece BLOCKED, en PR sin merge ni despliegue.
