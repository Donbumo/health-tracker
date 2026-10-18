# Handoff activo

Índice de reglas y guías: [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md).

## Estado actual — Energía diaria, issue #18

- Base verificada: `500589bbafa6d730536595cb7d115f72ebdfe462`, Nutrition 2.1 desplegada en 0045. Preflight NAS exclusivamente de lectura; no se recuperaron aún datos reales.
- Rama `fix/daily-energy-issue-18`: canónico por propietario/fecha, evidencias e identidades móviles conservadas, revisión explícita, edición/borrado confirmado y migración aditiva 0046.
- Alcance, pruebas, capturas, compatibilidad y riesgos de rollback en [DAILY_ENERGY_ISSUE_18.md](DAILY_ENERGY_ISSUE_18.md).
- PR #21: controles JSON 1.1/ZIP y recuperación 0046 PASS en QA LOCAL; 154 tests focales y RC/RR, sin cambios productivos adicionales. [Runbook reproducible](ENERGY_0046_RECOVERY_RUNBOOK.md) y `design/daily-energy-issue-18/qa/review-controls.json`. No se tocó NAS en este cierre.
- Gate del usuario: autorización final de squash/despliegue pendiente; sin merge/despliegue hasta revisar resultados. La recuperación exige nueva comparación owner-only, backup consistente nuevo y restore aislado antes de DDL/escrituras. Mantener todos los backups anteriores.
- No cerrar #18 automáticamente al merge: sólo después del smoke y recuperación productivos. Energy Experience 2.0 empieza en rama separada únicamente después de ese cierre; no se ha iniciado.
- No cambiar flags productivos, catálogo, snapshots de Nutrition ni DB/volúmenes del NAS. Nunca downgrade destructivo de 0046 después de decisiones/tombstones nuevos.

## Contexto anterior — Gym

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
