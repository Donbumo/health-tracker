# Handoff activo

Índice de reglas y guías: [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md).

## Estado actual

- Base productiva: `d143a07c92c5a93c97040a69ead9449251d29025`, PR #8 desplegado previamente.
- Rama `fix/gym-import-draft-persistence`: borradores normalizados persistentes para el flujo de importación Gym.
- Reutiliza parser, resolver y publicación oficial. Una única migración mínima `20260928_0043`; no se aplica a producción en esta entrega.

## Trabajo en curso

- Hotfix y contrato en [GYM_IMPORT_DRAFT_PERSISTENCE.md](GYM_IMPORT_DRAFT_PERSISTENCE.md).
- Autosave privado, refresh/reopen, confirmación sin original, conflictos de revisión y recibo idempotente.
- QA exclusivamente ficticia y bases efímeras. No copiar archivos, rutinas ni mappings personales al repositorio.

## Bloqueadores y riesgos

- Las decisiones antiguas no estaban guardadas en servidor. Recuperación desde una pestaña del navegador solo si se comprueba que conserva el formulario; no reconstruir desde logs.
- La migración es necesaria para persistir trabajo antes de que exista una rutina. No reutilizar drafts de sesiones, auditoría ni restore para otro dominio.
- Cambia la retención de originales únicamente en nuevas importaciones Gym: se conserva contenido normalizado y procedencia, sin bytes de upload.

## Siguiente paso

- Entrega con commit `fix: persist gym import mapping progress` y push de la rama; siguiente paso: revisión para PR.
- Sin merge, NAS, tag, AI Coach, descargas de medios ni cambios en mappings reales.

## Pruebas relevantes

- `backend/tests/test_gym_import_drafts.py`: expiración/ausencia física, autosave, reapertura, cancelación, CSRF/ownership, historial, rollback e idempotencia.
- MariaDB focal: 12 pruebas PASS, incluyendo carreras de guardado y confirmación. Migración upgrade/downgrade y db check PASS en schema efímero.
- Suite backend completa: 1119 PASS, 26 gates opcionales omitidos. Autosave JavaScript: 4 PASS con `node --test scripts/gym/test_draft_autosave.cjs`.
- QA local con seis ejercicios: original eliminado, draft envejecido 60 días, refresh/cierre/reapertura, conflicto entre pestañas, fallo de red y reintento, corrección manual y confirmación PASS. Historial ficticio conservado.
- Responsive: anchos 360, 390, 430, 768, 1024 y 1366 sin overflow; captura móvil 390 × 844. Cancelación sin mappings personales PASS.
- Recuperación del incidente real no confirmada: Edge no es accesible desde esta sesión; conservar la pestaña abierta sin recargar. No se modificó producción.
