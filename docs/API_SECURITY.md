# Seguridad de API v1

- CORS cerrado por defecto; `API_CORS_ORIGINS` es allowlist, sin cookies ni wildcard efectivo.
- `Cache-Control: no-store`, `nosniff`; 401 incluye `WWW-Authenticate`.
- JSON POST exige media type, 64 KiB y profundidad 12 por defecto.
- Rate limit cubre login, refresh y sesiones. Es memoria por proceso, no global entre workers, y solo es suficiente para QA privada/self-hosted. Un despliegue público requiere un backend compartido.
- La cookie web nunca autentica API; CSRF se exime porque el blueprint no confía en cookies.
- Logging allowlisted sin passwords, tokens, Authorization, cuerpos, email completo ni salud.

Claves por configuración y HTTPS obligatorio en despliegue real.
