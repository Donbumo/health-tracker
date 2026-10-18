# Evidencia P0 Energía diaria

Datos ficticios de QA (2040); ninguna captura pertenece a una cuenta real.

- `baseline-reproduction.json`: comportamiento de la base 0045 antes de modificar código, en MariaDB RC/RR.
- `mariadb-final.json`: proyección, concurrencia, revisión, rollback, idempotencia y móvil sobre QA local 0046.
- `sqlite-migration.json`: SQLite desde un fixture del schema 0045, db check y no-op; el test `test_energy_day_migration.py` conserva todas las columnas de duplicados de dos propietarios.
- `integrated-http.json`: Flask/Gunicorn real + MariaDB QA, CSRF, edición, revisión, export y confirmación de borrado.
- `ui-report.json`: 60 combinaciones de cinco pantallas, seis anchos y dos temas, sin overflow y con foco visible.
- `build-evidence.json`: imagen QA, arquitectura y hashes de fuentes; no se modificó la imagen productiva.

La primera ejecución MariaDB subió 0045 → 0046 y comprobó en memoria que no variaban los hashes de columnas anteriores de DailyEnergy, nutrición, recetas, snapshots y catálogo. Los reintentos posteriores del script reportan correctamente «already at head», sin repetir DDL ni reconstruir QA. Los fingerprints anteriores no se guardaron como un volcado de datos; la aserción está en el script reproducible.

Capturas finales: edición y conflicto móvil 390 en dark/light, confirmación móvil y detalle de escritorio 1366. La prueba visual también cubre 360, 430, 768 y 1024.

Reproducir con el venv y la instancia MariaDB QA existentes. `scripts/energy/qa_app.py` crea únicamente un SQLite temporal y reutiliza el puerto QA 8025; `ui_qa.cjs` usa Playwright existente. Los scripts MariaDB corren dentro de la imagen QA, red local existente, con el archivo privado de conexión suministrado mediante `--env-file`; montar este directorio como `/evidence` y los scripts como sólo lectura. Verifican schema/usuario QA antes de escribir. El smoke HTTP requiere Gunicorn dentro del mismo contenedor, sin publicar un puerto nuevo.

No incluir archivos de conexión, dumps, tokens, reportes personales, perfiles del navegador ni logs de producción. El informe principal y el gate de recuperación están en `docs/DAILY_ENERGY_ISSUE_18.md`.

## Cierre de controles PR #21

`review-controls.json`: tres tests nuevos (JSON completo, ZIP completo, entrada 1.0), 154 focales PASS; cuenta con múltiples fuentes, contradicción/resolución, fuente y día eliminados, cuatro originales, móvil con revisiones/aliases, segunda importación y bloqueo del backup obsoleto. Ejecutados además con MariaDB RC/RR.

Recuperación real QA: 0045 completo, copia/checksum/restore, interrupción DDL con head aún 0045, recuperación hacia adelante en copia aislada, bloqueo DML, backup posterior a nuevas escrituras y restore de 80 tablas idénticas y originales. Imagen compatible guardada y recargada; fallo/reinicio Gunicorn con smoke HTTP de energía y Nutrition. Scripts `recovery_0046_qa.py`, `recovery_0046_qa.ps1` y `recovery_service_smoke.py`; procedimiento en `docs/ENERGY_0046_RECOVERY_RUNBOOK.md`. No se modificó la aplicación ni se repitió la suite completa; sin cambios UI, capturas anteriores vigentes. No se accedió a NAS ni producción.

Imagen, dumps, originales y manifests de tabla permanecen privados fuera del repositorio. El informe agregado sólo publica resultados y checksums de fixtures sintéticos/imagen. No acredita preflight, backup, permisos o PITR productivos: esos gates deben repetirse tras autorización.
