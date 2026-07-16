# Regla canónica: Web Daily Driver

Aplica a Jinja, rutas web, formularios, dashboard, navegación y PWA.

## Invariantes

- El usuario efectivo siempre proviene de la sesión; no se acepta `user_id` seleccionable.
- Las vistas owner-only responden 404 ante recursos ajenos.
- Una función cotidiana tiene una sola ruta visible; rutas anteriores pueden conservarse por compatibilidad.
- El dashboard prioriza hoy, borrador, siguiente acción y datos recientes.
- No se muestran IDs DB, payloads crudos, tokens, paths internos ni secretos.
- Toda mutación web usa POST y CSRF. JavaScript mejora la experiencia, pero no sustituye la validación servidor.
- Formularios y estados deben seguir siendo utilizables a 360 px, con foco visible y objetivos táctiles cercanos a 44 px.

## Importaciones

`/imports` es la entrada visible. El registro solo declara capacidades existentes; parsing, validación, deduplicación y commit permanecen en los servicios oficiales. Preview no escribe dominio y confirmación requiere token firmado owner-bound.

## PWA

El service worker solo puede cachear GET del mismo origen bajo `/static/`. Nunca cachea navegación autenticada, API, formularios POST, tokens ni payloads. La app debe funcionar si el service worker no se instala.

## Entrega

Ejecutar compilación, pruebas específicas, suite completa, `flask db check`, Docker/MariaDB aislado cuando corresponda, `git diff --check` y QA visual real. No afirmar WCAG completa ni sign-off visual no realizado.
