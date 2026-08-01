package io.healthtracker.companion.ui

import android.content.Intent
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardType
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

private const val LOCATION_NOTICE = "Las rutas pueden revelar ubicaciones sensibles. Elige si conservarlas, recortar extremos o descartarlas."

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ActivitiesScreen(viewModel: CompanionViewModel, close: () -> Unit, openDetail: (String) -> Unit) {
    val context = LocalContext.current
    val activities by viewModel.activities.collectAsState()
    val imports by viewModel.activityImports.collectAsState()
    val duplicates by viewModel.activityDuplicates.collectAsState()
    val connected by viewModel.connected.collectAsState()
    var routePolicy by remember { mutableStateOf("redact") }
    var redactStart by remember { mutableStateOf("200") }
    var redactEnd by remember { mutableStateOf("200") }
    var discipline by remember { mutableStateOf("all") }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        val filename = context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) cursor.getString(0) else null
        } ?: uri.lastPathSegment ?: "activity.fit"
        viewModel.importActivity(uri, filename, routePolicy,
            if (routePolicy == "redact") redactStart.toIntOrNull() ?: 0 else 0,
            if (routePolicy == "redact") redactEnd.toIntOrNull() ?: 0 else 0)
    }
    LaunchedEffect(connected) { if (connected) viewModel.refreshActivities() }
    Scaffold(
        topBar = { TopAppBar(title = { Text("Actividades") }, navigationIcon = { TextButton(onClick = close) { Text("Atrás") } }) },
        floatingActionButton = { ExtendedFloatingActionButton(onClick = { picker.launch(arrayOf("application/octet-stream", "application/gpx+xml", "application/xml", "text/xml")) }) { Text("Importar FIT/GPX/TCX") } },
    ) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp), contentPadding = PaddingValues(vertical = 16.dp, horizontal = 0.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item {
                Text(LOCATION_NOTICE, style = MaterialTheme.typography.bodySmall)
                Text(if (connected) "Conectado; la interpretación autoritativa se hace en tu servidor." else "Offline: puedes seleccionar, validar y encolar archivos.")
            }
            item {
                Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Privacidad para la próxima ruta", style = MaterialTheme.typography.titleMedium)
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        listOf("keep" to "Conservar", "redact" to "Recortar extremos", "drop" to "Descartar").forEach { (value, label) ->
                            FilterChip(selected = routePolicy == value, onClick = { routePolicy = value }, label = { Text(label) })
                        }
                    }
                    if (routePolicy == "redact") Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(redactStart, { redactStart = it.filter(Char::isDigit).take(5) }, label = { Text("Inicio (m)") },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), singleLine = true, modifier = Modifier.weight(1f))
                        OutlinedTextField(redactEnd, { redactEnd = it.filter(Char::isDigit).take(5) }, label = { Text("Final (m)") },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), singleLine = true, modifier = Modifier.weight(1f))
                    }
                } }
            }
            if (imports.any { it.state !in setOf("applied", "cancelled") }) item { Text("Imports pendientes", style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() }) }
            items(imports.filter { it.state !in setOf("applied", "cancelled") }, key = { it.publicId }) { item ->
                Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    Text(item.displayName, style = MaterialTheme.typography.titleMedium)
                    Text("${(item.detectedFormat ?: "por detectar").uppercase()} · ${item.sizeBytes} bytes · ${item.sha256.take(12)}")
                    Text(activityImportState(item.state), style = MaterialTheme.typography.labelLarge)
                    if (item.warningsJson != "[]") Text("La inspección contiene advertencias; revísalas antes de confirmar.", style = MaterialTheme.typography.bodySmall)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (item.state == "ready_to_confirm") Button(onClick = { viewModel.confirmActivityImport(item.publicId) }) { Text("Confirmar") }
                        if (item.state in setOf("retry", "failed", "source_lost")) OutlinedButton(onClick = { viewModel.retryActivityImport(item.publicId) }) { Text("Reintentar") }
                        TextButton(onClick = { viewModel.cancelActivityImport(item.publicId) }) { Text("Cancelar") }
                    }
                } }
            }
            item {
                Text("Actividades recientes", style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() })
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("all", "running", "cycling", "walking", "strength").forEach { value ->
                        FilterChip(selected = discipline == value, onClick = { discipline = value }, label = { Text(if (value == "all") "Todas" else value) })
                    }
                }
                if (duplicates.isNotEmpty()) Text("${duplicates.size} posibles duplicados requieren revisión; nunca se fusionan automáticamente.")
            }
            val visible = activities.filter { discipline == "all" || it.discipline == discipline }
            if (visible.isEmpty()) item { Text("No hay actividades cacheadas para este filtro.") }
            items(visible, key = { it.publicId }) { activity ->
                Card(onClick = { openDetail(activity.publicId) }, modifier = Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(activity.title ?: humanDiscipline(activity.discipline), style = MaterialTheme.typography.titleMedium)
                    Text(activity.startedAt)
                    Text(listOfNotNull(activity.distanceMeters?.let { "$it m" }, activity.durationSeconds?.let { "${it / 60} min" }).joinToString(" · "))
                    Text("${activity.sourceFormat.uppercase()} · ${if (activity.syncStatus == "synced") "guardada" else "pendiente"}", style = MaterialTheme.typography.bodySmall)
                } }
            }
            item { Spacer(Modifier.height(80.dp)) }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ActivityDetailScreen(viewModel: CompanionViewModel, close: () -> Unit) {
    val context = LocalContext.current
    val activity by viewModel.selectedActivity.collectAsState()
    val laps by viewModel.activityLaps.collectAsState()
    val seriesMetadata by viewModel.activitySeriesMetadata.collectAsState()
    val route by viewModel.activityRoute.collectAsState()
    val routePoints by viewModel.activityRoutePoints.collectAsState()
    val metricPoints by viewModel.activityMetricSeries.collectAsState()
    val candidates by viewModel.activityPlanCandidates.collectAsState()
    val planLink by viewModel.activityPlanLink.collectAsState()
    val comparison by viewModel.activityComparison.collectAsState()
    var metric by remember { mutableStateOf("heartRate") }
    var confirmArchive by remember { mutableStateOf(false) }
    var confirmRouteRemoval by remember { mutableStateOf(false) }
    Scaffold(topBar = { TopAppBar(title = { Text("Detalle de actividad") }, navigationIcon = { TextButton(onClick = close) { Text("Atrás") } }) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp), contentPadding = PaddingValues(vertical = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            val value = activity
            if (value == null) item { Text("Cargando detalle guardado…") } else {
                item {
                    Text(value.title ?: humanDiscipline(value.discipline), style = MaterialTheme.typography.headlineSmall, modifier = Modifier.semantics { heading() })
                    Text(value.startedAt)
                    Text("Duración: ${value.durationSeconds?.let { "${it / 60} min" } ?: "sin dato"} · Distancia: ${value.distanceMeters ?: "sin dato"} m")
                    Text("Fuente: ${value.sourceFormat.uppercase()}${value.sourceDevice?.let { " · ${it.take(80)}" }.orEmpty()}")
                    Text("El archivo original permanece privado en el servidor; esta pantalla solo conserva metadatos y caché reducida.", style = MaterialTheme.typography.bodySmall)
                }
                item {
                    Text("Vueltas", style = MaterialTheme.typography.titleLarge)
                    if (laps.isEmpty()) Text("Sin laps detectados.") else laps.take(30).forEach { lap -> Text("Lap ${lap.lapIndex + 1}: ${lap.durationSeconds ?: "—"} s · ${lap.distanceMeters ?: "—"} m") }
                }
                item {
                    Text("Gráfica local", style = MaterialTheme.typography.titleLarge)
                    Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                        listOf("heartRate" to "FC", "speed" to "Velocidad", "cadence" to "Cadencia", "power" to "Potencia").forEach { (key, label) ->
                            FilterChip(selected = metric == key, onClick = { metric = key; viewModel.selectActivityMetric(key) }, label = { Text(label) })
                        }
                    }
                    SeriesChart(metricPoints, "$metric en el tiempo; ${metricPoints.size} puntos reducidos")
                    Text(if (metricPoints.isEmpty()) "No hay muestras para esta métrica." else "Rango ${metricPoints.minOrNull()} a ${metricPoints.maxOrNull()}; ${seriesMetadata?.sampleCount ?: metricPoints.size.toLong()} muestras de origen.")
                }
                item {
                    Text("Ruta local", style = MaterialTheme.typography.titleLarge)
                    Text(LOCATION_NOTICE)
                    if (route?.visibilityState == "available" && routePoints.isNotEmpty()) {
                        RouteChart(routePoints)
                        Text("Línea local con inicio y final genéricos · ${route?.pointCount ?: routePoints.size} puntos. No se consulta ningún mapa externo.")
                        OutlinedButton(onClick = { confirmRouteRemoval = true }) { Text("Eliminar ruta") }
                    } else Text(if (route?.visibilityState == "removed") "La ruta fue eliminada; resumen y laps siguen disponibles." else "Actividad indoor o sin ruta disponible.")
                }
                item {
                    Text("Plan contra realidad", style = MaterialTheme.typography.titleLarge)
                    if (planLink != null) Text("Vínculo: ${planLink?.state}")
                    comparison?.let { Text("Comparación descriptiva: ${it.status}\n${it.summaryJson.take(500)}") }
                    if (candidates.isEmpty() && planLink == null) Text("No hay candidatos. Faltan datos o no existe un entrenamiento cercano.")
                    candidates.take(5).forEach { candidate -> PlanCandidate(candidate,
                        confirm = { id -> viewModel.decideActivityPlan(id, "confirm") },
                        reject = { id -> viewModel.decideActivityPlan(id, "reject") })
                    }
                }
                item {
                    Text("Exportar", style = MaterialTheme.typography.titleLarge)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = { viewModel.exportSelectedActivity("json", false) { context.startActivity(Intent.createChooser(it, "Exportar actividad")) } }) { Text("JSON sin ruta") }
                        OutlinedButton(onClick = { viewModel.exportSelectedActivity("gpx", true) { context.startActivity(Intent.createChooser(it, "Exportar GPX")) } }, enabled = route?.visibilityState == "available") { Text("GPX visible") }
                    }
                    TextButton(onClick = { confirmArchive = true }) { Text("Archivar actividad") }
                }
            }
        }
    }
    if (confirmArchive) AlertDialog(onDismissRequest = { confirmArchive = false }, title = { Text("¿Archivar actividad?") }, text = { Text("Se ocultará de recientes; no elimina el archivo ni la ruta.") }, confirmButton = { Button(onClick = { confirmArchive = false; viewModel.archiveSelectedActivity(close) }) { Text("Archivar") } }, dismissButton = { TextButton(onClick = { confirmArchive = false }) { Text("Cancelar") } })
    if (confirmRouteRemoval) AlertDialog(onDismissRequest = { confirmRouteRemoval = false }, title = { Text("¿Eliminar la ruta?") }, text = { Text("La ubicación visible se eliminará de forma irreversible. Resumen, laps y actividad se conservan.") }, confirmButton = { Button(onClick = { confirmRouteRemoval = false; viewModel.removeSelectedActivityRoute() }) { Text("Eliminar ruta") } }, dismissButton = { TextButton(onClick = { confirmRouteRemoval = false }) { Text("Cancelar") } })
}

@Composable
private fun SeriesChart(values: List<Double>, description: String) {
    Canvas(Modifier.fillMaxWidth().height(150.dp).semantics { contentDescription = description }) {
        if (values.size < 2) return@Canvas
        val min = values.minOrNull() ?: return@Canvas; val max = values.maxOrNull() ?: return@Canvas; val span = (max - min).takeIf { it > 0 } ?: 1.0
        values.zipWithNext().forEachIndexed { index, (left, right) ->
            val x1 = size.width * index / (values.size - 1); val x2 = size.width * (index + 1) / (values.size - 1)
            drawLine(Color(0xFF006C4C), Offset(x1, size.height * (1f - ((left - min) / span).toFloat())), Offset(x2, size.height * (1f - ((right - min) / span).toFloat())), strokeWidth = 4f)
        }
    }
}

@Composable
private fun RouteChart(points: List<Pair<Double, Double>>) {
    Canvas(Modifier.fillMaxWidth().height(190.dp).semantics { contentDescription = "Ruta dibujada localmente; inicio y final indicados también en texto" }) {
        if (points.size < 2) return@Canvas
        val minLat = points.minOf { it.first }; val maxLat = points.maxOf { it.first }; val minLon = points.minOf { it.second }; val maxLon = points.maxOf { it.second }
        fun map(point: Pair<Double, Double>) = Offset((((point.second - minLon) / ((maxLon - minLon).takeIf { it > 0 } ?: 1.0)) * size.width).toFloat(), (((maxLat - point.first) / ((maxLat - minLat).takeIf { it > 0 } ?: 1.0)) * size.height).toFloat())
        points.zipWithNext().forEach { (a, b) -> drawLine(Color(0xFF006C4C), map(a), map(b), strokeWidth = 5f) }
        drawCircle(Color.Black, 8f, map(points.first())); drawCircle(Color.Gray, 8f, map(points.last()))
    }
}

@Composable
private fun PlanCandidate(candidate: JsonObject, confirm: (String) -> Unit, reject: (String) -> Unit) {
    val id = candidate["planned_workout_id"]?.jsonPrimitive?.content ?: return
    val score = candidate["evidence"]?.jsonObject?.get("score")?.jsonPrimitive?.doubleOrNull
    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
        Text(candidate["title"]?.jsonPrimitive?.content ?: "Entrenamiento planeado", style = MaterialTheme.typography.titleSmall)
        Text("Fecha ${candidate["scheduled_for_date"]?.jsonPrimitive?.content ?: "—"} · evidencia ${score?.let { "${(it * 100).toInt()} %" } ?: "insuficiente"}")
        Text("Sugerencia descriptiva; requiere tu confirmación.", style = MaterialTheme.typography.bodySmall)
        Row { Button(onClick = { confirm(id) }) { Text("Confirmar") }; TextButton(onClick = { reject(id) }) { Text("Rechazar") } }
    } }
}

private fun activityImportState(value: String) = when (value) {
    "pending_upload" -> "Pendiente de red"; "uploading" -> "Subiendo"; "ready_to_confirm" -> "Inspeccionada; confirma para escribir"
    "retry" -> "Reintentará con backoff"; "failed" -> "Falló la validación"; "source_lost" -> "Se perdió el archivo o permiso"; else -> value
}
private fun humanDiscipline(value: String) = when (value) { "running" -> "Carrera"; "cycling" -> "Ciclismo"; "walking" -> "Caminata"; "strength" -> "Fuerza"; else -> "Actividad" }
