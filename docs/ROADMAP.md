# Roadmap

Este documento reúne trabajo futuro o no comprobado. No describe funcionalidades implementadas; verifica siempre el código, los schemas y las pruebas antes de cambiar el estado de un punto.

## Próximos cierres operativos

- Completar QA manual Alpha 1.7 en Android y round-trip entre dos instancias efímeras; firma/autenticidad criptográfica y cifrado estándar quedan para una fase contractual posterior.
- Evaluar jobs asíncronos/reanudación HTTP por rangos sólo si los límites actuales dejan de ser suficientes; no ampliar retención o nube sin política explícita.
- Sign-off visual real de tema claro para Alpha 1.0.
- Rotación de la credencial señalada durante QA antes de un release posterior.
- Definir retención/pruning de auditorías solo si existe una política operativa explícita.
- Ampliar updates seguros únicamente donde haya identidad o clave natural verificable.

## Companion móvil y reloj

- Completar QA físico Alpha 1.6 con S400/fixtures QA: permisos API 26/30/31/34/36, CompanionDeviceManager/fallback, scan cancel/background, fingerprint tras process death, GATT/CCCD, límites, cifrado, delete/export/revocación, TalkBack y ausencia de payloads/logs. No añadir la captura real a Git.
- Investigar peso S400 únicamente con el criterio de evidencia de `XIAOMI_S400_PROTOCOL_RESEARCH.md`; composición sigue siendo un proyecto contractual independiente aun si peso se valida.

- Completar QA manual de Alpha 1.5 con Health Connect real y datos ficticios: dispositivo/proveedor ausente y actualización, permisos parciales/revocación, peso+grasa del mismo origen, pasos en cambio de zona, nutrición incompleta, background opt-in, eliminación remota, edición detached, servidor offline→reconexión, process death, borrado selectivo y accesibilidad. Ejecutar instrumentación únicamente en un AVD o dispositivo separado.
- Completar QA manual de Alpha 1.4: recorrido Hoy→peso→desayuno→pasos, modo avión, process death, edición nutricional offline, reconexión sin duplicados, resolución de conflictos, Progreso Salud, rotación, TalkBack, fuente grande y tamaños 320/360/411/600 dp. Ejecutar instrumentación solo en un AVD separado.
- Completar QA manual de Alpha 1.3 para planificación: creación/edición offline, coalescing al mover o cancelar, varios eventos diarios, cambio de zona horaria, reemplazo de package sin draft y conflicto con draft activo, ciclo Hoy→Historial→Progreso, rotación, TalkBack, fuente grande y tamaños 320/360/411/600 dp; no está aprobado todavía.
- Completar QA manual de Alpha 1.2 para Historial/Progreso: paginación offline, rotación, TalkBack, fuente grande, temas y gráficas en tamaños 320/360/411/600 dp; no está aprobado todavía.
- Completar QA manual offline/rotación/accesibilidad/temas, instrumentación en un AVD separado, revisión de integración, firma de producción y distribución del cliente Android; compilación, lint, JVM, APK y compilación androidTest ya están verdes.
- Bridge Bluetooth/reloj y app de reloj para guiar sesiones offline.
- Telemetría continua solo con contrato, límites, privacidad y pruebas propios.
- El cliente de teléfono no implica bridge, app de reloj ni soporte de fabricantes.

## Integraciones y formatos

- Ampliar Health Connect más allá de la lectura Alpha 1.5 solo con contrato y consentimiento independientes. Siguen pendientes escritura, ejercicio/rutas, sueño, signos vitales y datos médicos; masa magra y masa de agua requieren primero campos canónicos semánticamente equivalentes.
- Google Fit, Huawei Health directo, Xiaomi Home y Wear OS siguen fuera de alcance. S400/BLE dispone solo de infraestructura experimental local; soporte de métricas sigue pendiente de evidencia, contrato, consentimiento y QA físico.

- FIT de salida solo con una biblioteca mantenida y validación binaria; sigue unsupported.
- Integraciones Garmin, Huawei, Magene/OnelapFit, Strava o TrainingPeaks requieren APIs oficiales y autorización; no usar scraping ni APIs privadas.
- OCR/FHIR y procesamiento de PDFs médicos requieren un bloque de seguridad y contrato independiente.

## Producto

- Mapping asistido reutilizable y persistente.
- Nuevos dominios de salud únicamente con schema, aislamiento, trazabilidad, import/export y pruebas completos.
