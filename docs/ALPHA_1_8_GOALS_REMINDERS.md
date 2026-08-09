# Alpha 1.8 — objetivos, recordatorios y adherencia

Alpha 1.8 añade objetivos personales no clínicos, reglas de recordatorio sincronizadas y notificaciones locales Android. El servidor es la autoridad de la configuración; Android es la autoridad del disparo local. No hay Firebase, push, correo, SMS, WhatsApp, IA ni alarmas exactas.

## Objetivos

Los tipos canónicos son sesiones o días activos por semana, pasos diarios, calorías/proteína/carbohidratos/grasas cuando existe el dato canónico, frecuencia de registro de peso, seguimiento de un plan activo y finalización de entrenamientos programados. No existen metas de peso, IMC, composición corporal o ritmo recomendado.

Cada `UserGoal` tiene UUID público, valor/unidad/periodo, días ISO aplicables, timezone IANA, intervalo de vigencia, estado `active|paused|completed|archived`, revisión optimista, procedencia y timestamps. Los objetivos de pasos y nutrición alimentan los targets ya expuestos por Salud; no se mantiene una segunda preferencia paralela.

## Recordatorios

`ReminderRule` admite entrenamiento próximo o pendiente, registrar peso/nutrición, revisar pasos, resumen semanal, sync pendiente y conflicto. Incluye hora local, días, anticipación, quiet hours, opciones 15/30/60 minutos o mañana, límite diario, cooldown, timezone, revisión y próxima ocurrencia. Importar una regla conserva su configuración pero la marca `requires_device_confirmation`; el dispositivo destino no la agenda hasta una confirmación local.

El backend expone CRUD owner-only Bearer bajo `/api/v1/mobile/goals` y `/api/v1/mobile/reminder-rules`, además de eventos técnicos y `/api/v1/mobile/adherence/{summary,timeline}`. Las mutaciones usan `Idempotency-Key`, UUID público y `base_revision`. El usuario efectivo siempre procede de la sesión Bearer.

## Planificador Android

El dominio separa `ReminderScheduler`, `ReminderPlanner`, `ReminderEvaluator`, `ReminderNotificationFactory`, `ReminderActionHandler` y `ReminderDeduplicator` de WorkManager y NotificationManager. Hay un work único por regla, otro work único por snooze y un ledger Room. Reboot, reemplazo de paquete, cambio de zona o reloj delegan una reprogramación corta a WorkManager; no hacen red ni disparan ocurrencias vencidas en masa.

La clave lógica es SHA-256 de `accountScope + rule UUID + fecha/hora local + tipo + UUID relacionado`. El horario repetido usa el primer offset; una hora inexistente avanza por la duración del salto DST, preservando los minutos. Un cambio de timezone recalcula el instante futuro sin cambiar una ocurrencia lógica ya registrada.

Quiet hours posponen al final de la ventana. Se aplican límite por regla/tipo, por canal, cooldown y tope global. Completar el entrenamiento relacionado, pausar el objetivo o desactivar la regla suprime el aviso pendiente. El snooze crea una ocurrencia hija; dismiss y acknowledgement no completan ni modifican datos de salud.

## Offline y Room

Room 8 añade `goals`, `reminder_rules`, `reminder_events`, `reminder_schedules`, `reminder_permission_state` y `adherence_cache`, todos con `accountScope` e identidad SHA-256 del servidor. La migración 7→8 es aditiva y la cadena 1/2/3/4/5/6/7→8 es explícita.

Crear/editar/pausar/archivar objetivos, editar/activar reglas, snooze y acknowledgement escriben primero en Room. La cola durable combina create→update, elimina create→delete y conserva sólo el último update. Logout elimina únicamente el scope confirmado y cancela sus works; cambiar de servidor produce otra identidad y no mezcla datos.

## UI y límites

Se conservan cinco pestañas. `Ajustes → Objetivos y recordatorios` contiene configuración, permiso contextual, prueba explícita y centro de eventos. Hoy muestra como máximo tres objetivos; Progreso muestra la caché de adherencia 7/30/90. El resumen semanal sólo se entrega si está habilitado y existen objetivos y datos.

Alpha 1.8 no promete entrega a una hora exacta: WorkManager es diferible y Android puede aplazar trabajo. No existe notificación clínica crítica, puntuación global, ranking ni recomendación. Quedan pendientes la ejecución física de las instrumentadas, validación de OEM/batería, reboot real, denegación de permiso y DST en un dispositivo.

Consulta [Privacidad de notificaciones](NOTIFICATION_PRIVACY.md) y [Métricas de adherencia](ADHERENCE_METRICS.md).
