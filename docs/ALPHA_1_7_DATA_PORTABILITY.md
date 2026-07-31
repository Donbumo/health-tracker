# Alpha 1.7 — portabilidad selectiva de datos

Alpha 1.7 incorpora un flujo independiente del backup administrativo y de Mobile Sync para mover datos entre instalaciones de Health Tracker. El propietario se deriva siempre del Bearer token del servidor destino; el paquete no contiene ni puede elegir `user_id`.

## Arquitectura

El flujo auditable es:

1. Android guarda una solicitud owner-scoped en Room.
2. El backend serializa modelos de dominio a registros públicos, valida schemas y genera un `.htpack` privado con expiración.
3. Android descarga a `.partial`, calcula SHA-256 y sólo promueve el archivo a `.htpack` tras verificar tamaño y hash.
4. La selección SAF se inspecciona localmente sin importar nada.
5. El backend vuelve a validar ZIP, schemas y checksums, clasifica cada registro y persiste un plan versionado.
6. Una confirmación explícita con `Idempotency-Key` aplica el plan en una transacción.
7. Las relaciones usan un mapa `source_public_uuid → destination_public_uuid`; nunca IDs internos.

Los modelos nuevos son `PortableArtifact`, `PortableExportJob`, `PortableImportJob`, `PortableImportDecision` y `PortableImportMapping`. La migración Alembic `20260730_0033` es aditiva y reversible. Android usa Room 7 con migración explícita 6→7 y conserva la cadena 1/2/3/4/5/6→7.

## API owner-only

- `POST/GET /api/v1/mobile/portability/exports`
- `GET/DELETE /api/v1/mobile/portability/exports/<uuid>`
- `GET /api/v1/mobile/portability/exports/<uuid>/download`
- `POST /api/v1/mobile/portability/imports/inspect`
- `POST/GET /api/v1/mobile/portability/imports`
- `GET/DELETE /api/v1/mobile/portability/imports/<uuid>`
- `POST /api/v1/mobile/portability/imports/<uuid>/apply`

Todas requieren Bearer. Crear export y aplicar import exigen `Idempotency-Key`; el backend conserva sólo su SHA-256. Un UUID ajeno se trata como no encontrado. La descarga usa MIME propio, `Content-Disposition`, `no-store` y `nosniff`.

Los artefactos vencen a las 24 horas por defecto. Los límites de tamaño, archivos, records, profundidad, strings, líneas JSON, attachments y ratio de compresión son configurables. El borrado y la expiración eliminan sólo el artefacto temporal del owner, nunca los datos fuente.

## Exportación

Se pueden elegir preferencias, ejercicios, planes/versiones, workouts, programaciones, sesiones, ejercicios realizados, series, cuerpo, nutrición, alimentos, pasos y procedencia externa saneada. Perfil identificable y attachments están apagados y requieren opt-in independiente. El rango temporal se aplica a programaciones, sesiones, cuerpo, nutrición y pasos.

La salida usa UUID públicos, UTC ISO 8601, decimales como strings sin pérdida innecesaria, unidades canónicas, JSON determinista, LF y nombres ASCII. No serializa ORM ni cachés derivadas.

Health Connect conserva sólo una procedencia genérica, por ejemplo `health_connect`; no salen record IDs, data origins completos, permisos, ledger ni changes tokens. BLE puede quedar como `external_measurement` en un registro canónico ya existente, pero no salen captura, MAC, asociación, GATT, manufacturer data ni evidencia experimental.

## Inspección, dry-run y conflictos

La inspección es read-only. Comprueba estructura, límites, schemas embebidos, checksums, conteos y referencias antes de crear un plan. El preview clasifica `new`, `same_record`, `compatible_update`, `conflict`, `foreign_collision`, `duplicate_candidate` y `broken_reference`.

Las estrategias son `skip_existing`, `import_as_new`, `use_destination`, `update_when_identical_lineage` y `require_manual_resolution`. No existe “reemplazar todo”, no se elimina contenido destino y no se sobrescriben silenciosamente notas, sesiones, medidas, alimentos, programaciones ni overrides.

Un UUID libre se conserva. Una colisión con otro owner se reporta sólo como `foreign_collision`, recibe UUID nuevo y remapea referencias sin revelar la cuenta externa. El mismo paquete ya aplicado al mismo owner se planifica como registros iguales y una repetición produce cero duplicados.

## Atomicidad y recuperación

Antes de aplicar se recalculan hash y tamaño del paquete, se repite la inspección completa y se exige la revisión vigente del plan. La importación usa una transacción completa dentro de los límites Alpha 1.7. Los attachments se materializan con nombre temporal y se compensan si ocurre rollback. Un fallo deja el job en `rolled_back` con código saneado y conserva temporalmente el paquete para diagnóstico sin registrar contenido.

## Android

`Ajustes → Datos y privacidad` reúne selector de secciones, rango, consentimientos, solicitudes recientes, descargas verificadas, guardado SAF, share por FileProvider, inspección local, upload, simulación, decisiones y confirmación. No se añadió pestaña.

Las solicitudes offline quedan durables y WorkManager las reintenta al recuperar red. Un doble toque equivalente reutiliza la solicitud local pendiente. El permiso URI persistible permite reanudar tras process death; si deja de existir, el usuario debe seleccionar de nuevo. ZIPs y parciales se guardan en archivos privados particionados por hash de `accountScope`, nunca dentro de Room ni en almacenamiento público. Logout limpia únicamente el ámbito local correspondiente.

## Herramientas de escritorio

`scripts/portability/` contiene:

- `inspect_htpack.py`: metadata e integridad; records sólo con `--show-records` y advertencia.
- `verify_htpack.py`: ZIP safety, límites, schemas y SHA-256 con exit code.
- `list_htpack.py`: secciones, conteos y metadata no sensible de attachments.
- `sanitize_htpack.py`: crea una salida nueva sin perfil, notas, attachments ni procedencia externa y recalcula el paquete.

No confían en la extensión y nunca sobrescriben el original al sanear.

## Limitaciones Alpha 1.7

- SHA-256 demuestra integridad, no autenticidad. No hay firma criptográfica ni cifrado del paquete.
- La generación backend es síncrona y acotada; los estados permiten evolución posterior a jobs asíncronos.
- No hay nube, borrado de cuenta, sync servidor-servidor ni import directo desde la selección SAF.
- Historial/progreso recalculables, workout packages, deliveries y ledgers técnicos no se transportan.
- QA físico, instrumentadas ejecutadas y validación de distribución siguen siendo gates separados.

Consulta [Formato portable v1](PORTABLE_PACKAGE_FORMAT_V1.md) y [Privacidad de exportación](DATA_EXPORT_PRIVACY.md).
