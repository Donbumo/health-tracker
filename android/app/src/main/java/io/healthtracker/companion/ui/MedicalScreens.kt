package io.healthtracker.companion.ui

import android.content.Intent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import java.time.LocalDate
import io.healthtracker.companion.core.database.LabResultEntity
import io.healthtracker.companion.core.database.MedicalDocumentEntity
import kotlinx.serialization.json.*

private const val MEDICAL_WARNING = "Los estudios y resultados pueden contener información médica sensible."
private const val RANGE_NOTICE = "Según el rango incluido en este informe. Los estados se muestran tal como fueron reportados por la fuente."

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun MedicalRecordsScreen(viewModel: CompanionViewModel, close: () -> Unit, openDetail: (String) -> Unit) {
    val studies by viewModel.medicalStudies.collectAsState()
    val connected by viewModel.connected.collectAsState()
    var showCreate by remember { mutableStateOf(false) }
    LaunchedEffect(connected) { if (connected) viewModel.refreshMedicalRecords() }
    Scaffold(
        topBar = { TopAppBar(title = { Text("Estudios médicos") }, navigationIcon = { TextButton(onClick = close) { Text("Atrás") } }) },
        floatingActionButton = { FloatingActionButton(onClick = { showCreate = true }) { Text("+") } },
    ) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).padding(horizontal = 20.dp),
            contentPadding = PaddingValues(vertical = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item { MedicalWarningCard() }
            if (!connected) item { Text("Disponible offline. Los cambios quedan guardados hasta recuperar conexión.") }
            if (studies.isEmpty()) item {
                Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(18.dp)) {
                    Text("Aún no hay estudios", style = MaterialTheme.typography.titleMedium)
                    Text("Añade resultados manuales o conserva documentos médicos sin interpretación automática.")
                } }
            }
            items(studies, key = { it.publicId }) { study ->
                Card(onClick = { openDetail(study.publicId) }, modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(study.title, style = MaterialTheme.typography.titleMedium)
                        Text("${medicalStudyType(study.studyType)} · ${study.studyDate}")
                        study.laboratoryName?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                        Text(medicalSyncStatus(study.syncStatus), style = MaterialTheme.typography.labelMedium)
                    }
                }
            }
        }
    }
    if (showCreate) MedicalStudyDialog(
        dismiss = { showCreate = false },
        save = { title, type, date, lab, notes ->
            viewModel.createMedicalStudy(title, type, date, lab, notes) { openDetail(it) }
            showCreate = false
        },
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun MedicalStudyDetailScreen(viewModel: CompanionViewModel, close: () -> Unit, openHistory: (String) -> Unit) {
    val study by viewModel.selectedMedicalStudy.collectAsState()
    val panels by viewModel.medicalPanels.collectAsState()
    val results by viewModel.medicalResults.collectAsState()
    val documents by viewModel.medicalDocuments.collectAsState()
    var showResult by remember { mutableStateOf(false) }
    var showArchive by remember { mutableStateOf(false) }
    var showPermanentDelete by remember { mutableStateOf(false) }
    var showEdit by remember { mutableStateOf(false) }
    var editingResult by remember { mutableStateOf<LabResultEntity?>(null) }
    var deletingResult by remember { mutableStateOf<LabResultEntity?>(null) }
    var deletingDocument by remember { mutableStateOf<MedicalDocumentEntity?>(null) }
    val context = LocalContext.current
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        val mime = context.contentResolver.getType(uri) ?: return@rememberLauncherForActivityResult
        viewModel.attachMedicalDocument(uri, uri.lastPathSegment?.substringAfterLast('/') ?: "documento", mime)
    }
    Scaffold(topBar = { TopAppBar(title = { Text(study?.title ?: "Estudio médico") },
        navigationIcon = { TextButton(onClick = close) { Text("Atrás") } }) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).padding(horizontal = 20.dp),
            contentPadding = PaddingValues(vertical = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item { MedicalWarningCard() }
            study?.let { value -> item {
                Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    Text(medicalStudyType(value.studyType), style = MaterialTheme.typography.titleMedium)
                    Text("Fecha del estudio: ${value.studyDate}")
                    value.laboratoryName?.let { Text("Laboratorio o centro: $it") }
                    value.notes?.let { Text(it) }
                    Text(medicalSyncStatus(value.syncStatus), style = MaterialTheme.typography.labelMedium)
                    if (value.state == "draft") Button(onClick = viewModel::completeSelectedMedicalStudy) { Text("Finalizar captura") }
                    Row { TextButton(onClick = { showEdit = true }) { Text("Editar") }; TextButton(onClick = { showArchive = true }) { Text("Archivar") } }
                    TextButton(onClick = { showPermanentDelete = true }) { Text("Eliminar definitivamente") }
                } }
            } }
            item {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { showResult = true }, modifier = Modifier.weight(1f)) { Text("Añadir resultado") }
                    OutlinedButton(onClick = { picker.launch(arrayOf("application/pdf", "image/jpeg", "image/png", "application/json", "text/csv")) },
                        modifier = Modifier.weight(1f)) { Text("Adjuntar") }
                }
            }
            item { Text("Resultados", style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() }); Text(RANGE_NOTICE, style = MaterialTheme.typography.bodySmall) }
            if (results.isEmpty()) item { Text("Sin resultados estructurados.") }
            panels.forEach { panel ->
                item(key = "panel-${panel.publicId}") { Text(panel.name, style = MaterialTheme.typography.titleMedium) }
                items(results.filter { it.panelPublicId == panel.publicId }, key = { it.publicId }) { result ->
                    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        Text(result.displayName, style = MaterialTheme.typography.titleSmall)
                        Text(buildString { append(result.originalValue); result.originalUnit?.let { append(" "); append(it) } })
                        Text("Estado reportado: ${reportedStatus(result.sourceStatus)}")
                        Text("Comparación mecánica: ${derivedRangeStatus(result.derivedRangeStatus)}", style = MaterialTheme.typography.bodySmall)
                        result.referenceText?.let { Text("Referencia reportada: $it", style = MaterialTheme.typography.bodySmall) }
                        result.canonicalKey?.let { key -> TextButton(onClick = { openHistory(key) }) { Text("Ver historial") } }
                        Row {
                            TextButton(onClick = { editingResult = result }) { Text("Corregir") }
                            TextButton(onClick = { deletingResult = result }) { Text("Eliminar") }
                        }
                    } }
                }
            }
            item { Text("Documentos", style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() }) }
            if (documents.isEmpty()) item { Text("Sin documentos adjuntos.") }
            items(documents, key = { it.publicId }) { document ->
                ListItem(headlineContent = { Text(document.originalFilename) },
                    supportingContent = { Text("${document.mimeType} · ${document.availability} · ${medicalSyncStatus(document.syncStatus)}") },
                    trailingContent = { Row {
                        if (document.availability == "available") TextButton(onClick = {
                            viewModel.shareMedicalDocument(document.publicId) { intent ->
                                context.startActivity(Intent.createChooser(intent, "Compartir documento médico"))
                            }
                        }) { Text("Compartir") }
                        TextButton(onClick = { deletingDocument = document }) { Text("Eliminar") }
                    } })
            }
        }
    }
    if (showResult) MedicalResultDialog({ showResult = false }) { panel, name, type, original, numeric, unit, low, high, status ->
        viewModel.addMedicalResult(panel, name, type, original, numeric, unit, low, high, status); showResult = false
    }
    if (showEdit && study != null) EditMedicalStudyDialog(study!!.title, study!!.notes, { showEdit = false }) { title, notes ->
        viewModel.editSelectedMedicalStudy(title, notes); showEdit = false
    }
    if (showArchive) AlertDialog(onDismissRequest = { showArchive = false }, title = { Text("Archivar estudio") },
        text = { Text("El estudio dejará de aparecer en la lista principal. Sus resultados y documentos se conservan.") },
        confirmButton = { Button(onClick = { viewModel.archiveSelectedMedicalStudy(close); showArchive = false }) { Text("Archivar") } },
        dismissButton = { TextButton(onClick = { showArchive = false }) { Text("Cancelar") } })
    if (showPermanentDelete) AlertDialog(onDismissRequest = { showPermanentDelete = false }, title = { Text("Eliminar definitivamente") },
        text = { Text("Esta acción elimina metadata, paneles, resultados, revisiones y documentos de este estudio. No afecta otros datos de salud y no puede deshacerse después de sincronizar.") },
        confirmButton = { Button(onClick = { viewModel.permanentlyDeleteSelectedMedicalStudy(close); showPermanentDelete = false }) { Text("Entiendo, eliminar") } },
        dismissButton = { TextButton(onClick = { showPermanentDelete = false }) { Text("Cancelar") } })
    editingResult?.let { result -> EditMedicalResultDialog(result, { editingResult = null }) { original, numeric, unit, low, high, status, reason ->
        viewModel.editMedicalResult(result.publicId, original, numeric, unit, low, high, status, reason); editingResult = null
    } }
    deletingResult?.let { result -> AlertDialog(onDismissRequest = { deletingResult = null }, title = { Text("Eliminar resultado") },
        text = { Text("Se eliminará este resultado estructurado. El documento original del estudio no se modifica.") },
        confirmButton = { Button(onClick = { viewModel.deleteMedicalResult(result.publicId); deletingResult = null }) { Text("Eliminar") } },
        dismissButton = { TextButton(onClick = { deletingResult = null }) { Text("Cancelar") } }) }
    deletingDocument?.let { document -> AlertDialog(onDismissRequest = { deletingDocument = null }, title = { Text("Eliminar documento") },
        text = { Text("El archivo y su metadata se eliminarán. Los paneles y resultados estructurados permanecerán.") },
        confirmButton = { Button(onClick = { viewModel.deleteMedicalDocument(document.publicId); deletingDocument = null }) { Text("Eliminar") } },
        dismissButton = { TextButton(onClick = { deletingDocument = null }) { Text("Cancelar") } }) }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun MedicalHistoryScreen(viewModel: CompanionViewModel, close: () -> Unit) {
    val key by viewModel.medicalHistoryKey.collectAsState()
    val period by viewModel.medicalHistoryPeriod.collectAsState()
    val history by viewModel.medicalHistory.collectAsState()
    val points = remember(history?.seriesJson) { parseMedicalPoints(history?.seriesJson) }
    Scaffold(topBar = { TopAppBar(title = { Text("Historial de ${key ?: "marcador"}") },
        navigationIcon = { TextButton(onClick = close) { Text("Atrás") } }) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).padding(horizontal = 20.dp),
            contentPadding = PaddingValues(vertical = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item { MedicalWarningCard() }
            item { LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                items(listOf("30d", "90d", "180d", "1y", "all")) { option ->
                    FilterChip(selected = period == option, onClick = { viewModel.setMedicalHistoryPeriod(option) },
                        label = { Text(when (option) { "all" -> "Todo"; "1y" -> "1 año"; else -> "${option.removeSuffix("d")} días" }) })
                }
            } }
            item { Text(history?.comparisonNotice ?: if (history?.comparable == true) "Serie comparable por unidad y método." else "Unidades o métodos no comparables") }
            item {
                Canvas(Modifier.fillMaxWidth().height(180.dp).semantics {
                    contentDescription = if (points.isEmpty()) "Gráfica sin puntos comparables" else "Gráfica de historial con ${points.size} puntos"
                }) {
                    if (points.size > 1) {
                        val min = points.minOrNull()!!; val max = points.maxOrNull()!!; val span = (max - min).takeIf { it != 0f } ?: 1f
                        val plotted = points.mapIndexed { index, value ->
                            Offset(index * size.width / (points.size - 1), size.height - ((value - min) / span * size.height))
                        }
                        plotted.zipWithNext().forEach { (a, b) -> drawLine(Color(0xFF356859), a, b, strokeWidth = 5f) }
                        plotted.forEach { drawCircle(Color(0xFF1C4A3E), 7f, it) }
                    }
                }
            }
            if (points.isEmpty()) item { Text("No hay puntos numéricos comparables para este periodo.") }
            item { Text(RANGE_NOTICE, style = MaterialTheme.typography.bodySmall) }
        }
    }
}

@Composable private fun MedicalWarningCard() = ElevatedCard(Modifier.fillMaxWidth()) {
    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text("Información importante", style = MaterialTheme.typography.titleMedium)
        Text(MEDICAL_WARNING); Text("La app no diagnostica, recomienda tratamientos ni completa rangos de referencia.", style = MaterialTheme.typography.bodySmall)
    }
}

@Composable private fun MedicalStudyDialog(dismiss: () -> Unit, save: (String, String, String, String?, String?) -> Unit) {
    var title by remember { mutableStateOf("") }; var type by remember { mutableStateOf("laboratory") }
    var date by remember { mutableStateOf(LocalDate.now().toString()) }; var lab by remember { mutableStateOf("") }; var notes by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = dismiss, title = { Text("Nuevo estudio") }, text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(title, { title = it.take(240) }, label = { Text("Título") })
        LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) { items(listOf("laboratory", "imaging", "clinical_document", "other")) { value ->
            FilterChip(selected = type == value, onClick = { type = value }, label = { Text(medicalStudyType(value)) })
        } }
        OutlinedTextField(date, { date = it.take(10) }, label = { Text("Fecha (AAAA-MM-DD)") })
        OutlinedTextField(lab, { lab = it.take(200) }, label = { Text("Laboratorio o centro (opcional)") })
        OutlinedTextField(notes, { notes = it.take(5000) }, label = { Text("Notas (opcional)") })
    } }, confirmButton = { Button(onClick = { save(title, type, date, lab.ifBlank { null }, notes.ifBlank { null }) }, enabled = title.isNotBlank() && runCatching { LocalDate.parse(date) }.isSuccess) { Text("Guardar") } },
        dismissButton = { TextButton(onClick = dismiss) { Text("Cancelar") } })
}

@Composable private fun EditMedicalStudyDialog(initialTitle: String, initialNotes: String?, dismiss: () -> Unit, save: (String, String?) -> Unit) {
    var title by remember { mutableStateOf(initialTitle) }; var notes by remember { mutableStateOf(initialNotes.orEmpty()) }
    AlertDialog(onDismissRequest = dismiss, title = { Text("Editar estudio") }, text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(title, { title = it.take(240) }, label = { Text("Título") })
        OutlinedTextField(notes, { notes = it.take(5000) }, label = { Text("Notas") })
    } }, confirmButton = { Button(onClick = { save(title, notes.ifBlank { null }) }, enabled = title.isNotBlank()) { Text("Guardar") } }, dismissButton = { TextButton(onClick = dismiss) { Text("Cancelar") } })
}

@Composable private fun MedicalResultDialog(dismiss: () -> Unit, save: (String, String, String, String, String?, String?, String?, String?, String) -> Unit) {
    var panel by remember { mutableStateOf("Panel") }; var name by remember { mutableStateOf("") }; var type by remember { mutableStateOf("numeric") }
    var original by remember { mutableStateOf("") }; var numeric by remember { mutableStateOf("") }; var unit by remember { mutableStateOf("") }
    var low by remember { mutableStateOf("") }; var high by remember { mutableStateOf("") }; var status by remember { mutableStateOf("not_provided") }
    AlertDialog(onDismissRequest = dismiss, title = { Text("Añadir resultado") }, text = { LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item { OutlinedTextField(panel, { panel = it.take(200) }, label = { Text("Panel") }) }
        item { OutlinedTextField(name, { name = it.take(200) }, label = { Text("Marcador según el informe") }) }
        item { LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) { items(listOf("numeric", "text", "positive_negative", "detected_not_detected")) { value ->
            FilterChip(selected = type == value, onClick = { type = value }, label = { Text(value.replace('_', ' ')) })
        } } }
        item { OutlinedTextField(original, { original = it.take(500) }, label = { Text("Valor original") }) }
        if (type == "numeric") item { OutlinedTextField(numeric, { numeric = it }, label = { Text("Valor numérico") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal)) }
        item { OutlinedTextField(unit, { unit = it.take(100) }, label = { Text("Unidad original (opcional)") }) }
        if (type == "numeric") item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(low, { low = it }, label = { Text("Límite inferior") }, modifier = Modifier.weight(1f))
            OutlinedTextField(high, { high = it }, label = { Text("Límite superior") }, modifier = Modifier.weight(1f))
        } }
        item { LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) { items(listOf("not_provided", "low", "within_range", "high", "abnormal", "critical_as_reported")) { value ->
            FilterChip(selected = status == value, onClick = { status = value }, label = { Text(reportedStatus(value)) })
        } } }
    } }, confirmButton = { Button(onClick = { save(panel, name, type, original, numeric.ifBlank { null }, unit.ifBlank { null }, low.ifBlank { null }, high.ifBlank { null }, status) },
        enabled = panel.isNotBlank() && name.isNotBlank() && original.isNotBlank() && (type != "numeric" || numeric.toBigDecimalOrNull() != null)) { Text("Guardar") } },
        dismissButton = { TextButton(onClick = dismiss) { Text("Cancelar") } })
}

@Composable private fun EditMedicalResultDialog(result: LabResultEntity, dismiss: () -> Unit,
                                                 save: (String, String?, String?, String?, String?, String, String?) -> Unit) {
    var original by remember { mutableStateOf(result.originalValue) }; var numeric by remember { mutableStateOf(result.numericValue.orEmpty()) }
    var unit by remember { mutableStateOf(result.originalUnit.orEmpty()) }; var low by remember { mutableStateOf(result.referenceLower.orEmpty()) }
    var high by remember { mutableStateOf(result.referenceUpper.orEmpty()) }; var status by remember { mutableStateOf(result.sourceStatus) }
    var reason by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = dismiss, title = { Text("Corregir resultado") }, text = { LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item { Text("El valor anterior se conserva en el historial de revisiones.") }
        item { OutlinedTextField(original, { original = it.take(500) }, label = { Text("Valor original") }) }
        if (result.valueType == "numeric") item { OutlinedTextField(numeric, { numeric = it }, label = { Text("Valor numérico") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal)) }
        item { OutlinedTextField(unit, { unit = it.take(100) }, label = { Text("Unidad original") }) }
        item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(low, { low = it }, label = { Text("Límite inferior") }, modifier = Modifier.weight(1f))
            OutlinedTextField(high, { high = it }, label = { Text("Límite superior") }, modifier = Modifier.weight(1f))
        } }
        item { LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) { items(listOf("not_provided", "low", "within_range", "high", "abnormal", "critical_as_reported")) { value ->
            FilterChip(selected = status == value, onClick = { status = value }, label = { Text(reportedStatus(value)) })
        } } }
        item { OutlinedTextField(reason, { reason = it.take(500) }, label = { Text("Motivo de la corrección (opcional)") }) }
    } }, confirmButton = { Button(onClick = { save(original, numeric.ifBlank { null }, unit.ifBlank { null }, low.ifBlank { null }, high.ifBlank { null }, status, reason.ifBlank { null }) },
        enabled = original.isNotBlank() && (result.valueType != "numeric" || numeric.toBigDecimalOrNull() != null)) { Text("Guardar corrección") } },
        dismissButton = { TextButton(onClick = dismiss) { Text("Cancelar") } })
}

private fun parseMedicalPoints(raw: String?): List<Float> = runCatching {
    Json.parseToJsonElement(raw ?: "[]").jsonArray.mapNotNull { point ->
        val row = point.jsonObject
        (row["normalized_value"] ?: row["numeric_value"])?.jsonPrimitive?.contentOrNull?.toFloatOrNull()
    }
}.getOrDefault(emptyList())

private fun medicalStudyType(value: String) = when (value) {
    "laboratory" -> "Laboratorio"; "imaging" -> "Imagen"; "clinical_document" -> "Documento clínico"
    "prescription_document" -> "Receta"; "vaccination_document" -> "Vacunación"; else -> "Otro"
}
private fun medicalSyncStatus(value: String) = when (value) { "pending" -> "Pendiente de sincronización"; "conflict" -> "Requiere atención"; else -> "Sincronizado" }
private fun reportedStatus(value: String) = when (value) { "low" -> "Bajo (reportado)"; "within_range" -> "Dentro del rango (reportado)"; "high" -> "Alto (reportado)"; "abnormal" -> "Anormal (reportado)"; "critical_as_reported" -> "Crítico (reportado)"; "indeterminate" -> "Indeterminado"; else -> "No proporcionado" }
private fun derivedRangeStatus(value: String) = when (value) { "below_reported_range" -> "Por debajo del rango reportado"; "within_reported_range" -> "Dentro del rango reportado"; "above_reported_range" -> "Por encima del rango reportado"; else -> "No computable" }
