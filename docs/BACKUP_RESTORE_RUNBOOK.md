# Runbook de backup y restore

## Operación normal

```powershell
docker compose up --build -d
docker compose exec web flask db upgrade
docker compose exec web flask db check
```

Crear, descargar y restaurar desde `/account/data`. No usar datos reales en QA; usar cuentas y fixtures ficticias.

## Punto de commit y compensación

1. El ZIP completo se valida en staging.
2. Se persiste un `ImportRun` pending en una transacción independiente.
3. `AccountRestoreService.apply_in_transaction` aplica datos sin commit propio.
4. Los binarios se extraen por chunks a staging y se verifican.
5. Se crean rows destino con paths nuevos.
6. Los archivos staging se mueven a sus paths finales sin sobrescribir.
7. La auditoría se finaliza `succeeded` y DB se confirma en el mismo commit.
8. Se limpia staging.

Si falla antes del commit DB, se hace rollback y se eliminan únicamente archivos finales creados por ese intento. El `ImportRun` se registra `failed` desde una sesión limpia. Si falla el cleanup posterior, el restore sigue succeeded, `cleanup_status=failed` queda en metadata allowlisted y reconciliación puede retirar staging obsoleto.

Existe una ventana de crash entre mover archivos y confirmar DB. No se oculta: el reconciliador reporta archivos huérfanos y runs pending abandonados. Los huérfanos finales solo se reportan; no se borran automáticamente.

## Archivos huérfanos finales

Un archivo final huérfano es un archivo presente en `UPLOAD_ROOT` o `GENERATED_UPLOAD_ROOT` para el que no existe ningún registro de base de datos coincidente.

**Causas típicas:**

- Ventana de crash entre mover el archivo a su path final y confirmar la transacción de DB.
- Archivos preexistentes de instalaciones anteriores (legado).
- Artefactos de QA no registrados.

**Política:**

- Los archivos finales huérfanos **solo se reportan**; nunca se eliminan automáticamente.
- `--apply` no borra archivos huérfanos finales; solo repara estados de DB y staging obsoleto.
- Investigar cada huérfano reportado antes de decidir borrarlo manualmente.

**Identificación en dry-run:**

El comando `flask backup reconcile` (sin `--apply`) muestra un bloque por cada huérfano con:
- `storage_kind`: `raw` (UPLOAD_ROOT) o `generated` (GENERATED_UPLOAD_ROOT)
- `relative_path` (si el nombre es seguro) o `path_fingerprint` SHA256 (si contiene caracteres de usuario)
- `size_bytes`, `sha256`, `modified_at` en UTC
- `probable_category`: `legacy_upload`, `legacy_generated`, `qa_artifact` o `unknown`
- `matching_database_record`: siempre `false` para huérfanos

**No se imprime:**
- Paths absolutos
- `original_filename`
- Contenido del archivo
- Datos clínicos o de salud

## Reconciliación

Dry-run por defecto:

```powershell
docker compose exec web flask backup reconcile
```

Aplicar reparaciones seguras:

```powershell
docker compose exec web flask backup reconcile --apply
```

`--apply` puede marcar rows missing/corrupt, marcar pending antiguos como failed y borrar staging antiguo. No borra archivos finales huérfanos ni datos de dominio. La salida son conteos sin nombres ni datos de salud.

El dry-run es el comportamiento predeterminado. Siempre ejecutarlo primero para revisar huérfanos antes de cualquier acción manual.

## Troubleshooting

- `required raw ... missing`: recuperar el archivo gestionado antes de crear backup.
- `integrity check failed`: no descargar/restaurar; revisar storage y ejecutar reconcile dry-run.
- `token expired/changed`: volver a subir y revisar el backup.
- `cleanup_status=failed`: ejecutar reconcile dry-run y después `--apply` si el staging es obsoleto.
- `unsupported backup format version`: usar un lector compatible; no editar el manifest manualmente.
- `orphan_files=N > 0`: ejecutar dry-run, revisar `orphan_details`, clasificar manualmente y borrar solo si está seguro.

Nunca usar `docker compose down -v` para resolver un problema de backup.
