# Autenticación API

El access token se firma con `itsdangerous`/SHA-256, dura 15 minutos por defecto y contiene como subject el UUID público persistido del usuario, además de IDs públicos de sesión/dispositivo/familia, `iat`, `exp`, `iss`, `aud`, versión y `jti`; no contiene IDs internos de base de datos, email ni salud.

El refresh es opaco, aleatorio y solo se almacena como hash SHA-256 de un secreto de alta entropía. Cada uso lo rota; reutilizar uno usado revoca la familia. Expiración absoluta predeterminada: 30 días.

Config: `API_TOKEN_SIGNING_KEY` (recomendada), `API_TOKEN_ISSUER`, `API_TOKEN_AUDIENCE`, `API_ACCESS_TOKEN_SECONDS` y `API_REFRESH_TOKEN_DAYS`. La clave debe tener al menos 32 caracteres. Si falta, solo se reutiliza la `SECRET_KEY` ya validada con un salt exclusivo y se emite un warning explícito; producción puede exigir separación con `API_REQUIRE_SEPARATE_SIGNING_KEY=true`, que detiene el arranque si falta.

Para rotarla, configura una nueva `API_TOKEN_SIGNING_KEY` y reinicia todos los workers simultáneamente. Los access tokens anteriores quedan inválidos; los refresh tokens opacos y los UUID públicos persistidos de usuarios, dispositivos, sesiones, familias, rutinas y versiones no cambian. No se registran passwords, claves, tokens, `Authorization`, bodies ni emails completos. HTTPS es obligatorio fuera de desarrollo.

El consumo de refresh usa `SELECT ... FOR UPDATE` y un claim atómico `UPDATE ... WHERE used_at IS NULL AND revoked_at IS NULL`. Dos usos concurrentes producen como máximo un sucesor; el segundo se considera reuse y revoca la familia completa, incluido el access emitido por el ganador.
