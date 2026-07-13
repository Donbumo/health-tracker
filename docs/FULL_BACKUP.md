# Backup integral y recuperación

Alpha 0.5 agrega un backup ZIP owner-only que combina el export JSON de cuenta con archivos raw y exports generados.

## Crear un backup

1. Abrir `/account/data`.
2. Elegir **Backup ZIP completo**.
3. Revisar conteos, bytes, faltantes y warnings.
4. Confirmar la generación.
5. Descargar desde el detalle o `/account/backups`.

La creación enumera únicamente registros del usuario autenticado, vuelve a calcular tamaño/SHA256, escribe el ZIP por chunks en un temporal, valida el ZIP recién creado, lo mueve atómicamente y registra un `ExportRecord` con `domain=account_backup`.

Un raw required faltante o corrupto bloquea. Un generated optional faltante o corrupto se omite con warning. Los backups anteriores no se empaquetan recursivamente.

## Restaurar

1. Abrir `/account/backups/restore`.
2. Subir un ZIP 1.0.
3. Revisar hashes, plan de datos y plan de archivos.
4. Confirmar explícitamente.
5. Descargar raw/generated desde el resultado o sus historiales.

El preview guarda únicamente el ZIP en staging privado; no escribe dominios ni storage final. El token firmado se liga a usuario, staging, SHA del ZIP, SHA del manifest, hash del plan de cuenta, hash del plan de archivos, modo, versión y expiración. La confirmación es de un solo uso en la sesión web.

La identidad del archivo se ignora. `user_id` efectivo siempre proviene de la sesión del servidor.

## Dedupe

- Datos: política `insert/update/skip/conflict/invalid` de `AccountRestoreService`.
- Raw: usuario destino + SHA256; mismo contenido con otro nombre produce skip.
- Generated: usuario destino + SHA256 + formato; produce skip.
- Usuarios distintos conservan registros y bytes independientes.

Activity y Route recuperan su `source_file_id` cuando el raw correspondiente y el registro de dominio pueden remapearse de forma segura. Un generated sin objeto fuente remapeable queda descargable con `source_id=null` y warning, nunca con un link roto.

## Qué no incluye

- Password hashes, contraseñas, sesiones o secretos.
- Archivos borrados/expired.
- Backups previos dentro de backups nuevos.
- Restore destructivo o replace de cuenta.
- ZIP cifrado.
- Storage externo o remoto.
