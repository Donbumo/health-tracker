# Companion Workout Package 1.0

El package deriva de un `PlannedWorkout` y de la versión histórica exacta de su rutina. Es un snapshot JSON allowlisted; no serializa ORM ni contiene IDs internos.

Incluye UUID del package/delivery, planned workout, plan y versión; fecha/zona; ejercicios/sets; capacidades; campos omitidos; warnings y SHA256 canónico. El mismo delivery conserva bytes semánticos y hash estables. Un perfil o revisión diferente crea otra entrega.

Si el dispositivo no soporta un campo, el backend lo elimina solo del package y registra su path en `unsupported_fields`; nunca modifica el snapshot de `PlannedWorkout`. Si supera el límite negociado, responde `package_too_large`.
