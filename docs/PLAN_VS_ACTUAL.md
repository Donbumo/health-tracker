# Plan contra realidad

Alpha 2.0 vincula una actividad importada con un entrenamiento planeado sin convertir similitud en certeza.

## Vínculos

- Referencia fuerte: UUID verificable de un entrenamiento planeado del mismo usuario. Puede crear `strong_auto_link`.
- Sugerencia débil: cercanía de fecha y, cuando existen, duración y distancia. Produce `suggested_link`; requiere confirmar o rechazar.
- Manual: el usuario selecciona un plan propio. Las búsquedas owner-only nunca revelan planes de otra cuenta.
- Fuerza: solo se vincula automáticamente con referencia fuerte; no se transforman laps FIT genéricos en series de gimnasio.

La evidencia conserva score y diferencias descriptivas. Un rechazo queda registrado; candidatos posibles no se fusionan ni desaparecen silenciosamente.

## Comparación

Para ciclismo, carrera y caminata se comparan duración, distancia cuando existe, intervalos planeados frente a detectados, laps y tiempo por lap. Potencia, frecuencia cardiaca y cadencia solo se comparan si el plan ya declara un objetivo y la fuente aporta la métrica. Porcentajes requieren denominador positivo; siempre se conserva diferencia absoluta.

Estados: `completed`, `partially_completed`, `deviated`, `insufficient_data` y `not_comparable`. Ejemplos permitidos: “45 de 60 minutos registrados”, “Faltan datos para comparar potencia” y “La actividad contiene cuatro laps”. Los snapshots guardan revisiones de plan y actividad para que el resultado sea auditable.

## Límites

El resultado es descriptivo. Alpha 2.0 no recomienda subir/bajar carga, FTP, recuperación, fatiga, estancamiento o riesgo, y no produce diagnóstico. Una actividad interrumpida, segmentos omitidos o datos insuficientes se muestran como tales en vez de inferirse.
