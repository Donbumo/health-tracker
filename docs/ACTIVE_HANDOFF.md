# Handoff activo

## Estado actual

- Producción permanece en el squash PR #30 `12bad71a60b96b57d282cfaf745fc0dc4ed27ab6`, estable según el cierre autorizado del 29-10. MariaDB 0046; ninguna acción de despliegue en esta corrección.
- La aceptación autenticada anterior falló funcionalmente: 21 detectados, 1 listo/20 pendientes, cero consumos confirmados o productos creados. Se conservan la revisión #29 y el fork #30. No afirmar aceptación productiva 21/0 a partir de QA.
- Rama correctiva sobre master: `codex/nutrition-import-legacy-semantics`. [Contrato legacy, diagnóstico y evidencia](NUTRITION_IMPORT_LEGACY_SEMANTICS.md).
- Índice de reglas y guías: [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md). Los antecedentes de UX y porciones quedan en [UX](NUTRITION_IMPORT_UX.md) y [PR #30](NUTRITION_IMPORT_CONSUMED_FIX.md).

## Trabajo en curso

- Gate de revisión corregido: huella semántica, invalidación de POST posteriores y exclusión de filas editadas del grupo sin perder el resto. Diagnóstico privado real anterior al merge: 18 agrupables; existen excepciones legítimas, no prometer 21/0.

- Adaptador semántico diario 1.0: totales por elemento, bases explícitas por 100 g/ml y por unidad; revisión agrupada sólo con fundamento documentado. Declaraciones suficientes sin identidades obligatorias.
- Extractor `nutrition-legacy-semantics-v3`; nuevo fork trazable desde #29/#30, sin renovar firmas ni copiar consentimiento. Conserva correcciones, originales y revisiones previas.
- Fixture ficticia de estructura legacy de 21 elementos/20 sin base explícita. Ambigüedades, marcadores y equivalencias aproximadas requieren decisión; estimaciones etiquetadas y nutrientes ausentes desconocidos.
- Sin migraciones, dependencias, escritores nuevos, guardado parcial ni Nutrition Intelligence C.

## Bloqueadores y riesgos

- El propietario autoriza cerrar la revisión 5704011429, squash y despliegue de sólo web tras los gates. La confirmación de consumos reales continúa prohibida en esta ejecución.
- Esta entrega no reabre la sesión productiva ni copia el archivo personal a QA. El diagnóstico público se limita a agregados de la aceptación autorizada anterior.
- Confirmaciones concurrentes pueden producir un 409 seguro en el intento perdedor durante el hueco de auditoría; el reintento devuelve el recibo existente sin duplicar.
- Mantener datos actuales ante recuperación: sólo imagen web compatible, nunca restaurar backups antiguos sobre escrituras nuevas.

## Siguiente paso

- Revisar el PR correctivo con el informe y la evidencia. Después de aprobarlo, preparar actualización de sólo web con backup nuevo verificado y restore aislado.
- Repetir aceptación real y medir listos, ambigüedades, decisiones y equivalencias pendientes. No confirmar consumos personales sin autorización posterior expresa.

## Pruebas relevantes

- SQLite focal: estructura legacy, escalado una sola vez, estados/procedencia, owner, CSRF, firma, consentimiento, rollback, historial y export/restore.
- MariaDB local efímera RC/RR 0046: ocho escenarios #29/#30 vigentes/vencidos, fork concurrente, correcciones conservadas, confirmación/replay atómicos y GET sin DML/DDL.
- Flask real en móvil/escritorio con usuarios ficticios: 1/20 anterior → 3/18 tras extracción → 21/0 tras interpretación y dos excepciones conscientes; cero productos. Capturas en el informe.
