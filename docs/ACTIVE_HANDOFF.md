# Handoff activo

## Estado actual

- Rama `feature/external-exercise-catalog`, sin worktree, sobre master/origin/master limpio `5607164f771e98b4d731da3e0100473d12ccd0a5`.
- Catálogo externo local: adapter Free Exercise DB, CLI status/sync/cleanup, metadata y vínculo opcional con identidades personales, búsqueda/galería e integración Gym.
- Única migración `20260927_0042` sobre `20260920_0041`. Sin cambios a providers, AI Coach, Strava ni contratos públicos de sesiones/rutinas.
- Arquitectura, operación y evidencia en [EXERCISE_CATALOG.md](EXERCISE_CATALOG.md).

## QA

- MariaDB 11.4 efímera con tmpfs y schemas QA; sin volúmenes persistentes ni NAS.
- Snapshot `f00c92c7dcf1216a928a52c3706c7ce8e2f71ed5`: 876 ejercicios, 1,746 imágenes, aproximadamente 95 MiB; repetición sin duplicados.
- Upgrade desde cero, downgrade 0042→0041, upgrade, head único y db check comprobados.
- Navegación, imágenes, import y sesiones sin solicitudes externas; QA responsive claro/oscuro de 360 a 1366 px.
- Resultados finales y commit en la entrega de la rama. Capturas y snapshot QA fuera de Git.

## Pendiente tras revisión

- Review → PR → squash → master. Sin merge ni deploy en esta entrega.
- Backup DB/storage; verificar estado real del NAS, head y permisos del bind mount antes del deploy.
- Después del deploy: status → dry-run por commit → sync → counts/medios → healthz → gate sin GitHub.
- Solo entonces revisar los seis ejercicios reales unresolved en la cuenta correcta. No se consultaron ni modificaron mappings de producción; `prensa` requiere selección explícita.
