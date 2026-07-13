# Regla canónica: API v1

1. `/api/v1` usa JSON estable, request ID y errores seguros.
2. Bearer es independiente de Flask-Login; nunca cookie/query como fallback.
3. Access corto firmado; refresh opaco hash-only, rotatorio y revocación de familia ante reuse.
4. Usuario efectivo viene del token y sesión persistida, nunca del payload.
5. ORM no se serializa directamente; usar allowlists e IDs públicos.
6. No registrar passwords, tokens, Authorization, bodies o salud.
7. CORS cerrado; sin wildcard/credenciales.
8. Fase 7A es read-only salvo auth/dispositivos. Sync e `Idempotency-Key` son Fase 7B.
9. Modelos requieren migración aditiva/reversible SQLite/MariaDB y single head.
10. Probar aislamiento, rotación/reuse, revocación, contratos, límites, migración y web.
11. Los IDs públicos de dominio son UUID persistidos y nunca se derivan de claves, email o IDs internos.
12. Rotar la clave invalida tokens firmados, no identidades públicas persistidas.
