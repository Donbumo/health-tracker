# Regla canónica: captura avanzada de carga

Aplica a series realizadas, perfiles de carga, import/export, Mobile Sync y companion.

1. `weight_kg` sigue siendo el total normalizado compatible. No cambia de significado.
2. El detalle opcional `load_details` versión `1.0` usa los nombres canónicos `load_mode`, `original_input`, `original_unit`, `components`, `normalized_total_kg`, `calculated_total_lb`, `display_total`, `bodyweight_kg`, `assistance` y `calculation_version`. Cada componente conserva su propio valor y unidad.
3. Toda conversión del backend usa `Decimal` y `1 lb = 0.45359237 kg`; el cálculo del navegador es solo preview.
4. Modos permitidos: `direct_total`, `per_side`, `bar_plus_per_side`, `machine_initial_total`, `machine_initial_per_side`, `machine_external_per_side_initial_total`, `selector_stack`, `dumbbell_each`, `bodyweight`, `bodyweight_plus`, `assistance` y `duration_distance`.
5. No inferir barra, peso corporal, carga inicial, lados, asistencia, unidad, duración o distancia. Cada componente requerido debe venir del usuario o archivo.
6. Asistencia se resta del peso corporal y nunca se registra como carga positiva. Sin peso corporal explícito no se puede calcular.
7. `duration_distance` conserva duración/distancia y usa carga normalizada cero; no representa resistencia.
8. Importadores deben recalcular el detalle y rechazar discrepancias con `weight_kg`, totales o warnings.
9. Sesiones antiguas sin detalle se interpretan como carga total histórica en kg, sin reescritura ni backfill.
10. Preferencias y perfiles son owner-only. El `user_id` viene del servidor; aliases resuelven a la identidad canónica del usuario.
11. Borradores, CSRF recovery e idempotencia deben incluir todos los campos de carga. Guardar sesión, perfil, preferencia, sync y eliminación del borrador es una sola transacción.
12. JSON y backup conservan el detalle; CSV/HTML muestran el total compatible y declaran cualquier pérdida. Restore remapea ownership.
13. Mobile Sync acepta el detalle de forma aditiva. Companion puede recibirlo en resultados; paquetes planeados declaran `advanced_load_details_in_planned_package=false` hasta existir contrato planeado probado.
14. La edición owner-only conserva el ID de sesión, la versión histórica del plan y los IDs de filas existentes; solo una modificación validada incrementa `revision`. CSRF recovery no escribe datos antes del reenvío válido.
15. Cualquier cambio requiere pruebas del calculador puro, ejemplos de máquinas, unidades mixtas, compatibilidad antigua, owner-only, schema, import/export/restore, drafts, edición e idempotencia.

Ver también [WORKOUT_LOAD_ENTRY.md](../WORKOUT_LOAD_ENTRY.md), [workout-session-recovery.md](workout-session-recovery.md), [mobile-sync.md](mobile-sync.md) y [companion-protocol.md](companion-protocol.md).
