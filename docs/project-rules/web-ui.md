# Regla canónica de Web UI

Aplica a cambios de Jinja, navegación, CSS y flujos web.

1. Conservar Flask/Jinja y mejora progresiva; no añadir un framework frontend sin aprobación.
2. No cambiar contratos de backend por conveniencia visual.
3. Mantener autenticación, autorización, ownership y CSRF en todas las acciones.
4. No mostrar secretos, tokens, paths internos, payloads sensibles ni datos de otros usuarios.
5. La navegación debe ser agrupada, consistente y condicionada por permisos.
6. El dashboard prioriza estado y acciones del día; onboarding no debe desplazar datos existentes.
7. Las acciones destructivas usan POST, CSRF, texto explícito y confirmación.
8. Todo control interactivo debe ser usable por teclado, tener foco visible y objetivo táctil aproximado de 44 px.
9. Inputs usan al menos 16 px en móvil. Las tablas anchas desplazan dentro de un wrapper propio.
10. No usar `overflow-x: hidden` global como arreglo de layouts.
11. Probar como mínimo 360, 390, 430, 768, 1024 y 1366 px cuando cambie estructura responsive.
12. Agregar pruebas ligeras de estructura y rutas; la validación visual manual sigue siendo obligatoria para cambios relevantes.
13. Mantener tema claro y oscuro mediante variables; no depender solo del color para comunicar estado.
14. Usar datos ficticios en QA y no tocar `.env` ni `/data`.

