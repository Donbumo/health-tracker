# Web UI Homelab

## Alpha 1.0 Web Daily Driver

La entrada autenticada prioriza dashboard diario, onboarding discreto, agenda, borradores y acciones frecuentes. La ruta visible de importación es `/imports`; preferencias viven en `/account/preferences` y ayuda en `/help`. La PWA es opcional y solo cachea assets estáticos: no ofrece offline para datos autenticados.

`/account/system` muestra estado, migración, storage, operaciones propias, si la firma API usa clave independiente y la limitación process-local del rate limiter, sin mostrar valores o paths.

## Recuperación de sesión web

Alpha 0.8.1 añade a la captura de entrenamiento un indicador de borrador, restauración local/servidor, acción para descartarlo y recuperación específica ante CSRF vencido. El botón Guardar se deshabilita durante submit y el borrador local solo se elimina cuando el detalle confirma la misma submission exitosa. Validar a 360/390/430/768/1024/1366 px, claro y oscuro.

## Entrenamientos planificados

La navegación autenticada incluye `Planificados`. La lista y creación son owner-only, responsive y usan POST + CSRF para reprogramar, omitir o cancelar. La UI no permite elegir otro `user_id`.

Alpha 0.8 añade una acción POST + CSRF para preparar una entrega hacia un dispositivo propio con perfil negociado. `/account/devices` muestra versiones, features y deliveries recientes con hash abreviado; nunca muestra token ni package completo.

Health Tracker Alpha 0.6.1 conserva Flask, Jinja y CSS propio. La interfaz está pensada para una instalación privada en LAN o VPN y prioriza los datos diarios, la trazabilidad y las acciones frecuentes.

## Estructura

- Escritorio: barra lateral agrupada y barra superior con contexto de usuario.
- Móvil: cabecera compacta y menú nativo `details/summary`, cerrado al cargar.
- Dashboard: estado diario y acciones rápidas primero; onboarding y operación reciente después.
- Cuenta: datos, backups, dispositivos API y estado del homelab.

La navegación agrupa Inicio, Entrenamiento, Actividad, Nutrición, Salud, Datos y Cuenta. Las opciones administrativas solo se muestran al rol `admin`.

## Estado del homelab

`/account/system` muestra únicamente señales seguras del usuario autenticado: disponibilidad de DB y almacenamiento, versión de migración, versión de app, hora UTC, conteos propios y último backup. No muestra rutas internas, variables de entorno, secretos, logs, tokens ni datos de otros usuarios.

`/account/devices` lista solo dispositivos API del usuario. Revocar exige POST, CSRF y confirmación explícita; también revoca sus sesiones API activas.

## QA responsive

Validar en 360, 390, 430, 768, 1024 y 1366 px:

1. No hay scroll horizontal global.
2. El menú móvil comienza cerrado y sus controles tienen un área táctil mínima aproximada de 44 px.
3. El dashboard diario es visible antes del onboarding.
4. Formularios, alertas y estados vacíos siguen legibles.
5. Las tablas anchas desplazan solo dentro de `.table-wrap` o `.table-wrapper`.
6. Navegación por teclado conserva foco visible.

La interfaz usa el tema del sistema mediante `prefers-color-scheme`. No existe un selector de tema persistente en esta fase.

## Límites

- No es una consola de infraestructura ni sustituye monitoreo externo.
- El estado de almacenamiento es una comprobación de disponibilidad, no expone paths.
- La revocación de dispositivos no permite inspeccionar tokens.
- No se añadió JavaScript de aplicación ni un framework frontend.

