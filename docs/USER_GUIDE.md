# Guía de usuario

Health Tracker Alpha 1.0 es una aplicación privada y self-hosted para registrar salud y entrenamiento desde navegador. No sustituye evaluación médica.

## Navegación cotidiana

- **Hoy** resume el entrenamiento planeado, borradores, actividad reciente y datos del día.
- **Entrenar** abre agenda, captura y progreso.
- **Rutinas** permite crear una rutina guiada, importar, duplicar y consultar versiones.
- **Historial** contiene sesiones e importaciones.
- **Salud y actividad** agrupa peso, nutrición, energía, actividades, rutas y laboratorios.
- **Datos** separa importar de exportar, respaldar y restaurar.
- **Cuenta** contiene preferencias, dispositivos y estado homelab.

En móvil, abre **Menú** desde la barra superior. El menú está cerrado al cargar para dejar visible el contenido diario.

## Android Companion

El cliente Android permite iniciar sesión contra una instancia privada, descargar el entrenamiento de hoy, ejecutarlo desde el teléfono y sincronizar el resultado. Los borradores y operaciones pendientes permanecen en el dispositivo si se pierde la red. Antes de usar HTTP local en debug debe habilitarse de forma explícita; para uso normal configura HTTPS.

Al terminar la descarga y el ACK, Hoy muestra **Descargado · disponible sin conexión** y habilita **Empezar** sin pedir una sincronización manual. Un entrenamiento descargado puede iniciarse, editarse y completarse offline, incluso después de cerrar la app o reiniciar el proceso. Peso, unidad, reps, RIR, RPE, notas, descanso, duración y distancia se guardan automáticamente; **Completar serie** y **Finalizar entrenamiento** siguen siendo acciones explícitas.

Hoy separa **Sin conexión**, **Guardado en este dispositivo**, **Sincronización pendiente**, **Sincronizando**, **Sincronizado** y **Requiere atención**. Al volver la red, la app renueva la sesión y procesa START, progreso y completion en orden. El botón **Sincronizar ahora** es solo un respaldo: login, descarga, cambios relevantes, foreground, reconexión y WorkManager ya disparan sync automática. No descartes un borrador corrupto hasta revisar su motivo; un fallo de red por sí solo nunca lo vuelve corrupto.

En Ajustes, **Cerrar sesión en este teléfono** elimina esa cuenta local, **Cerrar todas las sesiones API** revoca todas las sesiones, **Revocar este dispositivo** bloquea sus sesiones y **Borrar solo datos locales** no cambia el servidor. Las tres acciones de mayor alcance exigen confirmación adicional.

Consulta [Instalación Android](ANDROID_INSTALLATION.md) y [Android Companion](ANDROID_COMPANION.md). No hay conexión con reloj o Bluetooth.

### Historial y Progreso en Android

**Historial** muestra primero las sesiones guardadas, incluso sin red. Permite filtrar por fechas o ejercicio, cargar páginas anteriores y abrir un detalle read-only con ejercicios, series, carga, reps, RIR/RPE, descanso y notas propias. Una sesión terminada offline aparece como pendiente y se reconcilia sin duplicarse.

**Progreso** permite elegir 7, 30, 90, 180 o 365 días, o todo el historial. Resume sesiones, días, series, volumen comparable y duración. Cada ejercicio muestra carga, volumen, tendencia y mejores marcas; las gráficas incluyen un resumen textual. “Datos insuficientes” o “no comparable” significa que la app evitó mezclar modos incompatibles, no que haya perdido la sesión.

## Datos y privacidad

Cada dato pertenece al usuario autenticado. Los previews de importación no escriben en la base. Un export JSON sirve para portabilidad; un backup ZIP incluye también archivos verificables. Ninguno incluye contraseñas ni tokens.

Consulta [Primeros pasos](GETTING_STARTED.md), [Flujo diario](DAILY_WORKFLOW.md), [Import Hub](IMPORT_HUB.md) y [Solución de problemas](TROUBLESHOOTING_USER.md).
