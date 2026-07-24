# Roadmap

Este documento reúne trabajo futuro o no comprobado. No describe funcionalidades implementadas; verifica siempre el código, los schemas y las pruebas antes de cambiar el estado de un punto.

## Próximos cierres operativos

- Sign-off visual real de tema claro para Alpha 1.0.
- Rotación de la credencial señalada durante QA antes de un release posterior.
- Definir retención/pruning de auditorías solo si existe una política operativa explícita.
- Ampliar updates seguros únicamente donde haya identidad o clave natural verificable.

## Companion móvil y reloj

- Completar QA manual offline/rotación/accesibilidad/temas, instrumentación en un AVD separado, revisión de integración, firma de producción y distribución del cliente Android; compilación, lint, JVM, APK y compilación androidTest ya están verdes.
- Bridge Bluetooth/reloj y app de reloj para guiar sesiones offline.
- Telemetría continua solo con contrato, límites, privacidad y pruebas propios.
- El cliente de teléfono no implica bridge, app de reloj ni soporte de fabricantes.

## Integraciones y formatos

- FIT de salida solo con una biblioteca mantenida y validación binaria; sigue unsupported.
- Integraciones Garmin, Huawei, Magene/OnelapFit, Strava o TrainingPeaks requieren APIs oficiales y autorización; no usar scraping ni APIs privadas.
- OCR/FHIR y procesamiento de PDFs médicos requieren un bloque de seguridad y contrato independiente.

## Producto

- Mapping asistido reutilizable y persistente.
- Calendario/planificador visual y edición avanzada donde exista demanda validada.
- Nuevos dominios de salud únicamente con schema, aislamiento, trazabilidad, import/export y pruebas completos.
