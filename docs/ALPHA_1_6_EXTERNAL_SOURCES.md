# Alpha 1.6 — fuentes externas y base BLE experimental

## Alcance honesto

Alpha 1.6 incorpora una infraestructura local para identificar fuentes externas, diagnosticar orígenes de báscula en Health Connect, asociar dispositivos BLE, inspeccionar GATT, capturar/reproducir sesiones limitadas y reconciliar candidatos. No declara resuelto el protocolo Xiaomi S400. Peso y composición corporal por BLE permanecen deshabilitados; Health Connect continúa siendo de solo lectura.

El backend no cambia. MAC, association ID, servicios GATT, manufacturer data, frames y capturas nunca se envían al servidor.

## Arquitectura

```text
Health Connect ──→ diagnóstico sanitizado ──→ confirmación local de origen
                                                   │
Android Bluetooth → scan/asociación → GATT → notify/indicate seleccionado
                                      │                 │
                                      └→ snapshot       └→ ble-capture-v1 cifrado
                                                               │
fixture ficticia → replay → frame técnico → XiaomiS400ProtocolAdapter
                                             │
                                             └→ sin medición hasta validar evidencia

fuentes/ledgers → ExternalMeasurementReconciler → exact/probable/possible/distinct
```

`ExternalHealthSource`, `ExternalSourceRegistry`, `ExternalSourceIdentity`, `ExternalSourceCapability`, `ExternalMeasurement`, `ExternalMeasurementEvidence` y `ExternalMeasurementReconciler` no dependen de Health Connect, Bluetooth Android ni del servidor. Las fuentes iniciales son `manual`, `health_connect_generic`, `health_connect_confirmed_scale`, `health_connect_confirmed_xiaomi_s400` y `xiaomi_s400_ble_experimental`.

Toda persistencia sensible se filtra por `accountScope`, que ya combina identidad normalizada de servidor y usuario. Un fingerprint de fuente externa no es el ID de autenticación, el public ID API, una MAC ni el `DataOrigin` completo.

## Diagnóstico Health Connect

**Ajustes → Fuentes externas → Comprobar datos de báscula** lee únicamente `WeightRecord` y `BodyFatRecord` dentro de una ventana acotada de 30 días y diez páginas por tipo. Calcula tipos, conteos, orígenes, fechas truncadas a día e identidades ya presentes en el ledger Alpha 1.5. No expone peso, grasa, record/client IDs, package name, metadata, tokens ni valores.

Cada origen se presenta como **Aplicación de salud** y fingerprint corto. No se clasifica automáticamente como Xiaomi. El usuario puede marcarlo como báscula genérica, Xiaomi S400, otro dispositivo o ambiguo, y revocar/cambiar la decisión. Es una preferencia local con estados `unconfirmed`, `user_confirmed`, `ambiguous`, `revoked` y `unavailable`; un origen nuevo nunca hereda la confirmación de otro fingerprint. El ledger Health Connect continúa gobernando dedupe por record ID y no se reescriben mediciones históricas.

## Permisos y disponibilidad Bluetooth

- API 31+: `BLUETOOTH_SCAN` y `BLUETOOTH_CONNECT`; no se declara `BLUETOOTH_ADVERTISE`.
- API 26–30: permisos Bluetooth heredados limitados con `maxSdkVersion=30` y `ACCESS_FINE_LOCATION` solo para el scan BLE que esas versiones requieren.
- BLE es una feature opcional del manifest; un teléfono sin BLE puede usar el resto de la app.
- La solicitud aparece únicamente al pulsar la acción contextual en Fuentes externas. Login, bootstrap y WorkManager general no la disparan.
- UI diferencia dispositivo sin BLE, Bluetooth apagado, permiso necesario y listo.

No se usa `neverForLocation`: Android advierte que esa aserción puede filtrar ciertos resultados BLE y todavía no existe evidencia física suficiente para demostrar que no compromete la detección S400. La app no deriva ubicación de los resultados y no persiste una MAC.

## Scan, asociación y process death

El scan explícito dura 20 segundos por defecto y el contrato solo admite 15–30. Es cancelable, single-flight, no se reinicia en bucle y se detiene al seleccionar, salir de pantalla o entrar en background. La UI nunca escoge el primer resultado; `select()` solo acepta un ID opaco perteneciente al listado de la sesión. Una doble pulsación reutiliza la asociación por fingerprint.

Existe adaptador `CompanionDeviceManager` para el chooser del sistema. La ruta operativa actual usa fallback BLE explícito porque la conexión física posterior requiere conservar una selección observable en la misma sesión y Alpha 1.6 todavía no dispone de QA S400 real para escoger una política más restrictiva. Room persiste association ID cuando exista, nombre sanitizado, alias, fingerprint, UUIDs observados, fingerprint de manufacturer (nunca bytes), fechas, estado y modelo confirmado por el usuario. Tras process death la asociación/capturas reaparecen desde Room; para reconectar el fallback sin persistir MAC se repite un scan y se selecciona el mismo fingerprint.

## GATT seguro

La inspección comprueba entorno/permisos, conecta con timeout, descubre servicios/características/descriptores dentro de límites, clasifica `read`, `write`, `write_no_response`, `notify` e `indicate`, genera un snapshot sanitizado y siempre desconecta/cierra GATT. No lee valores ni escribe características.

Para una captura, el usuario debe escoger en el snapshot una característica `notify/indicate`. La única escritura ejecutable es el descriptor CCCD estándar requerido por Android para habilitar notificaciones/indicaciones; no hay UUID, comandos ni escrituras S400 inventadas. Límites por defecto: conexión 12 s, descubrimiento 10 s, captura 90 s, 256 KiB y 2.000 eventos; servicios 40, características 200 y descriptores 400.

## Captura privada, export y replay

La acción debug `Capturar sesión de medición` requiere asociación, entorno listo, selección explícita y consentimiento. Se detiene por timeout, límite, desconexión, cancelación, salida o background. El archivo se serializa como `ble-capture-v1`, se cifra AES/GCM con una clave Android Keystore y se guarda con nombre aleatorio bajo `noBackupFilesDir`. Room solo recibe metadata mínima y checksum SHA-256.

Una exportación exige advertencia y elección del destino, usa un `FileProvider` no exportado y permiso temporal read-only; la URI y copia temporal se revocan/eliminan al salir de la pantalla y también se limpian al iniciar la app. No hay upload. Borrar una captura no borra la asociación; olvidar una asociación no borra mediciones ni reinterpreta capturas.

El formato excluye MAC, nombre completo, cuenta, servidor, usuario, timestamp absoluto, device API ID y tokens. `DeterministicBleReplaySource` emite eventos en orden estable. Las fixtures versionadas del repositorio declaran `fixtureFictional: true` y usan UUIDs/bytes inventados.

## Ground truth y protocolo S400

`ProtocolEvidenceEntity` mantiene el valor mostrado introducido por desarrollo, unidad e instante relativo fuera del dominio de salud. `XiaomiS400ProtocolAdapter` solo agrupa frames, cuenta repeticiones, compara longitud/bytes y produce fingerprints/estabilidad técnica. `DisabledXiaomiS400MeasurementMapper` siempre devuelve ausencia.

Para habilitar peso futuro se requieren al menos cinco capturas, tres valores distintos, unidades aplicables, coincidencia exacta con todos los displays, repetibilidad, integridad, cero colisiones y revisión manual. Una observación nunca basta. Composición, impedancia, grasa, músculo, agua, edad, sexo y fórmulas permanecen sin soporte.

## Reconciliación multifuentе

El reconciliador usa métrica, record/client ID, content fingerprint, dispositivo confirmado, timestamp y valor/precisión. Solo `exact_duplicate` con identidad fuerte puede reconciliarse automáticamente. `probable_duplicate` y `possible_duplicate` conservan ambas mediciones y deben permitir una decisión explícita posterior; `user_override` y `user_detached` nunca se pisan. Proximidad temporal por sí sola no elimina nada.

## Room 6

La migración explícita 5→6 añade `external_sources`, `external_source_capabilities`, `health_connect_source_associations`, `ble_device_associations`, `ble_gatt_snapshots`, `ble_capture_metadata`, `external_measurement_ledger`, `possible_duplicates` y `protocol_evidence`. La cadena 1/2/3/4/5→6 no usa fallback destructivo. Logout borra únicamente la partición efectiva; cambiar servidor conserva particiones aisladas. Capturas grandes permanecen fuera de SQLite.

## Herramientas locales

```powershell
python scripts/development/sanitize_ble_capture.py --help
python scripts/development/inspect_ble_fixture.py --help
python scripts/development/compare_ble_captures.py --help

python scripts/development/sanitize_ble_capture.py "C:\ruta con espacios\capture.json" "C:\ruta con espacios\fixture-candidate.json"
python scripts/development/inspect_ble_fixture.py android/app/src/test/resources/fixtures/ble_capture_stable_fictional.json
python scripts/development/compare_ble_captures.py <captura-a.json> <captura-b.json>
```

Sanitizar nunca sobrescribe el original ni añade la salida a Git. Inspección oculta payloads salvo `--show-payload`, que emite una advertencia. Comparación informa estructura, longitudes, repeticiones y offsets candidatos sin semántica.

## Limitaciones y QA pendiente

- No se ejecutó QA con báscula ni teléfono físico, instalación APK o instrumentación conectada.
- La ruta CompanionDeviceManager y la suscripción/CCCD requieren comprobación física en API 26, 30, 31, 34 y 36.
- Deben validarse detección, cancelación/background, permisos permanentes, GATT de la unidad real, cifrado/export/revocación y accesibilidad.
- Una captura real debe permanecer fuera de Git. Solo después de exportarla explícitamente, sanitizarla y revisarla puede producir una fixture candidata; incluso entonces no demuestra semántica por sí sola.
