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

En Alpha 1.3, abre **Plan** para administrar rutinas y agenda. Puedes crear o duplicar una rutina, editar nombre/descripción con guardado automático, añadir y ordenar entrenamientos, buscar ejercicios, definir series (reps, carga, modo, RIR/RPE, descanso, tiempo, distancia y notas) y programarlas para una fecha. Semana muestra siete días; Mes usa una cuadrícula sencilla con indicadores y la lista del día seleccionado. Puedes mover o cancelar una programación y regresar a Hoy. Archivar o quitar contenido pide confirmación; un plan con programaciones activas debe resolverlas antes de archivarse, y los archivados se pueden mostrar y restaurar desde el filtro.

En Alpha 1.4, **Hoy** muestra peso, nutrición, pasos y entrenamiento sin llenar la pantalla de formularios. Abre **Salud del día** o usa **Registrar peso**, **Añadir comida** y **Registrar pasos**. Puedes cambiar la fecha, editar o eliminar una medición, organizar comidas como desayuno/comida/cena/snack, buscar o crear alimentos privados, duplicar/mover entradas y corregir pasos. Los campos incompletos se indican y no se inventan macros.

En Alpha 1.5, abre **Ajustes → Health Connect** para una importación opcional y de solo lectura. Elige primero peso, grasa corporal, pasos y, si lo deseas, nutrición; después pulsa **Conectar** y concede solo esos accesos. Masa magra y agua corporal permanecen deshabilitadas mientras Health Tracker no tenga campos con la misma semántica. Si falta Health Connect, la tarjeta indica si el dispositivo no es compatible o si debes instalar/actualizar el proveedor.

En Alpha 1.6, abre **Ajustes → Fuentes externas**. **Comprobar datos de báscula** muestra únicamente tipos, conteos, fechas truncadas y orígenes genéricos; no muestra tus valores. Puedes confirmar localmente un origen como báscula genérica, Xiaomi S400, otro dispositivo o marcar que no estás seguro, y cambiar/eliminar esa confirmación después.

La sección Xiaomi S400 es experimental. **Buscar** solicita Bluetooth solo en ese momento, dura como máximo 20 segundos y exige elegir un dispositivo. **Inspeccionar dispositivo** enumera servicios sin escribir características. En debug puedes seleccionar un notify/indicate y consentir una captura privada cifrada; borrarla no olvida el dispositivo y exportarla requiere una segunda advertencia/elección. No existe **Guardar medición**: peso y composición BLE siguen deshabilitados hasta validar el protocolo con varias capturas físicas.

**Sincronizar ahora** lee cambios; **Pausar** conserva datos y permisos; **Desconectar sin borrar datos** detiene la integración sin modificar Health Connect. **Administrar acceso** abre los controles del sistema. El permiso de segundo plano es separado y opcional: sin él, la app sigue importando al abrirse o al pedir una sincronización. Revocar un tipo no cierra sesión ni borra lo ya importado.

Hoy y Progreso muestran la etiqueta Health Connect junto a peso o pasos. El total de pasos se calcula por día y zona sin sumar aplicaciones ni combinarlo con el total manual; si existe una corrección manual, se presenta esa y se conserva el agregado importado para auditoría. Nutrición solo se importa cuando la comida tiene fecha, tipo, nombre y nutrientes representables. Si editas un peso o una comida importados, se convierten en copia del usuario y Health Connect deja de sobrescribirlos.

**Borrar datos importados** requiere una confirmación independiente y elimina solo recursos todavía vinculados a Health Connect, también encolando la eliminación del servidor. No borra registros manuales, copias editadas, sesiones, rutinas ni datos que viven en Health Connect. La primera importación revisa hasta 30 días; después usa cambios incrementales y dedupe. Los datos aparecen desde Room aunque el servidor esté offline y se envían cuando vuelve la red.

Todo se guarda primero en este dispositivo. Puedes cerrar la app, abrirla sin red y continuar; al recuperar conectividad, WorkManager sincroniza automáticamente. Los estados muestran guardado local, pendiente, sincronizando, sincronizado o atención. Si hay conflicto, Salud del día permite usar servidor, reintentar, duplicar una medición/comida o cancelar el cambio. **Progreso → Salud** ofrece peso, pasos, calorías y macros con resumen textual; son tendencias descriptivas, no diagnóstico ni causalidad.

Todo funciona primero sobre la copia local. **Guardado local, pendiente** significa que no se perdió el cambio; al recuperar red se envía en orden. Programar dos veces por una doble pulsación conserva una sola identidad; mover varias veces antes de sincronizar conserva la última fecha segura, y crear y cancelar antes del primer envío no deja una programación remota. Si otra edición cambió la misma revisión, Plan muestra el recurso, las revisiones y un resumen sanitizado, con acciones **Usar servidor**, **Reintentar copia local**, **Duplicar** cuando corresponde o **Cancelar cambio local** en vez de sobrescribir silenciosamente.

Al programar para la fecha operativa de la cuenta, la tarjeta aparece inmediatamente en Hoy desde Room, aunque todavía no haya red. Al terminar la descarga y el ACK, Hoy muestra **Descargado · disponible sin conexión** y habilita **Empezar** sin pedir una sincronización manual. Si la rutina cambia antes de iniciar, la app puede reemplazar el package por la revisión vigente; nunca modifica ni sustituye un draft activo y muestra el conflicto para que decidas. Un entrenamiento descargado puede iniciarse, editarse y completarse offline, incluso después de cerrar la app o reiniciar el proceso. Peso, unidad, reps, RIR, RPE, notas, descanso, duración y distancia se guardan automáticamente; **Completar serie** y **Finalizar entrenamiento** siguen siendo acciones explícitas.

Hoy separa **Sin conexión**, **Guardado en este dispositivo**, **Sincronización pendiente**, **Sincronizando**, **Sincronizado** y **Requiere atención**. Al volver la red, la app renueva la sesión y procesa START, progreso y completion en orden. El botón **Sincronizar ahora** es solo un respaldo: login, descarga, cambios relevantes, foreground, reconexión y WorkManager ya disparan sync automática. No descartes un borrador corrupto hasta revisar su motivo; un fallo de red por sí solo nunca lo vuelve corrupto.

En Ajustes, **Cambiar servidor** exige confirmación, invalida los tokens activos y conserva la copia Room anterior aislada; después confirma la nueva URL e inicia sesión. **Cerrar sesión en este teléfono** elimina esa cuenta local, **Cerrar todas las sesiones API** revoca todas las sesiones, **Revocar este dispositivo** bloquea sus sesiones y **Borrar solo datos locales** no cambia el servidor. Las acciones de mayor alcance exigen confirmación adicional. **Compartir diagnóstico sanitizado** entrega solo metadatos y conteos de Health Connect, nunca mediciones ni tokens.

Consulta [Instalación Android](ANDROID_INSTALLATION.md) y [Android Companion](ANDROID_COMPANION.md). No hay conexión con reloj o Bluetooth, ni escritura hacia Health Connect.

### Historial y Progreso en Android

**Historial** muestra primero las sesiones guardadas, incluso sin red. Permite filtrar por fechas o ejercicio, cargar páginas anteriores y abrir un detalle read-only con ejercicios, series, carga, reps, RIR/RPE, descanso y notas propias. Una sesión terminada offline aparece como pendiente y se reconcilia sin duplicarse.

**Progreso** permite elegir 7, 30, 90, 180 o 365 días, o todo el historial. Resume sesiones, días, series, volumen comparable y duración. Cada ejercicio muestra carga, volumen, tendencia y mejores marcas; las gráficas incluyen un resumen textual. “Datos insuficientes” o “no comparable” significa que la app evitó mezclar modos incompatibles, no que haya perdido la sesión.

## Datos y privacidad

Cada dato pertenece al usuario autenticado. Los previews de importación no escriben en la base. Un export JSON sirve para portabilidad; un backup ZIP incluye también archivos verificables. Ninguno incluye contraseñas ni tokens.

Consulta [Primeros pasos](GETTING_STARTED.md), [Flujo diario](DAILY_WORKFLOW.md), [Import Hub](IMPORT_HUB.md) y [Solución de problemas](TROUBLESHOOTING_USER.md).
