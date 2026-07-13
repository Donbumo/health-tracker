# Dispositivos y sesiones API

`ApiDevice` pertenece a un usuario y usa UUID público. Plataformas: `android`, `ios`, `watch`, `unknown`. Cada login crea `ApiSession` y familia refresh; el mismo dispositivo actualiza metadata allowlisted. Revocar conserva historia y revoca sesiones.

`GET /api/v1/devices` nunca expone IDs internos, hashes o tokens. UUID ajeno responde 404. `last_seen_at` se actualiza con throttling.

Los IDs públicos son UUID persistidos: `User`, `TrainingPlan` y `TrainingPlanVersion` los generan en servidor; dispositivo conserva el UUID estable presentado por el cliente; sesión, familia y refresh ID se generan en servidor. Ninguno deriva de claves, email o IDs de base de datos.

```powershell
flask api-auth cleanup
flask api-auth cleanup --apply
```

Dry-run es predeterminado; `--apply` marca expirados y no borra historia.
