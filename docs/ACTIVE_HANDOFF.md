# Handoff activo

Índice de reglas y guías: [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md).

## Estado actual

- Base: `e41ceb62cac5cc53208e949502dd5e91f1f4eafb` en master. External Exercise Catalog ya fue desplegado en la entrega anterior; este trabajo no accede al NAS.
- Rama `codex/exercise-mapping-assistant`: revisión manual de vínculos desde Mi entrenamiento, lista de pendientes, búsqueda/candidatos visuales, confirmación explícita y cambio de vínculo.
- Reutiliza identidades, aliases y FK nullable existentes. Sin migración, nueva fuente, descargas, AI ni modificación de External Exercise Catalog.

## Trabajo en curso

- Implementación lista para revisión mediante commit y PR. Arquitectura y alcance en [EXERCISE_MAPPING_ASSISTANT.md](EXERCISE_MAPPING_ASSISTANT.md).
- QA exclusivamente ficticia con SQLite/MariaDB efímera y servidor local. No copiar nombres/rutinas reales al repositorio.

## Bloqueadores y riesgos

- Los candidatos son sugerencias, nunca equivalencias automáticas. «Ninguno corresponde» mantiene el ejercicio pendiente o su vínculo anterior.
- No fusiona identidades ni cambia nombres/documentos históricos. Los límites de backup portable de la referencia visual no cambian.
- El gate con ejercicios reales requiere revisión y autorización posterior para producción. No guardar mappings durante QA.

## Siguiente paso

- Revisar el PR. No merge, NAS, tag ni despliegue dentro de esta entrega.
- Después del despliegue autorizado, el usuario selecciona manualmente los candidatos en su cuenta.

## Pruebas relevantes

- QA final: 1,108 backend PASS, 25 gates opcionales omitidos; 10 pruebas del asistente PASS en MariaDB 11.4; db check sin operaciones nuevas; 24 comprobaciones responsive/paleta PASS.
- `backend/tests/test_exercise_mapping.py`: ownership, CSRF, decisiones firmadas y obsoletas, reintentos, aliases/import futuro, historia y nombres legacy.
- `backend/tests/test_external_exercise_catalog.py`, `backend/tests/test_gym_training.py` y suite completa para regresiones.
- `scripts/gym/mapping_qa_app.py`: fixture local, HTTP saliente bloqueado, prueba visual de resumen/candidatos y confirmación ficticia.
