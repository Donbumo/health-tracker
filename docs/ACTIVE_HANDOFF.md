# Handoff activo

Índice de reglas y guías: [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md).

## Estado actual — Energy Experience 2.0, entrega A para revisión

- Issue #18 recuperado en producción y cerrado como completado tras smoke. PR #21 squash: `9e2f2dc7fea728bfec3c8abf1aed6bc7bb428852`; NAS en 0046, 13.685 alimentos y flags conservados.
- [Cierre productivo](https://github.com/Donbumo/health-tracker/issues/18): backup/restore aislado, imagen compatible, tres días reparados, resto del historial intacto, HTTP/HTTPS y estabilidad PASS. PITR y dispositivos físicos siguen separados.
- Rama local `feature/energy-experience-2-0`, creada después del cierre. [Auditoría, arquitectura y plan](ENERGY_EXPERIENCE_2_0.md), prototipo y diez capturas en `design/energy-experience-2-0/`. 60 combinaciones de layout, teclado y estados PASS.
- Dirección aprobada con gasto protagonista, barras/medias, calendario dinámico e historial filtrado especificado para B. Entrega A implementa `/energy`, facade owner-only y tablas accesibles; legacy y escritores intactos. [QA de A](ENERGY_EXPERIENCE_2_0_A_QA.md): focales y MariaDB RC/RR PASS; evidencia HTTP separada del prototipo.
- Preparar PR de A contra master; no merge, despliegue ni NAS. B/C no implementados. Producción conserva exclusivamente el hotfix aprobado; no desplegar la nueva experiencia sin revisión.

## Contexto — hotfix Energía diaria, issue #18 (desplegado)

- Base verificada: `500589bbafa6d730536595cb7d115f72ebdfe462`, Nutrition 2.1 desplegada en 0045. Preflight NAS exclusivamente de lectura; no se recuperaron aún datos reales.
- Rama `fix/daily-energy-issue-18`: canónico por propietario/fecha, evidencias e identidades móviles conservadas, revisión explícita, edición/borrado confirmado y migración aditiva 0046.
- Alcance, pruebas, capturas, compatibilidad y riesgos de rollback en [DAILY_ENERGY_ISSUE_18.md](DAILY_ENERGY_ISSUE_18.md).
- PR #21: controles JSON 1.1/ZIP y recuperación 0046 PASS en QA LOCAL; 154 tests focales y RC/RR, sin cambios productivos adicionales. [Runbook reproducible](ENERGY_0046_RECOVERY_RUNBOOK.md) y `design/daily-energy-issue-18/qa/review-controls.json`. No se tocó NAS en este cierre.
- Gate del hotfix superado por autorización explícita: merge y despliegue completados tras nueva comparación owner-only, backup consistente, restore aislado y db check. Mantener todos los backups e imagen compatible.
- #18 se cerró después de recuperación y smoke; Energy Experience 2.0 comenzó a continuación en rama separada, sólo como propuesta.
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
