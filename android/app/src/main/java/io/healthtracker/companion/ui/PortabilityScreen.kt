package io.healthtracker.companion.ui

import android.content.Intent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import io.healthtracker.companion.core.database.PortableExportJobEntity
import io.healthtracker.companion.core.database.PortableDownloadEntity
import io.healthtracker.companion.core.database.PortableImportJobEntity
import io.healthtracker.companion.core.database.PortableImportPlanEntity
import io.healthtracker.companion.core.database.PortableInspectionEntity
import io.healthtracker.companion.core.portability.PORTABLE_HEALTH_WARNING
import io.healthtracker.companion.core.portability.PortableExportRequest

private val portableSections = linkedMapOf(
    "settings" to "Preferencias no sensibles",
    "exercises" to "Ejercicios personalizados",
    "plans" to "Planes y rutinas",
    "workouts" to "Entrenamientos planeados",
    "schedules" to "Programaciones",
    "sessions" to "Sesiones completadas",
    "session_exercises" to "Ejercicios realizados",
    "sets" to "Series realizadas",
    "body_stats" to "Peso y medidas corporales",
    "nutrition_entries" to "Nutrición",
    "custom_foods" to "Alimentos personalizados",
    "steps" to "Pasos",
    "goals" to "Objetivos",
    "reminder_rules" to "Recordatorios y quiet hours",
    "external_sources" to "Procedencia externa sanitizada",
)

@Composable
fun DataPrivacyScreen(viewModel: CompanionViewModel, onBack: () -> Unit) {
    val context = LocalContext.current
    val exports by viewModel.portableExports.collectAsState()
    val imports by viewModel.portableImports.collectAsState()
    val inspections by viewModel.portableInspections.collectAsState()
    val plans by viewModel.portablePlans.collectAsState()
    val downloads by viewModel.portableDownloads.collectAsState()
    val connected by viewModel.connected.collectAsState()
    var selected by remember { mutableStateOf(portableSections.keys.toSet()) }
    var attachments by remember { mutableStateOf(false) }
    var profile by remember { mutableStateOf(false) }
    var dateFrom by remember { mutableStateOf("") }
    var dateTo by remember { mutableStateOf("") }
    var saveExportId by remember { mutableStateOf<String?>(null) }

    val openPackage = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        val persisted = runCatching {
            context.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }.isSuccess
        viewModel.inspectPortablePackage(uri, persisted)
    }
    val savePackage = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/vnd.health-tracker.portable+zip")) { uri ->
        val exportId = saveExportId
        if (uri != null && exportId != null) viewModel.savePortableExport(exportId, uri)
        saveExportId = null
    }

    LazyColumn(
        Modifier.fillMaxSize().padding(horizontal = 20.dp).testTag("data_privacy_screen"),
        contentPadding = PaddingValues(vertical = 20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text("Datos y privacidad", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.semantics { heading() })
                OutlinedButton(onClick = onBack) { Text("Volver") }
            }
        }
        item {
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Archivo de salud", style = MaterialTheme.typography.titleLarge)
                Text(PORTABLE_HEALTH_WARNING)
                Text("Guárdalo en un lugar seguro. SHA-256 verifica integridad, pero no demuestra quién creó el paquete.", style = MaterialTheme.typography.bodySmall)
                Text("La app no usa almacenamiento público ni solicita acceso amplio; selección y guardado usan el selector del sistema.", style = MaterialTheme.typography.bodySmall)
            } }
        }
        item { Text("Exportar mis datos", style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() }) }
        portableSections.forEach { (key, label) ->
            item(key) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(checked = key in selected, onCheckedChange = { checked -> selected = if (checked) selected + key else selected - key })
                    Text(label)
                }
            }
        }
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) { Text("Perfil identificable"); Text("Incluye nombre visible y email; apagado por defecto.", style = MaterialTheme.typography.bodySmall) }
                Switch(profile, onCheckedChange = { profile = it })
            }
        }
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) { Text("Attachments"); Text("Solo archivos propios verificados; apagado por defecto.", style = MaterialTheme.typography.bodySmall) }
                Switch(attachments, onCheckedChange = { attachments = it })
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(dateFrom, { dateFrom = it }, label = { Text("Desde YYYY-MM-DD") }, modifier = Modifier.weight(1f), singleLine = true)
                OutlinedTextField(dateTo, { dateTo = it }, label = { Text("Hasta YYYY-MM-DD") }, modifier = Modifier.weight(1f), singleLine = true)
            }
        }
        item {
            Text(
                "Estimación: ${selected.size + (if (profile) 1 else 0) + (if (attachments) 1 else 0)} secciones; el servidor calculará records y tamaño exactos.",
                style = MaterialTheme.typography.bodySmall,
            )
            Button(
                onClick = {
                    val sections = selected + (if (profile) setOf("profile") else emptySet()) + (if (attachments) setOf("attachments") else emptySet())
                    viewModel.requestPortableExport(PortableExportRequest(sections, dateFrom.ifBlank { null }, dateTo.ifBlank { null }, attachments, profile))
                },
                enabled = selected.isNotEmpty() || profile || attachments,
                modifier = Modifier.fillMaxWidth().testTag("request_portable_export"),
            ) { Text(if (connected) "Solicitar exportación" else "Guardar solicitud offline") }
        }
        item { Text("Importar paquete", style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() }) }
        item {
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Seleccionar .htpack")
                Text("La selección solo inicia una inspección local; nunca importa datos directamente.", style = MaterialTheme.typography.bodySmall)
                Button(onClick = { openPackage.launch(arrayOf("application/vnd.health-tracker.portable+zip", "application/zip", "application/octet-stream")) }, modifier = Modifier.fillMaxWidth()) { Text("Seleccionar paquete") }
            } }
        }
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text("Exportaciones recientes", style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() })
                OutlinedButton(onClick = viewModel::refreshPortability) { Text("Actualizar") }
            }
        }
        if (exports.isEmpty()) item { Text("Todavía no hay exportaciones.") }
        items(exports, key = { "export:${it.publicId}" }) { item -> ExportCard(item, downloads.firstOrNull { it.exportPublicId == item.publicId }, viewModel, onSave = {
            saveExportId = item.publicId; savePackage.launch("health-tracker-${item.publicId}.htpack")
        }, onShare = {
            runCatching { context.startActivity(Intent.createChooser(viewModel.sharePortableIntent(item.publicId), "Compartir paquete de salud")) }
        }) }
        item { Text("Importaciones recientes", style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() }) }
        if (imports.isEmpty()) item { Text("Todavía no hay importaciones.") }
        items(imports, key = { "import:${it.publicId}" }) { item ->
            ImportCard(
                item,
                inspections.firstOrNull { it.importPublicId == item.publicId },
                plans.firstOrNull { it.importPublicId == item.publicId },
                viewModel,
                connected,
            )
        }
    }
}

@Composable
private fun ExportCard(item: PortableExportJobEntity, download: PortableDownloadEntity?, viewModel: CompanionViewModel, onSave: () -> Unit, onShare: () -> Unit) {
    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Exportación ${item.publicId.take(8)}…", style = MaterialTheme.typography.titleMedium)
        Text("Estado: ${humanPortableState(item.state)} · ${item.sizeBytes?.let(::formatBytes) ?: "tamaño pendiente"}")
        item.sha256?.let { Text("SHA-256: ${it.take(12)}…", style = MaterialTheme.typography.bodySmall) }
        if (item.state == "ready") {
            val verified = download?.state == "verified"
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { viewModel.downloadPortableExport(item.publicId) }) { Text("Descargar y verificar") }
                OutlinedButton(onClick = onSave, enabled = verified) { Text("Guardar") }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onShare, enabled = verified) { Text("Compartir") }
                OutlinedButton(onClick = { viewModel.deleteLocalPortableExport(item.publicId) }, enabled = verified) { Text("Borrar local") }
                OutlinedButton(onClick = { viewModel.deleteServerPortableExport(item.publicId) }) { Text("Borrar servidor") }
            }
            if (!verified) Text("Guardar y compartir se habilitan después de verificar el SHA-256 local.", style = MaterialTheme.typography.bodySmall)
        } else if (item.state in setOf("requested", "preparing")) {
            OutlinedButton(onClick = { viewModel.cancelPortableExport(item.publicId) }) { Text("Cancelar") }
        }
    } }
}

@Composable
private fun ImportCard(
    item: PortableImportJobEntity,
    inspection: PortableInspectionEntity?,
    plan: PortableImportPlanEntity?,
    viewModel: CompanionViewModel,
    connected: Boolean,
) {
    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Importación ${item.publicId.take(8)}…", style = MaterialTheme.typography.titleMedium)
        Text("Estado: ${humanPortableState(item.state)} · ${item.sizeBytes?.let(::formatBytes) ?: "tamaño pendiente"}")
        item.packageSha256?.let { Text("SHA-256: ${it.take(12)}…", style = MaterialTheme.typography.bodySmall) }
        Text("Secciones: ${item.sectionsJson}", style = MaterialTheme.typography.bodySmall)
        Text("Conteos: ${item.countsJson}", style = MaterialTheme.typography.bodySmall)
        inspection?.let {
            Text("Formato ${it.formatVersion} · integridad ${it.integrity} · autenticidad ${it.authenticity}", style = MaterialTheme.typography.bodySmall)
            if (it.warningsJson != "[]") Text("Advertencias: ${it.warningsJson}", style = MaterialTheme.typography.bodySmall)
        }
        plan?.let { Text("Simulación: ${it.summaryJson}", style = MaterialTheme.typography.bodySmall) }
        when (item.state) {
            "local_inspection_ready" -> Button(onClick = { viewModel.uploadPortableImport(item.publicId) }, enabled = connected) { Text(if (connected) "Subir y simular" else "Pendiente de conexión") }
            "inspection_ready", "awaiting_confirmation" -> {
                Text("Revisa conflictos y conserva el destino cuando no haya una actualización segura.", style = MaterialTheme.typography.bodySmall)
                OutlinedButton(onClick = { viewModel.resolvePortableConflictsSafely(item.publicId) }) { Text("Conservar destino en conflictos") }
                Button(onClick = { viewModel.applyPortableImport(item.publicId) }) {
                    Text(if (connected) "Confirmar importación" else "Confirmar y aplicar al reconectar")
                }
            }
        }
        if (item.state !in setOf("importing", "completed", "completed_with_skips")) {
            if (item.syncStatus == "pending_upload") {
                OutlinedButton(onClick = { viewModel.deleteLocalPortableImport(item.publicId) }) { Text("Eliminar inspección local") }
            } else {
                OutlinedButton(onClick = { viewModel.deleteServerPortableImport(item.publicId) }) { Text("Eliminar temporal") }
            }
        }
    } }
}

private fun humanPortableState(value: String): String = when (value) {
    "requested" -> "solicitada"
    "preparing" -> "preparando"
    "ready" -> "lista"
    "local_inspection_ready" -> "inspección local correcta"
    "inspection_ready" -> "simulación lista"
    "importing" -> "importando"
    "completed" -> "completada"
    "completed_with_skips" -> "completada con omisiones"
    "rolled_back" -> "revertida"
    "failed" -> "fallida"
    "expired" -> "vencida"
    else -> value
}

private fun formatBytes(value: Long): String = when {
    value >= 1024 * 1024 -> "%.1f MiB".format(value / (1024.0 * 1024.0))
    value >= 1024 -> "%.1f KiB".format(value / 1024.0)
    else -> "$value B"
}
