package io.healthtracker.companion.ui

import android.content.Intent
import android.content.ClipData
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import io.healthtracker.companion.BuildConfig
import io.healthtracker.companion.core.bluetooth.BleEnvironmentState
import io.healthtracker.companion.core.bluetooth.BleGattState
import io.healthtracker.companion.core.external.ConfirmedScaleKind
import io.healthtracker.companion.core.healthconnect.ScaleDiagnosticResult

@Composable
internal fun ExternalSourcesScreen(viewModel: CompanionViewModel, close: () -> Unit) {
    val context = LocalContext.current
    val sources by viewModel.externalSources.collectAsState()
    val diagnostic by viewModel.scaleDiagnostic.collectAsState()
    val associations by viewModel.healthConnectSourceAssociations.collectAsState()
    val device by viewModel.externalDevice.collectAsState()
    val persistedDevices by viewModel.bleDeviceAssociations.collectAsState()
    val persistedCaptures by viewModel.bleCaptureMetadata.collectAsState()
    val duplicates by viewModel.possibleExternalDuplicates.collectAsState()
    var captureConsent by remember { mutableStateOf(false) }
    var forgetConfirmation by remember { mutableStateOf(false) }
    var deleteCaptureConfirmation by remember { mutableStateOf(false) }
    var exportConfirmation by remember { mutableStateOf(false) }
    var exportUri by remember { mutableStateOf<Uri?>(null) }
    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        viewModel.onBlePermissionResult()
    }
    BackHandler { viewModel.cancelBleScan(); viewModel.cancelExperimentalCapture(); close() }
    DisposableEffect(Unit) { onDispose { viewModel.cancelBleScan(); viewModel.cancelExperimentalCapture() } }
    DisposableEffect(exportUri) { onDispose { exportUri?.let(viewModel::revokeBleCaptureExport) } }

    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(horizontal = 20.dp).testTag("external_sources_screen"),
        contentPadding = PaddingValues(vertical = 20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            TextButton(onClick = { viewModel.cancelBleScan(); viewModel.cancelExperimentalCapture(); close() }) { Text("Volver") }
            Text("Fuentes externas", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.semantics { heading() })
            Text("Cada fuente queda aislada por servidor y cuenta. Bluetooth y Health Connect son opcionales e independientes.")
        }
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("Health Connect", style = MaterialTheme.typography.titleLarge)
                    Text("Comprobar datos de báscula", style = MaterialTheme.typography.titleMedium)
                    Text("Solo inspecciona peso y grasa corporal. El resultado contiene conteos, fechas truncadas y fingerprints; nunca valores ni IDs.")
                    Button(onClick = viewModel::inspectHealthConnectScaleSources, modifier = Modifier.fillMaxWidth()) {
                        Text("Comprobar datos de báscula")
                    }
                    ScaleDiagnosticSummary(diagnostic)
                    diagnostic.origins.forEach { origin ->
                        val association = associations.firstOrNull { it.sourceFingerprint == origin.fingerprint }
                        Card(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                Text(origin.safeLabel, style = MaterialTheme.typography.titleMedium)
                                Text("Origen ${origin.fingerprint.take(12)} · ${origin.recordCount} registros")
                                Text("Estado local: ${association?.state ?: "unconfirmed"}")
                                Text("Confirmar que este origen corresponde a mi báscula")
                                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    FilterChip(
                                        selected = association?.confirmedModel == "generic_scale",
                                        onClick = { viewModel.confirmHealthConnectScale(origin.fingerprint, ConfirmedScaleKind.GENERIC_SCALE) },
                                        label = { Text("Genérica") },
                                    )
                                    FilterChip(
                                        selected = association?.confirmedModel == "xiaomi_s400_user_confirmed",
                                        onClick = { viewModel.confirmHealthConnectScale(origin.fingerprint, ConfirmedScaleKind.XIAOMI_S400) },
                                        label = { Text("Xiaomi S400") },
                                    )
                                }
                                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    FilterChip(
                                        selected = association?.confirmedModel == "other_device",
                                        onClick = { viewModel.confirmHealthConnectScale(origin.fingerprint, ConfirmedScaleKind.OTHER_DEVICE) },
                                        label = { Text("Otro dispositivo") },
                                    )
                                    FilterChip(
                                        selected = association?.state == "ambiguous",
                                        onClick = { viewModel.confirmHealthConnectScale(origin.fingerprint, ConfirmedScaleKind.NOT_SURE) },
                                        label = { Text("No estoy seguro") },
                                    )
                                }
                                if (association?.state in setOf("user_confirmed", "ambiguous")) {
                                    TextButton(onClick = { viewModel.revokeHealthConnectScale(origin.fingerprint) }) { Text("Eliminar confirmación") }
                                }
                            }
                        }
                    }
                }
            }
        }
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("Dispositivos", style = MaterialTheme.typography.titleLarge)
                    Text("Xiaomi Body Composition Scale S400", style = MaterialTheme.typography.titleMedium)
                    ExperimentalProtocolNotice()
                    persistedDevices.firstOrNull()?.let { persisted ->
                        Text("Asociación conservada: ${persisted.alias ?: persisted.sanitizedName} · ${persisted.deviceFingerprint.take(12)}")
                        Text("Última detección: ${persisted.lastSeenAt.take(10)} · capturas privadas: ${persistedCaptures.size}")
                        if (device.selected == null) Text("Tras reiniciar, pulsa Buscar y selecciona el mismo fingerprint para volver a conectar sin duplicar la asociación.", style = MaterialTheme.typography.bodySmall)
                    }
                    BleEnvironmentMessage(device.environment)
                    when (device.environment) {
                        BleEnvironmentState.PERMISSION_REQUIRED -> {
                            Button(
                                onClick = { permissionLauncher.launch(viewModel.requiredBlePermissions().toTypedArray()) },
                                modifier = Modifier.fillMaxWidth(),
                            ) { Text("Permitir Bluetooth para buscar") }
                            OutlinedButton(
                                onClick = {
                                    context.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}")))
                                },
                                modifier = Modifier.fillMaxWidth(),
                            ) { Text("Abrir configuración") }
                        }
                        BleEnvironmentState.BLUETOOTH_DISABLED -> OutlinedButton(
                            onClick = { context.startActivity(Intent(Settings.ACTION_BLUETOOTH_SETTINGS)) },
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text("Activar Bluetooth") }
                        BleEnvironmentState.READY -> Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(onClick = viewModel::startBleScan, enabled = !device.scanning, modifier = Modifier.weight(1f)) { Text("Buscar") }
                            OutlinedButton(onClick = viewModel::cancelBleScan, enabled = device.scanning, modifier = Modifier.weight(1f)) { Text("Cancelar") }
                        }
                        BleEnvironmentState.DEVICE_WITHOUT_BLE -> Unit
                    }
                    if (device.scanning) Text("Buscando durante un máximo de 20 segundos… Selecciona explícitamente un dispositivo.")
                    device.candidates.forEach { candidate ->
                        Card(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                Text(candidate.sanitizedName, style = MaterialTheme.typography.titleMedium)
                                Text("Fingerprint ${candidate.deviceFingerprint.take(12)} · señal ${candidate.rssi}")
                                Button(
                                    onClick = { viewModel.associateBleCandidate(candidate.sessionDeviceId) },
                                    modifier = Modifier.fillMaxWidth(),
                                ) { Text("Seleccionar y asociar") }
                            }
                        }
                    }
                    if (device.associationState == "associated") {
                        Text("Asociada localmente · modelo confirmado por el usuario")
                        OutlinedButton(onClick = viewModel::inspectAssociatedBleDevice, modifier = Modifier.fillMaxWidth()) {
                            Text("Inspeccionar dispositivo")
                        }
                        if (device.latestInspection != null) {
                            val inspection = device.latestInspection!!
                            Text("GATT: ${inspection.resultCode} · servicios ${inspection.services.size}")
                            Text("Se detectaron ${inspection.services.sumOf { it.characteristics.count { characteristic -> "notify" in characteristic.properties } }} notify y ${inspection.services.sumOf { it.characteristics.count { characteristic -> "indicate" in characteristic.properties } }} indicate. Cero escrituras de características.")
                            inspection.services.forEach { service ->
                                service.characteristics.filter { "notify" in it.properties || "indicate" in it.properties }.forEach { characteristic ->
                                    FilterChip(
                                        selected = device.selectedCaptureServiceUuid == service.uuid && device.selectedCaptureCharacteristicUuid == characteristic.uuid,
                                        onClick = { viewModel.selectBleCaptureCharacteristic(service.uuid, characteristic.uuid) },
                                        label = { Text("Seleccionar ${characteristic.uuid.take(8)} · ${characteristic.properties.sorted().joinToString("/")}") },
                                    )
                                }
                            }
                        }
                        if (BuildConfig.EXPERIMENTAL_BLE_CAPTURE) {
                            OutlinedButton(
                                onClick = { if (device.capturing) viewModel.cancelExperimentalCapture() else captureConsent = true },
                                enabled = device.capturing || device.selectedCaptureCharacteristicUuid != null,
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Text(if (device.capturing) "Detener captura" else "Capturar sesión de medición")
                            }
                            Text("Capturas almacenadas en esta sesión: ${device.storedCaptureCount}")
                            if (device.latestCaptureId != null) {
                                OutlinedButton(onClick = { exportConfirmation = true }, modifier = Modifier.fillMaxWidth()) { Text("Exportar última captura") }
                                TextButton(onClick = { deleteCaptureConfirmation = true }) { Text("Borrar última captura") }
                            }
                        }
                        TextButton(onClick = { forgetConfirmation = true }, modifier = Modifier.fillMaxWidth()) { Text("Olvidar dispositivo") }
                    }
                    if (device.associationState != "associated" && persistedDevices.isNotEmpty()) {
                        TextButton(onClick = { forgetConfirmation = true }, modifier = Modifier.fillMaxWidth()) { Text("Olvidar asociación guardada") }
                    }
                    Text("No existe botón Guardar medición. Peso y composición BLE permanecen deshabilitados.", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        item {
            Text("Registro local: ${sources.size} fuentes declaradas. Las capturas usan almacenamiento interno sin backup y cifrado Keystore; no se suben automáticamente.")
            if (duplicates.isNotEmpty()) {
                Text("Posibles duplicados", style = MaterialTheme.typography.titleLarge)
                duplicates.forEach { duplicate ->
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("${duplicate.classification} · revisión explícita")
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                OutlinedButton(onClick = { viewModel.resolveExternalDuplicate(duplicate.duplicateId, true) }, modifier = Modifier.weight(1f)) { Text("Son la misma") }
                                OutlinedButton(onClick = { viewModel.resolveExternalDuplicate(duplicate.duplicateId, false) }, modifier = Modifier.weight(1f)) { Text("Mantener ambas") }
                            }
                        }
                    }
                }
            }
            Spacer(Modifier.height(72.dp))
        }
    }

    if (captureConsent) AlertDialog(
        onDismissRequest = { captureConsent = false },
        title = { Text("Captura BLE experimental") },
        text = { Text("Una captura puede contener datos sensibles. Solo se suscribirá a características notify/indicate seleccionadas, tendrá límites estrictos y permanecerá privada. Exportarla requerirá otra confirmación. Esta build aún no interpreta ni publica valores.") },
        confirmButton = {
            Button(onClick = { captureConsent = false; viewModel.explainExperimentalCapture() }) { Text("Entiendo y continuar") }
        },
        dismissButton = { TextButton(onClick = { captureConsent = false }) { Text("Cancelar") } },
    )
    if (forgetConfirmation) AlertDialog(
        onDismissRequest = { forgetConfirmation = false },
        title = { Text("¿Olvidar dispositivo?") },
        text = { Text("Se eliminará la asociación. Las mediciones no se borrarán y las capturas se administran por separado.") },
        confirmButton = { Button(onClick = { forgetConfirmation = false; viewModel.forgetAssociatedBleDevice() }) { Text("Olvidar") } },
        dismissButton = { TextButton(onClick = { forgetConfirmation = false }) { Text("Cancelar") } },
    )
    if (deleteCaptureConfirmation) AlertDialog(
        onDismissRequest = { deleteCaptureConfirmation = false },
        title = { Text("¿Borrar captura privada?") },
        text = { Text("Se eliminarán el archivo cifrado y su metadata local. La asociación permanecerá.") },
        confirmButton = { Button(onClick = { deleteCaptureConfirmation = false; viewModel.deleteLatestBleCapture() }) { Text("Borrar") } },
        dismissButton = { TextButton(onClick = { deleteCaptureConfirmation = false }) { Text("Cancelar") } },
    )
    if (exportConfirmation) AlertDialog(
        onDismissRequest = { exportConfirmation = false },
        title = { Text("Exportar captura sensible") },
        text = { Text("La exportación descifra temporalmente una copia. Elige explícitamente una aplicación; Health Tracker no la sube. El permiso y la copia temporal se revocarán al salir de esta pantalla.") },
        confirmButton = {
            Button(onClick = {
                exportConfirmation = false
                viewModel.prepareLatestBleCaptureExport { uri ->
                    exportUri?.let(viewModel::revokeBleCaptureExport)
                    exportUri = uri
                    val send = Intent(Intent.ACTION_SEND)
                        .setType("application/json")
                        .putExtra(Intent.EXTRA_STREAM, uri)
                    send.clipData = ClipData.newRawUri("Captura BLE privada", uri)
                    send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    context.startActivity(Intent.createChooser(send, "Elegir destino para la captura"))
                }
            }) { Text("Elegir destino") }
        },
        dismissButton = { TextButton(onClick = { exportConfirmation = false }) { Text("Cancelar") } },
    )
}

@Composable
internal fun ScaleDiagnosticSummary(diagnostic: ScaleDiagnosticResult) {
    Text(diagnostic.humanSummary())
    if (diagnostic.recordCount > 0) {
        Text("Tipos: ${diagnostic.foundTypes.sorted().joinToString(", ")} · registros: ${diagnostic.recordCount} · orígenes: ${diagnostic.originCount}")
        Text("Ventana disponible: ${diagnostic.firstDate ?: "desconocida"} → ${diagnostic.lastDate ?: "desconocida"}")
        Text("Ya importados: ${diagnostic.importedCount} · no importados: ${diagnostic.notImportedCount}")
    }
}

@Composable
internal fun ExperimentalProtocolNotice() {
    Text("Experimental · Protocolo todavía no validado", color = MaterialTheme.colorScheme.error)
}

@Composable
internal fun BleEnvironmentMessage(state: BleEnvironmentState) {
    Text(bleEnvironmentText(state))
}

internal fun bleEnvironmentText(state: BleEnvironmentState): String = when (state) {
    BleEnvironmentState.READY -> "Bluetooth disponible. La búsqueda solo empieza al pulsar Buscar."
    BleEnvironmentState.DEVICE_WITHOUT_BLE -> "Este dispositivo no dispone de BLE. Health Connect y el resto de la app siguen funcionando."
    BleEnvironmentState.BLUETOOTH_DISABLED -> "Bluetooth está apagado; no equivale a permiso denegado."
    BleEnvironmentState.PERMISSION_REQUIRED -> "Se necesita permiso Bluetooth contextual. Denegarlo no afecta Health Connect, login ni entrenamientos."
}
