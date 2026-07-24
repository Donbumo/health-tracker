# Captura avanzada de carga — Alpha 0.9

Alpha 1.0 reorganiza visualmente la captura diaria, pero no cambia fórmulas, modos, perfiles ni el contrato `load_details` 1.0 descrito aquí.

La captura de sesiones permite registrar cómo se obtuvo la carga total sin perder compatibilidad con el historial. `weight_kg` continúa siendo el total normalizado usado por volumen, progreso y clientes antiguos. El bloque opcional `load_details` conserva el modo, unidades por componente, entrada original, totales y `calculation_version`.

## Modos

- Carga total y por lado.
- Barra más carga por lado.
- Máquina con carga inicial total o por lado.
- Máquina con carga externa por lado e inicial total.
- Pila selectora y mancuerna por mano.
- Peso corporal, peso corporal más carga y asistencia.
- Duración/distancia sin carga normalizada.

La conversión autoritativa ocurre en el backend con `Decimal`: `1 lb = 0.45359237 kg`. La UI muestra ambos totales; no inventa componentes faltantes.

Ejemplos ficticios cubiertos por pruebas:

- Prensa: `115 lb` por lado + `167 lb` inicial total = `397 lb` (`180.08 kg` almacenados; precisión completa conservada en el detalle).
- Press de hombro: `45 lb` externo por lado + `27 lb` inicial por lado = `144 lb` (`65.32 kg` almacenados).
- Remo T: `45 lb` añadido total + `37 lb` inicial total = `82 lb` (`37.19 kg` almacenados).

## Uso web

1. Abre una sesión desde una rutina o entrenamiento planeado.
2. Elige unidad preferida y, por serie, modo de carga.
3. Captura únicamente los componentes solicitados; el total kg/lb aparece en la tarjeta.
4. Usa ajustes rápidos o copia la primera carga a las demás series.
5. Marca “Recordar configuración” para guardar el perfil del ejercicio al confirmar la sesión.
6. Desde el detalle puedes editar una sesión propia; conserva su identidad y versión histórica del plan, incrementa la revisión solo cuando cambia el contenido y vuelve a validar todos los totales.

La última carga y el perfil aparecen como ayuda. Los campos se incluyen en borradores local/servidor y sobreviven recuperación CSRF. La preferencia y el perfil solo cambian si la sesión completa se confirma.

## Datos y compatibilidad

- `TrainingSet.load_details_json` es nullable; sesiones antiguas siguen funcionando.
- `ExerciseLoadProfile` es privado por usuario y se vincula a la identidad/aliases de ejercicio.
- El schema `completed_workout` acepta `load_details` opcional versión `1.0`.
- JSON, export de cuenta y restore conservan detalles/perfiles. CSV aplana componentes; HTML muestra total y modo.
- Mobile Sync conserva el bloque opcional. Android calcula los doce modos con `BigDecimal`, conserva la entrada original y envía el total normalizado; Companion no promete componentes avanzados en paquetes planeados todavía.

Consulta [WORKOUT_LOAD_MODES.md](WORKOUT_LOAD_MODES.md) y [WORKOUT_LOAD_CALCULATIONS.md](WORKOUT_LOAD_CALCULATIONS.md) para el contrato exacto.

No se incluye reloj, telemetría continua ni edición avanzada de cargas planeadas en este bloque. La captura Android está documentada en [ANDROID_COMPANION.md](ANDROID_COMPANION.md).
