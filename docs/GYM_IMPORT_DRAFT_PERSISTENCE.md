# Borradores persistentes de importación Gym

## Incidente y causa

El flujo anterior enviaba `RoutineImportDraft` en campos ocultos del formulario. Las selecciones de mapping se mantenían en JavaScript/HTML hasta volver a revisar. No existía un borrador Gym en DB ni una sesión server-side con esas decisiones.

`stage_source` creaba un original privado `.gym-preview-*.tmp`. `promote_source`, llamado por la confirmación, exigía que existiera y tuviera menos de una hora. Volver a revisar renovaba el token firmado del preview, pero no el mtime del original. Así podía existir un preview válido cuyo original ya había expirado. El rechazo sucedía antes de publicar la rutina y la página de error ya no incluía el borrador.

## Persistencia y contrato

Se reutilizan `RoutineImportDraft`, el parser determinístico, el resolver y la publicación oficial de programas/versiones. Se añade exclusivamente `GymImportDraft` / `gym_import_drafts`, migración `20260928_0043` desde `20260927_0042`.

Los modelos existentes no permiten reutilización sin alterar sus contratos: `WorkoutSessionDraft` exige una versión de rutina existente y describe una sesión; `ImportRun` es auditoría sanitizada, no almacenamiento de payloads; `PortableImportJob` pertenece a restores con artifacts/TTL; `AIActionDraft` pertenece a conversaciones AI. No se reutiliza ninguno para otro dominio.

El borrador guarda owner, UUID, contenido normalizado (programa, días, ejercicios, prescripciones, decisiones, warnings y pendientes), nombre/digest de fuente, tipo de fuente, target/base revision, revisión propia, estado y timestamps. No expira por tiempo ni por falta de actividad. `updated_at` cambia en cada guardado. Persiste hasta confirmación o cancelación explícita. No se añade limpieza automática por TTL.

Después de parsear no se guarda ni se necesita el archivo original. Los nuevos imports no crean staging, por lo que confirmar/cancelar no puede dejar nuevos archivos huérfanos. El SHA-256 queda como procedencia en la auditoría de confirmación. La política cambia solo en Gym; otros importadores conservan sus originales como antes. Los staging legacy anteriores a este hotfix no se recuperan ni eliminan automáticamente.

## Autosave y reanudación

- Cada selección se guarda inmediatamente mediante POST + CSRF. Incluye catálogo, identidad propia, nuevo y «Ninguno corresponde · usar mi nombre».
- Las selecciones son privadas del borrador; no crean identidades, aliases ni mappings personales hasta confirmar. Cancelar no cambia mappings existentes. «Ninguno corresponde» no borra un vínculo personal preexistente.
- Las correcciones del editor también se guardan automáticamente, admitiendo estados incompletos dentro de límites y allowlists. Un estado incompleto puede reabrirse pero no publicarse.
- Solo hay un guardado en vuelo. Se muestra Guardando/Guardado, hora y error visible. Un error bloquea más ediciones/confirmación hasta reintentar o recargar el estado guardado. Salir con un cambio pendiente genera aviso del navegador.
- Sin JavaScript, «Revisar mappings corregidos» guarda explícitamente. No se promete autosave sin JavaScript.
- Mi entrenamiento contiene «Continuar importación». Se reutilizan las pantallas existentes de preview y editor; las URLs GET permanentes permiten refresh/cerrar/reabrir sin repetir uploads.
- Los assets JS modificados cambian su versión de URL para evitar ejecutar copias viejas de la PWA.

## Confirmación, concurrencia y seguridad

Confirmar consume únicamente `draft_id`, revisión y decisión firmada; el contenido y target vienen de la DB y del owner autenticado. Se ignoran payloads/targets adicionales del cliente. La decisión está ligada a owner + UUID + revisión; su vigencia está limitada por el estado/revisión del borrador, sin depender del TTL de un upload.

El bloqueo del usuario y del borrador serializa save/cancel/confirm en MariaDB. Una revisión obsoleta devuelve 409 con «Este borrador cambió en otra pestaña. Recarga para continuar.» No sobrescribe lo guardado. El servicio existente verifica también la revisión de la rutina destino y valida el JSON estándar antes de publicar.

Programa, versión, mappings, auditoría y estado completed se escriben en una transacción. Una falla hace rollback y conserva el borrador. Un doble confirm o reintento después de perder la respuesta devuelve el programa ya creado, sin otra auditoría/versión. Se conserva un recibo pequeño del resultado; el payload de trabajo se vacía al completar/cancelar. Los borradores de trabajo no se incorporan al contrato público de exportación de rutinas; un backup completo de DB conserva la tabla.

Todos los accesos filtran `user_id` de la sesión. IDs ajenos dan 404. El cliente no decide owner, estado, timestamps, target ni revisión siguiente. Se conservan los límites del parser, CSRF y autenticación. No se guardan datos de borrador en cookies, logs ni localStorage.

## QA

`backend/tests/test_gym_import_drafts.py` cubre original físicamente ausente, draft envejecido 60 días, tres mappings antes de refresh/reopen, finalización de seis ejercicios, prescripciones, cancelación, selección none/new, cambios, edición incompleta, ownership/CSRF, allowlists, rollback, historial y target obsoleto. El gate opt-in MariaDB reutiliza `CATALOG_TEST_MARIADB=exercise_catalog_unit_qa`, únicamente en loopback:33379, e incluye carreras de autosave y confirmación.

QA visual: usar el servidor local ficticio `scripts/gym/mapping_qa_app.py` e importar un CSV ficticio con seis nombres desconocidos. Mapear tres, eliminar el archivo de fixture, recargar/cerrar/reabrir, continuar y confirmar. Verificar 390 × 844, errores de autosave y conservación de selecciones. Nunca guardar mappings personales reales durante QA.

Validación de esta entrega:

- Backend completo: 1119 PASS, 26 gates opcionales omitidos.
- MariaDB focal: 12 PASS, incluidas confirmación y guardado concurrentes. Upgrade 0042 → 0043, downgrade, nuevo upgrade y `db check` PASS en schema efímero.
- `node --test scripts/gym/test_draft_autosave.cjs`: 4 PASS; cubre bloqueo/reintento, revisión obsoleta y respuestas de sesión expirada o malformadas que nunca deben aparentar un guardado.
- QA visual local: tres selecciones guardadas, original borrado físicamente, draft envejecido 60 días, refresh/cierre/reapertura, seis ejercicios completados, corrección manual, conflicto entre pestañas y fallo de red con reintento. Confirmación y conservación del historial ficticio PASS.
- Anchos 360, 390, 430, 768, 1024 y 1366 sin overflow; móvil 390 × 844 PASS. Cancelación sin mappings personales PASS. Sin errores JavaScript en el recorrido normal; los fallos de red/409 fueron inducidos para QA.

## Recuperación del incidente y entrega

El servidor anterior no persistía las decisiones del mapping. El original de staging solo contiene el archivo subido, no las decisiones posteriores. No se usan logs para reconstruir datos. Una pestaña anterior que conserve su formulario podría contener una copia recuperable; debe inspeccionarse sin recargar ni confirmar y sin copiarla a Git. La existencia de una pestaña abierta por sí sola no demuestra recuperación.

En esta sesión no fue posible acceder a Edge. Por tanto, la recuperación desde el navegador no está confirmada; se debe conservar abierta la pestaña original sin recargar. No se modificó producción ni se reconstruyeron datos reales.

Entrega: commit y push de `fix/gym-import-draft-persistence`, sin merge ni despliegue. La nueva migración requiere revisión y autorización posterior antes de aplicarse en producción.
