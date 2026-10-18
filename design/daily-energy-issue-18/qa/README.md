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
