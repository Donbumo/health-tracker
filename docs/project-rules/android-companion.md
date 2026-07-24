# Regla canónica: Android Companion

1. Android consume `/api/v1`, Mobile Sync 1.0 y Companion 1.0; no crea backend, cursor, entidad de sesión o protocolo paralelos.
2. Servidor/usuario forman `accountScope`; toda tabla y consulta local sensible se filtra por ese scope.
3. Password no se persiste; access token vive en memoria y refresh token se cifra con Android Keystore. Nunca tokens en Room, DataStore, logs, UI o diagnóstico.
4. Release exige HTTPS y validación normal. HTTP solo puede existir en debug, con confirmación explícita y host local allowlisted por la app.
5. Package es inmutable: verificar SHA-256 y versión antes de persistir/iniciar. No empezar expirados ni completar dos veces.
6. Draft, `client_event_id`, `client_submission_id`, idempotency key, secuencia y revisión se escriben antes de la red y no se regeneran al reabrir.
7. Completion no elimina draft hasta respuesta autoritativa. `existing session` enlaza la sesión; conflicto conserva copia local.
8. Sync usa un cursor por dispositivo, transacciones Room, resultados por elemento, backoff+jitter y `Retry-After`; nunca last-write-wins silencioso.
9. Cálculo local usa `BigDecimal`, `1 lb = 0.45359237 kg` y las doce fórmulas backend. `weight_kg` permanece compatible y el servidor decide.
10. Logout/revocación/borrado local cancelan workers y eliminan datos de esa cuenta. Backup Android permanece deshabilitado.
11. Sin analytics, ads, WebView, trust-all, hostname verifier desactivado, body logging, secretos en BuildConfig o componentes exportados innecesarios.
12. Todo cambio funcional requiere unit tests y, cuando corresponda, MockWebServer, Room/Keystore, Compose/instrumentación y contract test backend con fixtures ficticias.
