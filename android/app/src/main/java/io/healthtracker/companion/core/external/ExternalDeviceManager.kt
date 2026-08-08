package io.healthtracker.companion.core.external

import androidx.room.withTransaction
import io.healthtracker.companion.core.bluetooth.AndroidBleEnvironment
import io.healthtracker.companion.core.bluetooth.AndroidBleGattClient
import io.healthtracker.companion.core.bluetooth.AndroidBlePermissionController
import io.healthtracker.companion.core.bluetooth.AndroidBleScanner
import io.healthtracker.companion.core.bluetooth.BleDeviceCandidate
import io.healthtracker.companion.core.bluetooth.BleEnvironmentState
import io.healthtracker.companion.core.bluetooth.BleGattInspection
import io.healthtracker.companion.core.bluetooth.BleGattState
import io.healthtracker.companion.core.bluetooth.EncryptedBleCaptureStore
import io.healthtracker.companion.core.bluetooth.BleScanConfig
import io.healthtracker.companion.core.bluetooth.BleScanSession
import io.healthtracker.companion.core.database.BleDeviceAssociationEntity
import io.healthtracker.companion.core.database.BleGattSnapshotEntity
import io.healthtracker.companion.core.database.BleCaptureMetadataEntity
import io.healthtracker.companion.core.database.CompanionDatabase
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray

data class ExternalDeviceUiState(
    val environment: BleEnvironmentState = BleEnvironmentState.PERMISSION_REQUIRED,
    val scanning: Boolean = false,
    val candidates: List<BleDeviceCandidate> = emptyList(),
    val selected: BleDeviceCandidate? = null,
    val associationState: String = "not_associated",
    val gattState: BleGattState = BleGattState.IDLE,
    val latestInspection: BleGattInspection? = null,
    val selectedCaptureServiceUuid: String? = null,
    val selectedCaptureCharacteristicUuid: String? = null,
    val capturing: Boolean = false,
    val storedCaptureCount: Int = 0,
    val latestCaptureId: String? = null,
    val errorCode: String? = null,
)

class ExternalDeviceManager(
    private val database: CompanionDatabase,
    private val environment: AndroidBleEnvironment,
    private val permissions: AndroidBlePermissionController,
    private val scanner: AndroidBleScanner,
    private val gattClient: AndroidBleGattClient,
    private val captureStore: EncryptedBleCaptureStore,
    private val scope: CoroutineScope,
) {
    private val mutableState = MutableStateFlow(ExternalDeviceUiState(environment = environment.state()))
    private val scanGate = AtomicBoolean(false)
    private var scanSession: BleScanSession? = null
    private var scanCollector: Job? = null
    private var captureJob: Job? = null
    val state: StateFlow<ExternalDeviceUiState> = mutableState.asStateFlow()

    fun requiredPermissions(): Set<String> = permissions.requiredPermissions()
    fun latestCaptureId(): String? = mutableState.value.latestCaptureId

    fun refresh() {
        mutableState.value = mutableState.value.copy(environment = environment.state())
    }

    fun startScan(timeoutSeconds: Int = 20) {
        refresh()
        if (mutableState.value.environment != BleEnvironmentState.READY) return
        if (!scanGate.compareAndSet(false, true)) return
        runCatching {
            scanner.start(BleScanConfig(timeoutSeconds)).also { session ->
                scanSession = session
                mutableState.value = mutableState.value.copy(scanning = true, candidates = emptyList(), errorCode = null)
                scanCollector = scope.launch {
                    session.results.collectLatest { results -> mutableState.value = mutableState.value.copy(candidates = results) }
                }
                scope.launch {
                    session.active.collectLatest { active ->
                        if (!active) {
                            mutableState.value = mutableState.value.copy(scanning = false)
                            scanGate.set(false)
                        }
                    }
                }
            }
        }.onFailure {
            scanGate.set(false)
            mutableState.value = mutableState.value.copy(scanning = false, errorCode = "scan_unavailable")
        }
    }

    fun cancelScan() {
        scanSession?.cancel()
        scanCollector?.cancel()
        scanSession = null
        scanCollector = null
        scanGate.set(false)
        mutableState.value = mutableState.value.copy(scanning = false)
    }

    suspend fun selectAndAssociate(scopeId: String, sessionDeviceId: String): Boolean {
        val candidate = scanSession?.select(sessionDeviceId) ?: return false
        cancelScan()
        val now = Instant.now().toString()
        val existing = database.companionDao().bleDeviceAssociationByFingerprint(scopeId, candidate.deviceFingerprint)
        database.companionDao().upsertBleDeviceAssociation(
            BleDeviceAssociationEntity(
                accountScope = scopeId,
                associationKey = existing?.associationKey ?: UUID.randomUUID().toString(),
                systemAssociationId = existing?.systemAssociationId,
                sanitizedName = candidate.sanitizedName,
                alias = existing?.alias,
                deviceFingerprint = candidate.deviceFingerprint,
                serviceUuids = candidate.observedServiceUuids.sorted().joinToString(","),
                manufacturerFingerprint = candidate.manufacturerFingerprint,
                firstSeenAt = existing?.firstSeenAt ?: now,
                lastSeenAt = now,
                state = "associated_explicit_scan",
                userConfirmedModel = "xiaomi_s400_user_confirmed",
            ),
        )
        mutableState.value = mutableState.value.copy(selected = candidate, associationState = "associated", candidates = listOf(candidate))
        return true
    }

    suspend fun inspect(scopeId: String): BleGattInspection {
        val candidate = mutableState.value.selected
            ?: return BleGattInspection(BleGattState.DISCONNECTED, null, emptyList(), "candidate_unavailable")
        mutableState.value = mutableState.value.copy(gattState = BleGattState.CONNECTING, errorCode = null)
        val inspection = runCatching { gattClient.connect(candidate).use { it.inspect() } }.getOrElse {
            BleGattInspection(BleGattState.ERROR_RECOVERABLE, null, emptyList(), "gatt_error")
        }
        mutableState.value = mutableState.value.copy(gattState = inspection.state, latestInspection = inspection, errorCode = inspection.resultCode.takeUnless { it == "ok" })
        val association = database.companionDao().bleDeviceAssociationByFingerprint(scopeId, candidate.deviceFingerprint)
        if (association != null) {
            val services = buildJsonArray {
                inspection.services.forEach { service ->
                    add(buildJsonObject {
                        put("uuid", service.uuid)
                        putJsonArray("characteristics") {
                            service.characteristics.forEach { characteristic ->
                                add(buildJsonObject {
                                    put("uuid", characteristic.uuid)
                                    put("properties", characteristic.properties.sorted().joinToString(","))
                                    put("descriptorCount", characteristic.descriptorCount)
                                    put("maximumObservedSize", characteristic.maximumObservedSize)
                                })
                            }
                        }
                    })
                }
            }.toString()
            database.companionDao().upsertBleGattSnapshot(
                BleGattSnapshotEntity(
                    accountScope = scopeId,
                    snapshotId = UUID.randomUUID().toString(),
                    associationKey = association.associationKey,
                    serviceFingerprint = inspection.serviceFingerprint ?: "none",
                    servicesJson = services,
                    observedDate = LocalDate.now(ZoneOffset.UTC).toString(),
                    resultCode = inspection.resultCode,
                ),
            )
        }
        return inspection
    }

    fun selectCaptureCharacteristic(serviceUuid: String, characteristicUuid: String): Boolean {
        val valid = mutableState.value.latestInspection?.services?.any { service ->
            service.uuid == serviceUuid && service.characteristics.any { characteristic ->
                characteristic.uuid == characteristicUuid && ("notify" in characteristic.properties || "indicate" in characteristic.properties)
            }
        } == true
        if (valid) mutableState.value = mutableState.value.copy(
            selectedCaptureServiceUuid = serviceUuid,
            selectedCaptureCharacteristicUuid = characteristicUuid,
        )
        return valid
    }

    fun startCapture(scopeId: String) {
        if (captureJob?.isActive == true) return
        val current = mutableState.value
        val candidate = current.selected ?: return
        val serviceUuid = current.selectedCaptureServiceUuid ?: return
        val characteristicUuid = current.selectedCaptureCharacteristicUuid ?: return
        captureJob = scope.launch {
            mutableState.value = mutableState.value.copy(capturing = true, errorCode = null)
            runCatching {
                val capture = gattClient.captureNotifications(candidate, serviceUuid, characteristicUuid)
                val stored = captureStore.save(capture)
                val association = database.companionDao().bleDeviceAssociationByFingerprint(scopeId, candidate.deviceFingerprint)
                    ?: error("association_missing")
                database.companionDao().upsertBleCaptureMetadata(
                    BleCaptureMetadataEntity(
                        accountScope = scopeId,
                        captureId = stored.captureId,
                        associationKey = association.associationKey,
                        encryptedFileName = stored.encryptedFileName,
                        createdDate = LocalDate.now(ZoneOffset.UTC).toString(),
                        eventCount = stored.eventCount,
                        byteCount = stored.byteCount,
                        durationMs = stored.durationMs,
                        checksum = stored.checksum,
                        terminalState = capture.events.lastOrNull()?.connectionState ?: "completed",
                    ),
                )
                mutableState.value = mutableState.value.copy(
                    capturing = false,
                    storedCaptureCount = mutableState.value.storedCaptureCount + 1,
                    latestCaptureId = stored.captureId,
                )
            }.onFailure {
                if (it !is kotlinx.coroutines.CancellationException) {
                    mutableState.value = mutableState.value.copy(capturing = false, errorCode = "capture_failed")
                }
            }
        }
    }

    fun cancelCapture() {
        captureJob?.cancel()
        captureJob = null
        mutableState.value = mutableState.value.copy(capturing = false)
    }

    suspend fun deleteLatestCapture(scopeId: String): Boolean {
        val captureId = mutableState.value.latestCaptureId ?: return false
        val metadata = database.companionDao().bleCaptureMetadata(scopeId, captureId) ?: return false
        if (!captureStore.deleteWithMetadata(metadata.encryptedFileName) {
                database.companionDao().deleteBleCaptureMetadata(scopeId, captureId)
            }
        ) return false
        mutableState.value = mutableState.value.copy(
            storedCaptureCount = (mutableState.value.storedCaptureCount - 1).coerceAtLeast(0),
            latestCaptureId = null,
        )
        return true
    }

    suspend fun forget(scopeId: String) {
        cancelCapture()
        val fingerprint = mutableState.value.selected?.deviceFingerprint ?: return
        database.companionDao().deleteBleDeviceAssociation(scopeId, fingerprint)
        mutableState.value = ExternalDeviceUiState(environment = environment.state())
    }
}
