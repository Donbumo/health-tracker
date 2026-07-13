# Storage e integridad de exports

Los artefactos viven bajo el storage generated gestionado:

```text
uploads/generated/exports/user_<id>/<uuid>.<ext>
```

`ExportRecord.relative_path` siempre es relativo. El nombre interno aleatorio se separa del nombre de descarga sanitizado.

## Escritura

1. Render en memoria con límite de 25 MiB.
2. Escritura a temporal exclusivo.
3. `flush` y reemplazo atómico.
4. Cálculo de SHA256 y tamaño.
5. Registro DB después del archivo completo.
6. Si falla DB o render, se limpian temporal y archivo final.

## Descarga

La descarga exige owner, estado `ready`, path resuelto dentro del root generated, archivo regular, tamaño correcto y SHA256 correcto. Se envía como attachment con media type allowlisted, `X-Content-Type-Options: nosniff` y cache privada desactivada.

No se guardan paths absolutos, payloads clínicos, trazas, tokens ni secretos en `ExportRecord`. Los warnings se truncan y limitan.

## Retención

`expires_at` es opcional. El borrado explícito elimina el binario y marca `deleted`; no borra datos de dominio. La metadata allowlisted puede aparecer en el export completo de cuenta con `binary_included: false`; account restore la trata como `unsupported` y no crea links rotos.

## Backups y archivos restaurados

Los ZIP completos viven en `uploads/generated/backups/user_<id>/`. Generated restaurados viven en `uploads/generated/restored/user_<id>/`; raw restaurados usan paths internos nuevos bajo `uploads/raw/user_<id>/`. Todos se verifican por tamaño/SHA256 antes de descarga.

El ZIP se construye por chunks y no usa el límite de render en memoria de 25 MiB. El export JSON del interior sí se serializa como un único documento y conserva su límite defensivo de 10 MiB en lectura. Staging vive bajo `DATA_ROOT/staging/account_backups` y nunca es parte de Git.
