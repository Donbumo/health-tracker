# Roadmap

Este documento reúne trabajo futuro o no comprobado. No describe funcionalidades implementadas; verifica siempre el código, los schemas y las pruebas antes de cambiar el estado de un punto.

## Próximos cierres operativos

- Sign-off visual real de tema claro para Alpha 1.0.
- Rotación de la credencial señalada durante QA antes de un release posterior.
- Definir retención/pruning de auditorías solo si existe una política operativa explícita.
- Ampliar updates seguros únicamente donde haya identidad o clave natural verificable.

## Companion móvil y reloj

- Completar QA manual de Alpha 1.4: recorrido Hoy→peso→desayuno→pasos, modo avión, process death, edición nutricional offline, reconexión sin duplicados, resolución de conflictos, Progreso Salud, rotación, TalkBack, fuente grande y tamaños 320/360/411/600 dp. Ejecutar instrumentación solo en un AVD separado.
- Completar QA manual de Alpha 1.3 para planificación: creación/edición offline, coalescing al mover o cancelar, varios eventos diarios, cambio de zona horaria, reemplazo de package sin draft y conflicto con draft activo, ciclo Hoy→Historial→Progreso, rotación, TalkBack, fuente grande y tamaños 320/360/411/600 dp; no está aprobado todavía.
- Completar QA manual de Alpha 1.2 para Historial/Progreso: paginación offline, rotación, TalkBack, fuente grande, temas y gráficas en tamaños 320/360/411/600 dp; no está aprobado todavía.
- Completar QA manual offline/rotación/accesibilidad/temas, instrumentación en un AVD separado, revisión de integración, firma de producción y distribución del cliente Android; compilación, lint, JVM, APK y compilación androidTest ya están verdes.
- Bridge Bluetooth/reloj y app de reloj para guiar sesiones offline.
- Telemetría continua solo con contrato, límites, privacidad y pruebas propios.
- El cliente de teléfono no implica bridge, app de reloj ni soporte de fabricantes.

## Integraciones y formatos

- Health Connect, Google Fit, Huawei Health, Xiaomi Home/S400, BLE y Wear OS permanecen posteriores a Alpha 1.4; requerirán contrato de procedencia, consentimiento, deduplicación y revocación antes de implementarse.

- FIT de salida solo con una biblioteca mantenida y validación binaria; sigue unsupported.
- Integraciones Garmin, Huawei, Magene/OnelapFit, Strava o TrainingPeaks requieren APIs oficiales y autorización; no usar scraping ni APIs privadas.
- OCR/FHIR y procesamiento de PDFs médicos requieren un bloque de seguridad y contrato independiente.

## Producto

- Mapping asistido reutilizable y persistente.
- Nuevos dominios de salud únicamente con schema, aislamiento, trazabilidad, import/export y pruebas completos.
