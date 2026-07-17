# Instrucciones locales de schemas

Aplican a `schemas/` además del `AGENTS.md` raíz.

- Cada schema versionado es la fuente de verdad del JSON público de su dominio.
- Usa nombres canónicos estables en `snake_case`. Los aliases externos no se agregan como propiedades estándar; pertenecen a normalizadores o al asistente.
- No relajes `required`, tipos, rangos o `additionalProperties` para hacer pasar una fixture concreta sin justificar un cambio de contrato.
- No inventes valores requeridos en generadores ni fixtures. Un preview inválido con errores claros es preferible a datos fabricados.
- Antes de cambiar un schema, localiza importadores, exportadores, generadores, formularios, API, backup/restore y pruebas que consumen ese contrato.
- Un cambio de contrato debe actualizar en el mismo bloque las capas afectadas y sus pruebas de validación/round-trip. Si rompe compatibilidad, exige versión o estrategia explícita.
- Usa solo ejemplos ficticios; nunca copies payloads reales.

Verifica al menos el test del schema/dominio, la suite relacionada y `git diff --check`. Lee `../docs/project-rules/canonical-data-contract-import-update.md` para cambios de contrato y las reglas adicionales que correspondan al importador o exportador afectado.
