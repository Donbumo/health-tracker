# Planned workouts

Alpha 1.0 añade filtros server-side por rango y estado en `/planned-workouts`, usa la zona horaria preferida al crear y mantiene los snapshots/revisiones existentes. No añade un calendario gráfico ni cambia el contrato de sincronización.

Alpha 0.8.1 permite iniciar la captura web desde un planned workout mediante su UUID público. La sesión, el estado `completed`, el cambio de Mobile Sync y la eliminación del borrador servidor se confirman juntos. Un planned workout ya completado rechaza otra submission distinta con conflicto seguro.

`PlannedWorkout` congela un día de una `TrainingPlanVersion` para una fecha y zona horaria IANA. El snapshot no se modifica cuando se activa otra versión de la rutina.

Estados permitidos: `planned`, `in_progress`, `completed`, `skipped` y `cancelled`. Toda mutación incrementa `revision`; una revisión base antigua produce conflicto. Un delete móvil crea tombstone y no elimina físicamente el registro.

Rutas API:

- `GET|POST /api/v1/planned-workouts`
- `GET|PATCH /api/v1/planned-workouts/<uuid>`
- `POST .../<uuid>/start`, `/skip` y `/cancel`

La UI web owner-only está disponible en `/planned-workouts`. Sus formularios usan POST y CSRF. La sesión completada queda vinculada al planned workout y a la versión histórica exacta.
