# Privacidad de notificaciones

Las notificaciones Alpha 1.8 son locales y opcionales. No se envían por servicios de terceros y el servidor no conoce ni controla su entrega. Android 13 o posterior solicita `POST_NOTIFICATIONS` únicamente después de que el usuario intenta activar una regla y ve una explicación previa. Denegar el permiso conserva la configuración, no afecta login/sync y no provoca solicitudes repetidas; la pantalla ofrece acceso a los ajustes del sistema.

## Canales y bloqueo

Los IDs estables son `workouts_v1`, `daily_health_v1`, `summaries_v1` y `attention_required_v1`. Usan importancia razonable, sin vibración personalizada. El usuario puede ajustar cada canal desde Android.

La notificación principal usa visibilidad privada y una versión pública genérica. Los únicos cuerpos son equivalentes a:

- “Tienes un entrenamiento programado.”
- “Es momento de revisar tu registro diario.”
- “Hay un elemento que requiere atención.”
- “Tu resumen semanal está disponible.”

Nunca contienen peso, calorías, macros, alimentos, notas, ejercicio sensible, detalle de conflicto, URL del servidor ni identidad completa. La prueba manual usa el mismo contenido genérico y no crea evento o adherencia.

## Acciones y persistencia

Las acciones permitidas abren la app, posponen, marcan como revisado o descartan. No completan entrenamiento, registran salud, borran recursos, resuelven conflictos ni cambian objetivos. Los `PendingIntent` son immutable y sus extras sólo localizan un registro: el receiver no exportado vuelve a validar `accountScope`, identidad del servidor, evento y regla activa contra Room.

`ReminderEvent` y el ledger local guardan sólo tipo, instantes, estado, relación técnica, fingerprint/dedupe y código saneado. No persisten el texto completo. Los eventos disparados y permission state no se incluyen en `.htpack`; los eventos locales antiguos sólo se limpian mediante una acción explícita.

El diagnóstico se limita a conteos, tipo/canal/estado, timestamp truncado, código saneado y fingerprint corto. No registra payloads, valores de salud, tokens, URL privada, SSID, ubicación, contactos o calendario.
