# Web UI Design System

El sistema visual vive en `backend/app/static/css/app.css` y debe mantenerse pequeño, semántico y compatible con Jinja.

## Fundamentos

- Variables CSS para color, superficies, texto, bordes, espaciado, radios y sombras.
- Espaciado basado en una escala corta; evitar valores aislados sin necesidad.
- Estados con texto además de color: `success`, `warning`, `danger`, `info` y `neutral`.
- Botones y controles con altura mínima de 44 px; inputs de 16 px para evitar zoom involuntario en móviles.
- Tablas dentro de `.table-wrap` o `.table-wrapper`; nunca ocultar overflow global para disimular un layout roto.

## Componentes

- `.app-shell`, `.app-sidebar`, `.app-topbar` y `.app-content` forman el shell autenticado.
- `.card`, `.metric-card`, `.quick-actions`, `.empty-state`, `.alert` y `.status-badge` son bloques reutilizables.
- `.mobile-menu` usa HTML nativo y no requiere JavaScript.
- `.button`, `.button-secondary` y `.button-danger` expresan jerarquía y riesgo.

## Responsive y temas

- Hasta 900 px se simplifican grids y espacios.
- Hasta 650 px se oculta la navegación de escritorio y aparece el menú móvil.
- `prefers-color-scheme: dark` ajusta variables, no duplica componentes.
- `prefers-reduced-motion` elimina transiciones no esenciales.

Los cambios visuales deben conservar HTML semántico, foco visible, contraste y las rutas/acciones existentes.

