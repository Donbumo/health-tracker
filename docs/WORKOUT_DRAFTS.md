# Borradores de sesiones

## Borrador local

La clave exacta es:

```text
health-tracker:v1:workout-draft:<user_public_id>:<training_plan_version_public_id>:<week>:<day>
```

Solo contiene campos del formulario, IDs públicos de contexto, versión, timestamps y `client_submission_id`. No contiene CSRF, cookies, Authorization, secretos ni HTML arbitrario. El cliente valida estructura, tamaño, expiración y JSON antes de restaurar; entre local y servidor elige el borrador con `updated_at` más reciente.

## Borrador servidor

`WorkoutSessionDraft` es owner-only y usa UUID público. Sus endpoints privados autenticados son:

- `POST /workout-session-drafts`
- `GET /workout-session-drafts/<public_id>`
- `PATCH /workout-session-drafts/<public_id>`
- `DELETE /workout-session-drafts/<public_id>`

Las mutaciones exigen CSRF. El payload se normaliza con allowlist, tiene tamaño limitado y se guarda junto con SHA256 y revisión. Acceso ajeno responde 404. El borrador servidor se elimina en la misma transacción que crea la sesión; no se elimina cuando el guardado falla.

## Mantenimiento

```powershell
flask workout-drafts cleanup
flask workout-drafts cleanup --apply
```

El primer comando es dry-run. `--apply` elimina únicamente expirados, inválidos u asociados a una submission ya completada. Los borradores activos antiguos se reportan pero no se borran.

