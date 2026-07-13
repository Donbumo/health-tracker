# Regla canónica: backup integral

Aplica a creación, lectura, preview, restore y reconciliación de backups ZIP.

1. `schemas/full_backup_manifest.schema.json` y `docs/BACKUP_FORMAT_1_0.md` son el contrato 1.0.
2. El export de datos sigue siendo `user_data_export`; el ZIP solo agrega portabilidad binaria.
3. Ningún path, ID, MIME o nombre del ZIP concede autoridad ni define un path final.
4. Preview solo puede escribir staging privado; nunca dominios ni storage final.
5. Confirmación requiere login, CSRF y token firmado ligado a usuario, ZIP, manifest y ambos planes.
6. Datos se aplican mediante `AccountRestoreService`; no crear un segundo restore genérico.
7. Raw usa `UploadedFile`; generated usa `ExportRecord`; auditoría usa `ImportRun`.
8. `user_id` siempre proviene del servidor. Dedupe nunca cruza usuarios.
9. Verificar tamaño y SHA256 antes y después de copiar. No sobrescribir.
10. Un fallo anterior al commit debe hacer rollback DB y compensar archivos creados.
11. Runs pending se persisten antes de mutar. Failed debe sobrevivir al rollback.
12. Reconciliación es dry-run por defecto y no borra archivos finales huérfanos automáticamente.
13. No almacenar ZIP, manifest completo, payload, secretos, paths internos ni datos de salud en auditoría.
14. Raw restaurado no se ejecuta ni reparsea automáticamente.
15. Cifrado/password ZIP no se improvisa; queda unsupported en 1.0.
