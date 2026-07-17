# Roadmap

Este documento reúne trabajo futuro o no comprobado. No describe funcionalidades implementadas; verifica siempre el código, los schemas y las pruebas antes de cambiar el estado de un punto.

## Próximos cierres operativos

- Sign-off visual real de tema claro para Alpha 1.0.
- Rotación de la credencial señalada durante QA antes de un release posterior.
- Definir retención/pruning de auditorías solo si existe una política operativa explícita.
- Ampliar updates seguros únicamente donde haya identidad o clave natural verificable.

## Companion móvil y reloj

- APK Android con login, cache offline, ejecución desde teléfono y sincronización.
- Bridge Bluetooth/reloj y app de reloj para guiar sesiones offline.
- Telemetría continua solo con contrato, límites, privacidad y pruebas propios.
- Ninguna de estas capas debe presentarse como existente por el hecho de que el backend Companion ya exponga negociación y deliveries.

## Integraciones y formatos

- FIT de salida solo con una biblioteca mantenida y validación binaria; sigue unsupported.
- Integraciones Garmin, Huawei, Magene/OnelapFit, Strava o TrainingPeaks requieren APIs oficiales y autorización; no usar scraping ni APIs privadas.
- OCR/FHIR y procesamiento de PDFs médicos requieren un bloque de seguridad y contrato independiente.

## Producto

- Mapping asistido reutilizable y persistente.
- Calendario/planificador visual y edición avanzada donde exista demanda validada.
- Nuevos dominios de salud únicamente con schema, aislamiento, trazabilidad, import/export y pruebas completos.
