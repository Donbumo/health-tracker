# ADR 0001: carga de contexto para agentes

- Estado: aceptada
- Fecha: 2026-07-17

## Contexto

El `AGENTS.md` raíz ordenaba leer varios documentos extensos para cualquier modificación. `AI_WORK_CONTEXT.md`, `PROJECT_CONTEXT.md` y `ACTIVE_HANDOFF.md` mezclaban reglas permanentes, estados de ramas, roadmap e historia, con más de cuarenta mil tokens potenciales antes de inspeccionar código.

## Decisión

El contexto se divide en tres niveles:

- Caliente: `AGENTS.md` raíz y, cuando aplique por jerarquía, `backend/AGENTS.md` o `schemas/AGENTS.md`.
- Tibio: `docs/ACTIVE_HANDOFF.md`, leído solo para estado o continuidad del trabajo.
- Frío: visión, arquitectura, reglas de dominio, guías, protocolos, roadmap e historia, localizados mediante `docs/DOCUMENTATION_INDEX.md`.

El archivo raíz actúa como router y conserva únicamente seguridad, aislamiento por usuario, convenciones, precedencia, verificación y criterios de finalización. Las reglas especializadas se consultan por dominio.

## Consecuencias

- Una tarea pequeña no necesita cargar la visión completa ni el historial.
- Cada regla tiene una fuente canónica y los documentos narrativos deben enlazarla en vez de copiarla.
- El handoff debe reemplazarse, no acumularse.
- Solo se crean `AGENTS.md` locales cuando un árbol tiene reglas claramente distintas.
- Un documento histórico puede explicar una decisión, pero no puede redefinir el contrato vigente.
