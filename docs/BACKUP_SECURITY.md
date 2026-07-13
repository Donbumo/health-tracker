# Seguridad de backups

El ZIP se trata como entrada hostil aunque haya sido creado por Health Tracker.

## Controles antes de leer contenido

- límites comprimido, descomprimido, por entry, cantidad, profundidad y ratio;
- nombres relativos POSIX sin `..`, rutas absolutas, drive letters o barras invertidas;
- rechazo de symlinks, tipos especiales, cifrado, duplicados y case collisions;
- un solo manifest y un solo account export;
- política estricta sin entries no declaradas;
- tamaño y SHA256 exactos para cada entry;
- schema/version del manifest y schema del export de cuenta.

El MIME es metadata no confiable. No se ejecuta, parsea ni reimporta automáticamente un raw restaurado.

## Privacidad y autorización

- Login y CSRF son obligatorios en creación/preview/confirmación.
- Backups, raw y generated se consultan por `current_user.id`; IDs ajenos devuelven 404.
- El token firmado liga contenido y planes al usuario destino.
- El ZIP no viaja en hidden fields ni en `ImportRun`.
- Auditoría almacena hashes, conteos, bytes y estados allowlisted; no manifest completo ni datos clínicos.
- Nombres originales solo se conservan dentro del backup/registro del propietario y se sanean.

## Privacidad en reconciliación y orphan_details

El modo dry-run de `flask backup reconcile` puede mostrar `orphan_details` con metadata allowlisted de cada archivo huérfano. Solo se expone:

- `storage_kind` (`raw` o `generated`)
- `relative_path` relativo al storage root **si y solo si** el path contiene únicamente caracteres seguros (`[A-Za-z0-9_./ -]`); en caso contrario se sustituye por `path_fingerprint` SHA256 de la ruta relativa
- `size_bytes`
- `sha256` del contenido
- `modified_at` en UTC
- `probable_category` (heurística: `legacy_upload`, `legacy_generated`, `qa_artifact`, `unknown`)
- `matching_database_record` (siempre `false` para huérfanos)

**Nunca se expone:**
- Paths absolutos
- `original_filename`
- Contenido del archivo
- Datos clínicos, de salud o personales

El bloque de `orphan_details` solo aparece en dry-run. `--apply` nunca lo incluye y nunca borra archivos huérfanos finales.

## Amenazas cubiertas por pruebas

Traversal, rutas absolutas/Windows, duplicados, case collision, symlink, ratio inseguro, límites, manifest/account faltante, versión futura, kind desconocido, SHA/tamaño incorrecto, JSON inválido, token alterado/vencido/reutilizado, cambio de ZIP/plan, usuario cruzado, fallo parcial de archivos, fallo de auditoría y cleanup fallido.

Reconciliación: orphan raw, orphan generated, orden determinista, sin path absoluto, sin original_filename, sin contenido, archivo desaparecido durante scan, dry-run no modifica, --apply no elimina huérfanos finales, cero orphans conserva salida actual.

No se promete confidencialidad criptográfica del ZIP 1.0. El operador debe proteger transporte y disco con controles del sistema/VPN. Un diseño futuro de cifrado debe usar una biblioteca y administración de claves revisadas, no criptografía propia.
