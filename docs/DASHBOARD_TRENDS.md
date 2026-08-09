# Resumen longitudinal web

## Resumen y Hoy

La web separa dos trabajos:

- `/dashboard` es **Resumen**: lectura longitudinal, filtros, comparación, cobertura y tendencias.
- `/today` es **Hoy**: entrenamiento planeado, siguiente acción, borrador, captura rápida, estado diario, actividad reciente y operación de la cuenta.

`/dashboard` sigue siendo la URL principal después del login. Un enlace legado con `?date=AAAA-MM-DD` redirige a la misma fecha en `/today`; no cambia ninguna ruta de `/api/v1`, Mobile Sync o Companion.

## Periodos y zona horaria

Resumen acepta filtros GET:

- `preset=today`, `7d`, `30d` o `90d`;
- `preset=this-month`, `previous-month` o `this-year`;
- `from=AAAA-MM-DD&to=AAAA-MM-DD` para un rango personalizado;
- `compare=previous` para añadir el periodo inmediatamente anterior con el mismo número de días.

Las fechas son locales, inclusivas y usan exclusivamente la zona IANA guardada en la cuenta, o `APP_TIMEZONE` cuando el usuario no tiene una preferencia. Los límites de timestamps se convierten a un intervalo UTC semiabierto; esto conserva días de 23 o 25 horas durante cambios DST. Un rango no puede superar 366 días. Fechas parciales, invertidas, inválidas o comparaciones desconocidas devuelven la página con un error humano y no ejecutan un rango abierto.

## Definiciones

### Energía

- **Ingesta**: `DailyNutrition.calories` por fecha.
- **Gasto**: `DailyEnergy.total_calories`. Si hay varias fuentes del mismo día, una corrección manual tiene prioridad; en otro caso se usa la fuente actualizada más recientemente. Las fuentes no se suman porque pueden solaparse.
- **Balance diario**: `calorías ingeridas − calorías gastadas`.
- **Balance acumulado**: suma de balances diarios solo en fechas con ambos valores.
- **Promedios**: usan únicamente días con el valor correspondiente; un día ausente no entra como cero.

El modelo conserva `source`, pero no una clasificación universal real/estimada. Resumen no inventa esa clasificación ni considera déficit o superávit como bueno o malo.

### Proteína

- Total y promedio usan `DailyNutrition.protein_g`.
- El objetivo usa únicamente un `UserGoal` activo, tipo `nutrition_protein`, unidad `g`, vigente y aplicable en esa fecha.
- Si coinciden varios objetivos, prevalece el actualizado más recientemente, igual que el read model existente de objetivos activos.
- **Balance de proteína**: proteína consumida menos objetivo, solo en días con ambos datos.
- **Cumplimiento**: consumo dividido entre objetivo, solo en días comparables.
- **Días en objetivo**: días comparables cuyo consumo alcanza o supera el objetivo.

El modelo conserva vigencia por fechas, pero no snapshots de cada cambio de estado. Un objetivo archivado o inexistente no se retroproyecta. Sin objetivo no hay balance, cumplimiento ni adherencia de proteína.

### Peso

- La fecha autoritativa es `WeighIn.recorded_at`, convertida a la zona de la cuenta.
- Se muestran exclusivamente puntos reales dentro del rango.
- Cambio es último menos primero y requiere al menos dos puntos.
- Promedio, mínimo y máximo usan los puntos reales.
- La media móvil de siete días usa pesajes reales de la ventana de calendario y aparece solo cuando contiene al menos dos puntos.
- Los valores se guardan en kg y se convierten una sola vez a la preferencia kg/lb para presentación.

No hay interpolación, relleno diario ni un objetivo de peso numérico en este resumen.

### Entrenamiento

- Las sesiones usan `TrainingSession.performed_at` en la zona de la cuenta y excluyen filas borradas.
- Los planes usan `PlannedWorkout.scheduled_for_date` y excluyen cancelados o borrados.
- Adherencia es planes completados dividido entre planes válidos del rango. Sin planes, queda ausente.
- Duración total y media usan únicamente sesiones que conservan duración.
- Días activos son fechas locales distintas con al menos una sesión.
- Hasta 31 días la serie agrupa por día; rangos mayores agrupan en bloques semanales acotados al periodo.

El volumen usa `weight_kg × reps`, convertido a la unidad preferida, únicamente para modos normalizados comparables: carga total, por lado, barra más lados, modos de máquina, selector y mancuernas. Si existe peso corporal, asistencia o duración/distancia, el volumen total del periodo queda no soportado y se explica; no se suman cargas incompatibles.

## Cobertura y datos ausentes

Resumen muestra días del periodo, días con ingesta, días con gasto, pesajes, sesiones y planes. Las series diarias conservan `null` cuando falta una medición. Cero solo aparece cuando es un conteo real o un valor registrado como cero.

La comparación calcula diferencia absoluta cuando ambos periodos tienen valor. El cambio relativo requiere un denominador anterior distinto de cero. Se omite para balances y porcentajes cuando una razón relativa sería engañosa.

## Gráficos, accesibilidad y privacidad

Los gráficos se generan con SVG y JavaScript del mismo repositorio; no hay CDN, trackers, analytics ni envío a terceros. Cuando se solicita comparación, las series actuales y anteriores aparecen tanto en el SVG como en las tablas alternativas. Los puntos tienen nombres accesibles y tooltip nativo. Cada gráfico incluye una tabla alternativa y mantiene el mensaje de datos ausentes. Si JavaScript no carga, las tablas y tarjetas siguen funcionando; si el JSON embebido es inválido, cada contenedor muestra un error legible sin romper el resto de la página.

El diseño usa las variables existentes de tema claro/oscuro, foco visible y controles táctiles. El SVG calcula un ancho interno entre 320 y 720 px y vuelve a renderizarse al cambiar el viewport; las etiquetas extremas se anclan al inicio y al final para evitar recortes. Las tablas desplazan dentro de su propio wrapper y no se oculta overflow global.

Todas las lecturas filtran por el `user_id` efectivo de la sesión. Los filtros no aceptan `user_id`, las respuestas de Resumen/Hoy usan `Cache-Control: private, no-store` y el JSON embebido se serializa con el escape HTML de Jinja. No existe endpoint nuevo: Android, Mobile Sync y Companion conservan sus contratos.

## Persistencia y rendimiento

No se añadió migración. La migración `20260717_0028` ya conserva zona horaria y unidad preferida en `users`; no existe una tabla separada `user_daily_preferences`. El preset, comparación, tarjetas visibles y media móvil no se persisten en esta fase.

Las consultas usan los índices owner+fecha existentes, un máximo de 366 días, eager loading acotado para series y un número estable de queries. No hay rollups, vistas materializadas ni caché compartida.
