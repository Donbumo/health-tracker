# Seguridad Android Companion

## Endurecimiento Beta 1

Toda caché médica, ruta/serie y export de actividad deriva el nombre de un SHA-256 opaco separado por propósito; un UUID/ID remoto nunca se interpola como path. La escritura valida el parent canónico y un export fallido elimina su parcial. La cancelación estructurada se propaga desde gateway/colas/workers para que logout o cambio de servidor no se conviertan en retry silencioso.

El auditor Beta inspecciona package, versión, SDK, debuggable, firma v2/v3, permisos, ZIP y patrones sensibles sin imprimir coincidencias. Los reportes viven fuera del repositorio y solo contienen nombres de patrones, conteos y clasificación.

## Ubicación de actividades Alpha 2.0

Las rutas son datos sensibles. La selección ofrece conservar, recortar extremos o descartar sin una activación silenciosa. Android dibuja la copia visible localmente y no usa mapas, tiles, geocodificación ni nombres de calles. Exportar usa un FileProvider privado y chooser explícito; JSON omite ruta por defecto y GPX solo se habilita si existe una ruta visible.

Room no guarda series densas ni coordenadas completas. Los parciales, series reducidas y rutas cacheadas usan almacenamiento privado/no-backup separado por hash del scope. Diagnóstico y UI solo muestran tipo, tamaño, estado, conteos y hash corto; nunca token, path, hash completo, coordenadas, contenido FIT/XML ni nombre completo en logs. Logout limpia el scope efectivo y el cambio de servidor no cruza identidades.

## Notificaciones Alpha 1.8

No existe push externo. `POST_NOTIFICATIONS` sólo se solicita tras una activación explícita y `RECEIVE_BOOT_COMPLETED` se limita a un receiver no exportado que delega a WorkManager. No hay permisos de alarmas exactas, servicios foreground, ubicación, calendario, contactos o SMS. Los `PendingIntent` son immutable; actions y workers vuelven a validar cuenta, hash del servidor, revisión, regla y recurso en Room. Contenido y diagnóstico siguen la allowlist de [Privacidad de notificaciones](NOTIFICATION_PRIVACY.md).

## Fuentes externas Alpha 1.6

BLE se declara opcional. El manifest usa `BLUETOOTH_SCAN`/`BLUETOOTH_CONNECT` en API 31+ y permisos heredados/ubicación con `maxSdkVersion=30`; no declara advertise. No se usa `neverForLocation` porque todavía podría filtrar dispositivos necesarios y falta evidencia S400 real. La solicitud solo aparece desde Fuentes externas; denegar/revocar no cierra sesión ni afecta Health Connect o entrenamiento.

No se registran MAC, manufacturer bytes, payloads, peso, grasa, impedancia, record IDs o package names completos. Asociación persiste únicamente identity/fingerprints sanitizados. Snapshots GATT no guardan valores. Capturas se cifran AES/GCM con Keystore bajo `noBackupFilesDir`, tienen límites y no se diagnostican/suben. FileProvider es no exportado; una exportación manual concede lectura temporal y elimina/revoca la copia al abandonar la pantalla o reiniciar. Logout/borrado local elimina primero los archivos cifrados del `accountScope` y después su metadata Room; cambiar servidor conserva la partición anterior sin mezclarla. El CCCD estándar es la única escritura de captura; no existen escrituras de características desconocidas.

## Identidad y tokens

- Login API Bearer, nunca cookies ni CSRF.
- La contraseña vive solo en el estado de la pantalla y no se persiste.
- Access token solo en memoria; refresh token AES/GCM con clave no exportable de Android Keystore.
- Refresh single-flight, una reanudación por 401 y sin loops. La rotación reemplaza el cifrado anterior; reuse/revocación fuerza login.
- Authorization, tokens, passwords, bodies, notas y payloads nunca se registran ni entran al diagnóstico.

## Red

Release acepta solo HTTPS con validación TLS/hostname normal de OkHttp. No hay trust-all, pinning inseguro ni hostname verifier personalizado. Debug puede habilitar cleartext únicamente tras confirmación explícita y validación en aplicación de loopback, emulador, IPv4 RFC1918 o `.local`; el riesgo de LAN sin TLS se muestra y queda fuera de release. La URL conserva puerto y base path válidos, rechaza credenciales/query/fragmento y se normaliza sin slash final.

Solo se aceptan esquemas `https`/`http`; se rechazan userinfo, query, fragment, rutas base, `javascript:`, `file:` y `content:`. No hay body logging.

## Plataforma

- `allowBackup=false` y reglas de extracción excluyen todos los datos.
- Los componentes propios exportados son el launcher y la Activity/alias exigidas por Health Connect para rationale y uso de permisos. El manifest combinado añade componentes de AndroidX Health/WorkManager protegidos por sus acciones o permisos oficiales; no hay deep links ni receivers/services/providers de negocio propios. No se declara FileProvider porque el diagnóstico se comparte como texto y no se exponen archivos.
- Sin permisos de ubicación, Bluetooth, archivos ni publicidad. Alpha 1.5 declara exclusivamente permisos de lectura Health Connect para peso, grasa corporal, masa magra, masa de agua, pasos y nutrición, más lectura en background; solo solicita en runtime los tipos compatibles y seleccionados, y el permiso de background se pide por separado cuando la feature está disponible.
- Sin WebView, SDK de fabricante, analytics o crash reporter externo.
- R8 activo en release; ningún secreto o URL privada entra en `BuildConfig`.

## Paquetes portables Alpha 1.7

- SAF evita permisos amplios de almacenamiento; una copia pública requiere selección explícita.
- FileProvider separado (`.portability`) es non-exported y concede sólo lectura temporal.
- Descargas y parciales viven bajo filesDir, en subdirectorios derivados por hash de `accountScope`; no entran en backup ni Room.
- Android valida hash, límites, nombres ZIP, duplicados, manifest y checksums antes del upload. El backend repite la verificación completa y valida schemas.
- No se escriben tokens, contenido de records o rutas en logs; la UI trunca IDs y hashes.
- El paquete no cifrado muestra advertencia de salud y autenticidad no demostrada.

## Datos locales

Room permanece en almacenamiento privado de la app y usa `accountScope = SHA256(server URL + user UUID)` en toda consulta. El refresh cifrado queda además ligado a la URL normalizada: un token de un NAS no se devuelve al cliente para otro. **Cambiar servidor** exige confirmación, invalida tokens y scope activos, cancela workers y conserva las filas antiguas bajo su scope aislado. Logout, revocación y borrado local sí eliminan cache, drafts, cursores y pendientes de esa cuenta.

El diagnóstico Health Connect exportable usa allowlist: versión de app/Android, estado del proveedor, tipos seleccionados, conteos, timestamps y códigos sanitizados. No incluye valores de peso/grasa/pasos/nutrición, IDs/origins completos, changes tokens, headers, access/refresh tokens, notas ni payloads.

Cerrar todas las sesiones, revocar el dispositivo y borrar datos locales muestran alcance explícito y requieren una confirmación adicional. Los botones quedan protegidos contra doble envío. Cerrar sesión afecta esta cuenta local; cerrar todas revoca sesiones API; revocar bloquea el dispositivo; borrar local no modifica el servidor.

Health Connect es opt-in y de solo lectura. La Activity de rationale y la pantalla de Ajustes explican finalidad, tipos y controles. Pausar o desconectar no llama a `revokeAllPermissions`; administrar acceso abre la superficie del sistema. El borrado de importados exige confirmación separada y preserva `manual` y `user_override`.

Valores, nutrientes, pasos, IDs completos, origins completos, permisos completos, tokens y payloads Health Connect no se registran. El estado observable solo expone tipos seleccionados/concedidos, conteos, timestamps y códigos sanitizados. El package de origen se conserva privado en el ledger para enlazar correctamente peso y composición, pero no se usa como identidad única ni se muestra en diagnósticos.

## Datos médicos Alpha 1.9

No se registran títulos, laboratorios/profesionales, notas, nombres de archivo, valores, unidades, rangos, marcadores, documentos, JSON/CSV, hashes completos, URI o rutas. SAF evita permisos amplios; la copia de upload vive en `noBackupFilesDir`, y el FileProvider médico no se exporta. Compartir/abrir requiere acción explícita y grant temporal. Notificaciones siguen genéricas y nunca muestran resultados. Véase [MEDICAL_DATA_PRIVACY.md](MEDICAL_DATA_PRIVACY.md).
