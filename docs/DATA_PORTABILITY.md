# Data portability

Alpha 1.0 añade de forma opcional `display_name` y `timezone` al objeto `user` del export 1.0 y restaura esas preferencias al usuario destino sin cambiar identidad, email, rol o credenciales. `/imports` sigue separado de export/restore/backup en `/account/data`.

Alpha 0.9 conserva de forma aditiva los detalles de carga de cada serie (`load_details` 1.0), la unidad preferida y los perfiles privados de carga por ejercicio. Restore recalcula/valida los totales, reescribe ownership al usuario destino y mantiene `weight_kg` como total normalizado. Sesiones anteriores sin este bloque siguen siendo válidas.

Documento corto para QA y handoff de portabilidad de datos.

## Qué existe

Health Tracker permite a un usuario autenticado:

- exportar sus datos en JSON desde `/account/export.json`;
- previsualizar un restore desde `/account/restore`;
- confirmar un restore merge seguro con token firmado;
- consultar auditoría saneada en `/imports/history`;
- usar los datos restaurados en pantallas normales: dashboard, peso, energía, nutrición, recetas, rutinas, sesiones, progreso y laboratorios.

## Qué incluye el export

El export completo usa `schemas/user_data_export.schema.json` e incluye, cuando existen:

- metadata básica del usuario sin password hash;
- uploads como metadata segura, sin binarios;
- productos de alimento;
- recetas;
- pesajes;
- nutrición diaria;
- energía diaria;
- balances derivados;
- rutinas y versiones;
- sesiones de entrenamiento;
- reportes de laboratorio.
- actividades importadas;
- rutas importadas.
- metadata allowlisted de exports generados, sin binarios ni paths internos.

## Qué no incluye

- `password_hash`;
- secretos;
- tokens;
- archivos binarios;
- rutas internas sensibles;
- datos de otros usuarios.

`export_records` usa `binary_included: false`. Restore lo marca `unsupported`: no recrea el archivo ni genera un link roto. El backup ZIP con binarios queda para Alpha 0.5.

## Restore actual

El restore actual es un merge transaccional. No intenta que la cuenta destino quede idéntica por borrado; inserta, actualiza o salta registros según claves seguras por dominio. Las sesiones de entrenamiento se remapean a las nuevas rutinas/versiones restauradas para preservar la relación histórica.

`uploads` y `daily_balances` se omiten porque son metadata/derivados. Los balances se recalculan desde nutrición y energía.

## Cómo probar

1. Crear o usar una cuenta QA.
2. Poblarla con datos ficticios.
3. Descargar `/account/export.json`.
4. Crear otra cuenta QA.
5. Abrir `/account/restore`.
6. Subir el JSON exportado.
7. Revisar el plan.
8. Confirmar.
9. Abrir `/account/data` y `/imports/history`.
10. Verificar pantallas funcionales:
    - `/dashboard`
    - `/weigh-ins`
    - `/daily-energy`
    - `/daily-nutrition`
    - `/food-products`
    - `/recipes`
    - `/training-plans`
    - `/training-sessions`
    - `/progress`
    - `/medical/labs`
    - `/activities`
    - `/routes`
11. Repetir el mismo restore y confirmar que no duplica registros.

## Comparación semántica

Las pruebas de round-trip comparan el export original contra el export restaurado ignorando campos técnicos esperados:

- IDs internos;
- timestamps;
- hashes;
- usuario destino;
- auditoría de versiones;
- uploads;
- balances derivados.

Si aparece una diferencia en contenido de dominio, debe tratarse como bug.

## Backup integral Alpha 0.5

El pendiente histórico de binarios queda cubierto por el formato ZIP 1.0. `user_data_export` continúa siendo el contrato de datos; el backup agrega `manifest.json`, raw y generated con SHA256. El restore JSON independiente sigue tratando `uploads` y `export_records` como metadata unsupported, mientras `/account/backups/restore` coordina datos y archivos.

Ver [FULL_BACKUP.md](FULL_BACKUP.md) y [BACKUP_FORMAT_1_0.md](BACKUP_FORMAT_1_0.md).

## Fases futuras

- Cifrado de backup con infraestructura revisada, no criptografía propia.
- Política de retención/pruning de auditoría.
- Herramienta de comparación visual para QA.
- Restore selectivo por dominio.
- Sincronización espejo con borrado seguro, solo si se diseña explícitamente.
