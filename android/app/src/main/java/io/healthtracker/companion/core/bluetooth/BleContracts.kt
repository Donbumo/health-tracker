package io.healthtracker.companion.core.bluetooth

import java.util.UUID
import kotlinx.coroutines.flow.Flow

enum class BleEnvironmentState { READY, DEVICE_WITHOUT_BLE, BLUETOOTH_DISABLED, PERMISSION_REQUIRED }
enum class BlePermissionState { GRANTED, DENIED, DENIED_PERMANENTLY }
enum class BleAssociationState { IDLE, SEARCHING, CHOOSER_PENDING, ASSOCIATED, CANCELLED, TIMEOUT, ERROR_RECOVERABLE }
enum class BleGattState { IDLE, CONNECTING, DISCOVERING, DISCOVERED, UNSUPPORTED, TIMEOUT, DISCONNECTED, PERMISSION_REQUIRED, BLUETOOTH_DISABLED, ERROR_RECOVERABLE }

data class BleScanConfig(val timeoutSeconds: Int = 20) {
    init { require(timeoutSeconds in 15..30) }
}

data class BleDeviceCandidate(
    val sessionDeviceId: String,
    val sanitizedName: String,
    val deviceFingerprint: String,
    val observedServiceUuids: Set<String>,
    val manufacturerFingerprint: String?,
    val rssi: Int,
)

data class BleGattCharacteristicSnapshot(
    val uuid: String,
    val properties: Set<String>,
    val descriptorCount: Int,
    val maximumObservedSize: Int = 0,
)

data class BleGattServiceSnapshot(
    val uuid: String,
    val characteristics: List<BleGattCharacteristicSnapshot>,
)

data class BleGattInspection(
    val state: BleGattState,
    val serviceFingerprint: String?,
    val services: List<BleGattServiceSnapshot>,
    val resultCode: String,
)

data class BleLimits(
    val connectionTimeoutMs: Long = 12_000,
    val discoveryTimeoutMs: Long = 10_000,
    val maximumServices: Int = 40,
    val maximumCharacteristics: Int = 200,
    val maximumDescriptors: Int = 400,
) {
    init {
        require(connectionTimeoutMs in 1_000..30_000)
        require(discoveryTimeoutMs in 1_000..30_000)
        require(maximumServices in 1..100)
        require(maximumCharacteristics in 1..500)
        require(maximumDescriptors in 1..1_000)
    }
}

interface BleEnvironment {
    fun state(): BleEnvironmentState
}

interface BlePermissionController {
    fun requiredPermissions(): Set<String>
    fun state(): BlePermissionState
}

interface BleScanSession : AutoCloseable {
    val results: Flow<List<BleDeviceCandidate>>
    val active: Flow<Boolean>
    fun select(sessionDeviceId: String): BleDeviceCandidate?
    fun cancel()
    override fun close() = cancel()
}

interface BleScanner {
    fun start(config: BleScanConfig = BleScanConfig()): BleScanSession
}

data class BleAssociationRequest(
    val modelLabel: String,
    val singleDevice: Boolean = false,
)

data class BleAssociationResult(
    val state: BleAssociationState,
    val systemAssociationId: Long? = null,
    val sanitizedCode: String? = null,
)

interface BleAssociationManager {
    fun supported(): Boolean
    suspend fun request(request: BleAssociationRequest): BleAssociationResult
    fun cancel()
}

interface BleConnection : AutoCloseable {
    val state: Flow<BleGattState>
    suspend fun inspect(limits: BleLimits = BleLimits()): BleGattInspection
    override fun close()
}

interface BleGattClient {
    suspend fun connect(candidate: BleDeviceCandidate, limits: BleLimits = BleLimits()): BleConnection
}

data class BleNotification(
    val serviceUuid: String,
    val characteristicUuid: String,
    val relativeTimestampMs: Long,
    val payload: ByteArray,
)

interface BleNotificationStream : AutoCloseable {
    val notifications: Flow<BleNotification>
    override fun close()
}

interface BleCaptureStore {
    suspend fun save(capture: BleCapture): StoredBleCapture
    suspend fun load(captureId: String): BleCapture
    suspend fun delete(captureId: String): Boolean
}

interface BleReplaySource {
    fun replay(capture: BleCapture): Flow<BleCaptureEvent>
}

interface BleFrameDecoder {
    fun decode(event: BleCaptureEvent): DecodedBleFrame
}

interface ScaleProtocolAdapter {
    fun accept(frame: DecodedBleFrame): ScaleProtocolObservation
}

interface ScaleMeasurementMapper {
    fun map(observation: ScaleProtocolObservation): CandidateScaleMeasurement?
}

data class DecodedBleFrame(val length: Int, val fingerprint: String, val bytes: ByteArray)
data class CandidateScaleMeasurement(val metricType: String, val canonicalValue: String, val verified: Boolean)
data class ScaleProtocolObservation(val state: String, val frameFingerprint: String, val stable: Boolean)

internal fun characteristicProperties(value: Int): Set<String> = buildSet {
    if (value and 0x02 != 0) add("read")
    if (value and 0x04 != 0) add("write_no_response")
    if (value and 0x08 != 0) add("write")
    if (value and 0x10 != 0) add("notify")
    if (value and 0x20 != 0) add("indicate")
    if (value and 0x01 != 0) add("broadcast")
}

internal fun normalizedUuid(value: UUID): String = value.toString().lowercase()
