# Métricas de adherencia

La adherencia Alpha 1.8 describe actividad observada frente a un objetivo explícito del usuario. No mide salud, no diagnostica, no atribuye causas, no crea recomendaciones y no combina dominios en una puntuación o ranking.

## Cálculo

Los rangos soportados son 7, 30 y 90 días, con comparación contra el periodo inmediatamente anterior. El cálculo carga en consultas acotadas objetivos, sesiones, programaciones, pasos, nutrición y pesajes del owner. Deduplica sesiones por UUID y convierte instantes en la timezone IANA del objetivo.

- Sesiones semanales: sesiones distintas en días aplicables frente al objetivo proporcional al rango.
- Días activos: fechas locales distintas con sesión.
- Programaciones: programaciones del periodo completadas frente a las existentes; si no hay ninguna, el denominador no es válido.
- Pasos: días aplicables con valor canónico disponible que alcanza el objetivo configurado.
- Nutrición: días con el campo canónico completo que alcanza el target explícito; un campo ausente no cuenta como completo.
- Peso: fechas locales con registro frente a frecuencia diaria, por días o semanal.
- Plan activo: sólo sesiones asociadas al UUID público del plan elegido.

La fecha efectiva nunca precede `start_date` y respeta `end_date` y días ISO. Los datos manuales e importados usan la resolución canónica ya existente. Un denominador cero produce `percentage: null` y “Sin datos suficientes”. El porcentaje se limita a 100; el conteo conserva logros adicionales.

## Estados y comparación

Los estados son `no_configured`, `insufficient_data`, `on_track`, `partially_complete`, `completed`, `missed` y `paused`. La respuesta incluye completado, esperado, porcentaje cuando aplica, cambio absoluto y cambio de porcentaje sólo si ambos denominadores son válidos.

Los textos usan formulaciones como “2 de 3; queda 1 en este periodo”, “Objetivo en pausa” o “Sin datos suficientes”. No usa “fallaste”, “mal”, “debes” o “incumpliste”. El rango es móvil según la fecha final y timezone seleccionadas; Alpha 1.8 no añade todavía una preferencia independiente de primer día de semana.

Android guarda el JSON de resumen como caché por cuenta, identidad de servidor y rango. La UI muestra Room primero, etiqueta cada dominio y conserva un fallback textual accesible offline. La caché, snapshots derivados y ledger no son portables: se recalculan desde objetivos y datos canónicos.
