# Nutrition 2.1 — revisión visual contra la dirección aprobada

Referencia conservada: [diseño aprobado 2.0](NUTRITION_INTELLIGENCE_2.md) y
`design/nutrition-intelligence-2/screenshots/`. Evidencia nueva: capturas de
Flask/Jinja real, sesión y fixtures ficticias, sin pantallas de producción.

| Dirección aprobada | Resultado 2.1 |
| --- | --- |
| Jerarquía clara, tarjetas, dark/light, acento lima | Se mantiene el shell Health Tracker, tipografía, contraste, bordes y acciones. |
| Nutrition Today legible | Se convierte en historia completa: fecha, calendario, recent/último, legacy y MealLog, con métricas del día. |
| Revisión explícita compacta | Se conservan pendientes e identidad/cantidad por ingrediente; original/cálculo separados, UUID/revisión en detalle secundario. |
| Parcial no parece déficit | Subtotales/estimaciones y estados visibles; balance sólo sobre días comparables. |
| Coverage no promete nutrición completa | Se mantiene el texto sobre disponibilidad de datos, sin objetivo de referencia. |
| Catálogo e identidad | Nombres reales, fuente/preparación, búsqueda bilingüe, filtros y resultados paginados; sin auto-match. |
| Foto no guarda directamente | Cámara/archivo → OCR local → datos editables → propuesta → confirmación; base 100 ml no se convierte a gramos. |
| Guardadas reutilizables | Biblioteca con planes, recetas y productos, revisión y consumos independientes. |

La inspección visual encontró y corrigió controles irrelevantes en el flujo de
etiqueta: se retiraron fecha/momento/solapamiento de consumo y la comparación de
ingredientes vacía. La etiqueta muestra primero identidad, base y valores
extraídos. La revisión compuesta muestra nombres/preparación de los alimentos;
los identificadores técnicos se pueden desplegar para comprobarlos.
Se amplió el selector de fecha mobile para mostrar el año completo; se
regeneraron las 252 combinaciones finales y se comprobó visualmente el resultado.

Los controles de valores y la evidencia original se expanden bajo demanda.
La revisión PDF conserva páginas/filas y muestra el texto OCR original. La
pantalla de resultados distingue productos, vínculos, planes y consumos: el
PDF de dieta termina en un plan, con dos vínculos y cero consumos.

## Capturas representativas

Ver [galería completa](../design/nutrition-intelligence-2-1/gallery.html).
Cada pantalla principal tiene 390/1366 y dark/light; las mobile también tienen
captura del viewport para evaluar el primer pliegue, no sólo una imagen larga.

- Historial con legacy/MealLog y hoy vacío.
- Dashboard semanal y mensual.
- Catálogo amplio con arroz blanco cocido.
- Carga PDF/cámara y revisión de PDF de dieta.
- Preparación compuesta con dos alimentos reales y cantidades.
- Etiqueta OCR con base/porción explícitas.
- Creación y edición firmada de producto privado.
- Meal Review con declaración/composición independientes.
- Biblioteca de planes y recetas.
- Resultados reales de PDF → plan y foto → producto.

Se revisan legibilidad, jerarquía, contexto de datos, controles, contenido del
primer pliegue y calidad de origen, además de overflow, tamaños y foco. Las
capturas no afirman smoke de una cámara física ni un dispositivo iOS/Android.

## Corrección final revisada

Gráficas de ingesta/gasto/balance y medias móviles visibles preceden al detalle
del día. Ejes y huecos se inspeccionaron en móvil y escritorio; se corrigió
superposición de etiquetas. La revisión se separa en cuatro etapas; composición
no expone a la vez todos los campos nutricionales. OFF muestra prefill pendiente
y carbohidratos ambiguos sin sumar. Biblioteca indica conteos y página; se
captura página 6 con registros más allá de 100. Retención muestra estado cerrado,
advertencia explícita y bloqueo de originales confirmados.

[Informe de las seis correcciones](NUTRITION_EXPERIENCE_2_1_FINAL_REVIEW.md).
