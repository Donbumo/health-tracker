# Seguridad Android Companion

## Identidad y tokens

- Login API Bearer, nunca cookies ni CSRF.
- La contraseña vive solo en el estado de la pantalla y no se persiste.
- Access token solo en memoria; refresh token AES/GCM con clave no exportable de Android Keystore.
- Refresh single-flight, una reanudación por 401 y sin loops. La rotación reemplaza el cifrado anterior; reuse/revocación fuerza login.
- Authorization, tokens, passwords, bodies, notas y payloads nunca se registran ni entran al diagnóstico.

## Red

Release acepta solo HTTPS con validación TLS/hostname normal de OkHttp. No hay trust-all, pinning inseguro ni hostname verifier personalizado. Debug puede habilitar cleartext únicamente tras confirmación explícita y validación en aplicación de loopback, emulador, IPv4 RFC1918 o `.local`; el riesgo de LAN sin TLS se muestra y queda fuera de release.

Solo se aceptan esquemas `https`/`http`; se rechazan userinfo, query, fragment, rutas base, `javascript:`, `file:` y `content:`. No hay body logging.

## Plataforma

- `allowBackup=false` y reglas de extracción excluyen todos los datos.
- La Activity principal solo exporta el launcher. Alpha 1.5 añade la Activity/alias exportadas exigidas por Health Connect para rationale y uso de permisos, protegidas por las acciones/permisos oficiales; no hay receivers, services, providers ni deep links propios exportados.
- Sin permisos de ubicación, Bluetooth, archivos ni publicidad. Alpha 1.5 declara exclusivamente permisos de lectura Health Connect para peso, grasa corporal, masa magra, masa de agua, pasos y nutrición, más lectura en background; solo solicita en runtime los tipos compatibles y seleccionados, y el permiso de background se pide por separado cuando la feature está disponible.
- Sin WebView, SDK de fabricante, analytics o crash reporter externo.
- R8 activo en release; ningún secreto o URL privada entra en `BuildConfig`.

## Datos locales

Room permanece en almacenamiento privado de la app y usa `accountScope = SHA256(server URL + user UUID)` en toda consulta. Se guardan únicamente datos de entrenamiento necesarios, no respuestas clínicas completas. Logout, revocación y borrado local eliminan cache, drafts, cursores y pendientes de esa cuenta; no afectan otras cuentas.

El diagnóstico exportable previsto es una allowlist de versión, timestamps, estado de red, cantidad de pendientes y códigos. No incluye IDs completos, hashes, headers, tokens, notas ni payloads.

Cerrar todas las sesiones, revocar el dispositivo y borrar datos locales muestran alcance explícito y requieren una confirmación adicional. Los botones quedan protegidos contra doble envío. Cerrar sesión afecta esta cuenta local; cerrar todas revoca sesiones API; revocar bloquea el dispositivo; borrar local no modifica el servidor.

Health Connect es opt-in y de solo lectura. La Activity de rationale y la pantalla de Ajustes explican finalidad, tipos y controles. Pausar o desconectar no llama a `revokeAllPermissions`; administrar acceso abre la superficie del sistema. El borrado de importados exige confirmación separada y preserva `manual` y `user_override`.

Valores, nutrientes, pasos, IDs completos, origins completos, permisos completos, tokens y payloads Health Connect no se registran. El estado observable solo expone tipos seleccionados/concedidos, conteos, timestamps y códigos sanitizados. El package de origen se conserva privado en el ledger para enlazar correctamente peso y composición, pero no se usa como identidad única ni se muestra en diagnósticos.
