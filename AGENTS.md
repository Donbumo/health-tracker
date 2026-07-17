# Instrucciones para agentes

Este archivo es el contexto caliente del repositorio. Debe bastar para tareas pequeñas. No leas toda la documentación por defecto: usa el índice y abre solo las reglas del dominio que realmente toque la tarea.

## Seguridad y privacidad

- No leas, muestres, copies ni resumas `.env`.
- No toques `/data` ni volúmenes persistentes salvo instrucción explícita y alcance verificado.
- No añadas a Git datos reales de salud, nutrición, entrenamiento, médicos o personales.
- Usa únicamente fixtures ficticias y claramente identificadas como QA/demo.
- Todo dato, archivo, consulta, export, import y sincronización sensible debe quedar aislado por el `user_id` efectivo del servidor; nunca confíes en un `user_id` del cliente.
- No expongas secretos, tokens, hashes, payloads sensibles, rutas internas ni datos de otros usuarios.
- No hagas commit, push, merge, tag ni operaciones destructivas salvo solicitud explícita.

## Convenciones generales

- Los JSON Schemas de `schemas/` son el contrato público. Los aliases externos solo viven en detección o normalización.
- No inventes campos requeridos ni uses placeholders para satisfacer schemas. Genera lo disponible y deja que la validación informe lo faltante.
- Mantén el pipeline auditable: entrada → conversión/generación → JSON estándar → validación → importador oficial → MariaDB.
- Preview, detección y normalización asistida son read-only. La escritura exige validación, confirmación y el servicio oficial correspondiente.
- Conserva compatibilidad con Flask, MariaDB y Docker Compose. Revisa modelos y heads antes de decidir si hace falta una migración.
- Cambios funcionales requieren pruebas del área. Preserva cambios ajenos del working tree.

## Qué leer según la tarea

Empieza por [`docs/DOCUMENTATION_INDEX.md`](docs/DOCUMENTATION_INDEX.md) si el dominio no es evidente.

| Si la tarea toca… | Lee antes de editar |
| --- | --- |
| Estado o trabajo en curso | `docs/ACTIVE_HANDOFF.md` |
| Visión o límites del producto | `docs/PROJECT_CONTEXT.md` |
| Backend, modelos, servicios o migraciones | `backend/AGENTS.md` |
| Schemas o contrato JSON público | `schemas/AGENTS.md` |
| Contratos, aliases, import/export o round-trip | `docs/project-rules/canonical-data-contract-import-update.md` |
| JSON no estándar, detección o generación asistida | regla canónica anterior + `docs/project-rules/phase-5b-universal-json-import-assistant.md` + `docs/project-rules/standard-json-generator-development.md` |
| Confirmación o escritura de import estándar | `docs/project-rules/confirmed-standard-import.md` |
| FIT, GPX, TCX o CSV de entrada | `docs/project-rules/real-file-imports.md` |
| Exportadores o storage generated | `docs/project-rules/exporters.md` |
| Restore de cuenta o backup ZIP | `docs/project-rules/account-restore.md` o `docs/project-rules/full-backup.md` |
| `/api/v1`, Bearer o dispositivos | `docs/project-rules/api-v1.md` |
| Mobile Sync | `docs/project-rules/mobile-sync.md` |
| Companion, packages o deliveries | `docs/project-rules/companion-protocol.md` |
| Jinja, CSS, navegación, dashboard o PWA | `docs/project-rules/web-ui.md` y, para flujo cotidiano, `docs/project-rules/web-daily-driver.md` |
| Cargas por serie | `docs/project-rules/workout-load-entry.md` |
| Drafts, CSRF o idempotencia de sesión web | `docs/project-rules/workout-session-recovery.md` |

Las guías de uso, protocolos detallados, roadmap e historia son contexto frío. Ábrelos solo cuando la regla o el índice los indique.

## Precedencia

Si hay conflicto, aplica este orden:

1. Instrucciones explícitas del usuario y seguridad.
2. JSON Schemas para contratos públicos.
3. Pruebas que codifican el comportamiento vigente.
4. `AGENTS.md` local del directorio afectado.
5. Reglas canónicas aplicables en `docs/project-rules/`.
6. Este archivo.
7. Código actual para detalles de implementación.
8. `docs/ACTIVE_HANDOFF.md`, documentación de producto e historia.

Un handoff o documento histórico nunca puede redefinir un contrato.

## Verificación y terminado

Para documentación solamente, ejecuta como mínimo:

```powershell
git diff --check
git status --short --branch
git diff --stat
git diff --name-only
```

Para backend, sigue además `backend/AGENTS.md`. Una tarea termina cuando el cambio solicitado está implementado, las pruebas proporcionales pasan, no se perdió aislamiento ni privacidad, las rutas documentadas existen y el handoff solo se actualiza si queda estado temporal útil.
