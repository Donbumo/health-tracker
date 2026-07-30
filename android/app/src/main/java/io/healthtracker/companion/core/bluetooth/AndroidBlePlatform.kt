package io.healthtracker.companion.core.bluetooth

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattService
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothStatusCodes
import android.bluetooth.BluetoothManager
import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.companion.AssociationInfo
import android.companion.CompanionDeviceManager
import android.companion.CompanionDeviceManager.Callback
import android.companion.AssociationRequest
import android.content.Context
import android.content.IntentSender
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat
import io.healthtracker.companion.core.external.shortFingerprint
import java.time.Instant
import java.util.Base64
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.resume
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeout

class AndroidBleEnvironment(private val context: Context) : BleEnvironment {
    override fun state(): BleEnvironmentState {
        if (!context.packageManager.hasSystemFeature(PackageManager.FEATURE_BLUETOOTH_LE)) return BleEnvironmentState.DEVICE_WITHOUT_BLE
        val adapter = context.getSystemService(BluetoothManager::class.java)?.adapter
            ?: return BleEnvironmentState.DEVICE_WITHOUT_BLE
        if (!adapter.isEnabled) return BleEnvironmentState.BLUETOOTH_DISABLED
        if (AndroidBlePermissionController(context).state() != BlePermissionState.GRANTED) return BleEnvironmentState.PERMISSION_REQUIRED
        return BleEnvironmentState.READY
    }
}

class AndroidBlePermissionController(private val context: Context) : BlePermissionController {
    override fun requiredPermissions(): Set<String> = requiredBlePermissionsFor(Build.VERSION.SDK_INT)

    override fun state(): BlePermissionState = if (requiredPermissions().all {
            ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED
        }
    ) BlePermissionState.GRANTED else BlePermissionState.DENIED

    fun state(activity: Activity): BlePermissionState {
        if (state() == BlePermissionState.GRANTED) return BlePermissionState.GRANTED
        val canExplain = requiredPermissions().any(activity::shouldShowRequestPermissionRationale)
        return if (canExplain) BlePermissionState.DENIED else BlePermissionState.DENIED_PERMANENTLY
    }
}

fun requiredBlePermissionsFor(api: Int): Set<String> = when {
    api >= Build.VERSION_CODES.S -> setOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
    api >= Build.VERSION_CODES.M -> setOf(Manifest.permission.ACCESS_FINE_LOCATION)
    else -> emptySet()
}

class AndroidBleScanner(
    private val context: Context,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.Default),
) : BleScanner {
    private val devices = ConcurrentHashMap<String, BluetoothDevice>()

    @SuppressLint("MissingPermission")
    override fun start(config: BleScanConfig): BleScanSession {
        check(AndroidBleEnvironment(context).state() == BleEnvironmentState.READY) { "ble_environment_not_ready" }
        val scanner = context.getSystemService(BluetoothManager::class.java).adapter.bluetoothLeScanner
            ?: error("ble_scanner_unavailable")
        return AndroidBleScanSession(scanner, config, devices, scope)
    }

    internal fun resolve(candidate: BleDeviceCandidate): BluetoothDevice? = devices[candidate.sessionDeviceId]
}

@SuppressLint("MissingPermission")
private class AndroidBleScanSession(
    private val scanner: BluetoothLeScanner,
    config: BleScanConfig,
    private val deviceMap: ConcurrentHashMap<String, BluetoothDevice>,
    scope: CoroutineScope,
) : BleScanSession {
    private val closed = AtomicBoolean(false)
    private val mutableResults = MutableStateFlow<List<BleDeviceCandidate>>(emptyList())
    private val mutableActive = MutableStateFlow(true)
    private val callback: ScanCallback
    private val timeoutJob: Job

    override val results: Flow<List<BleDeviceCandidate>> = mutableResults.asStateFlow()
    override val active: Flow<Boolean> = mutableActive.asStateFlow()

    init {
        callback = object : ScanCallback() {
            @SuppressLint("MissingPermission")
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                if (closed.get()) return
                val services = result.scanRecord?.serviceUuids.orEmpty().mapTo(sortedSetOf()) { it.uuid.toString().lowercase() }
                val manufacturer = result.scanRecord?.manufacturerSpecificData?.let { data ->
                    if (data.size() == 0) null else buildString {
                        for (index in 0 until data.size()) append(data.keyAt(index)).append(':').append(data.valueAt(index)?.size ?: 0).append(';')
                    }.let { shortFingerprint(it) }
                }
                val safeName = result.device.name?.trim()?.take(80)?.takeIf { it.all { char -> !char.isISOControl() } } ?: "Dispositivo BLE"
                val identityMaterial = listOf(safeName.lowercase(), services.joinToString(","), manufacturer.orEmpty()).joinToString("|")
                val fingerprint = shortFingerprint(identityMaterial)
                val existing = mutableResults.value.firstOrNull { it.deviceFingerprint == fingerprint }
                val sessionId = existing?.sessionDeviceId ?: UUID.randomUUID().toString()
                deviceMap[sessionId] = result.device
                val candidate = BleDeviceCandidate(sessionId, safeName, fingerprint, services, manufacturer, result.rssi)
                mutableResults.value = (mutableResults.value.filterNot { it.deviceFingerprint == fingerprint } + candidate)
                    .sortedByDescending { it.rssi }
                    .take(50)
            }

            override fun onScanFailed(errorCode: Int) = cancel()
        }
        scanner.startScan(callback)
        timeoutJob = scope.launch {
            delay(config.timeoutSeconds * 1_000L)
            cancel()
        }
    }

    override fun select(sessionDeviceId: String): BleDeviceCandidate? {
        val selected = mutableResults.value.firstOrNull { it.sessionDeviceId == sessionDeviceId } ?: return null
        cancel()
        return selected
    }

    @SuppressLint("MissingPermission")
    override fun cancel() {
        if (!closed.compareAndSet(false, true)) return
        runCatching { scanner.stopScan(callback) }
        timeoutJob.cancel()
        mutableActive.value = false
    }
}

class AndroidBleAssociationManager(
    private val context: Context,
    private val launchChooser: (IntentSender) -> Unit,
) : BleAssociationManager {
    private val inProgress = AtomicBoolean(false)
    private var pending: CompletableDeferred<BleAssociationResult>? = null

    override fun supported(): Boolean = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
        context.packageManager.hasSystemFeature(PackageManager.FEATURE_COMPANION_DEVICE_SETUP)

    override suspend fun request(request: BleAssociationRequest): BleAssociationResult {
        if (!supported()) return BleAssociationResult(BleAssociationState.ERROR_RECOVERABLE, sanitizedCode = "companion_device_unavailable")
        if (!inProgress.compareAndSet(false, true)) return BleAssociationResult(BleAssociationState.SEARCHING, sanitizedCode = "association_in_progress")
        val result = CompletableDeferred<BleAssociationResult>()
        pending = result
        val manager = context.getSystemService(CompanionDeviceManager::class.java)
        val platformRequest = AssociationRequest.Builder().setSingleDevice(request.singleDevice).build()
        @Suppress("DEPRECATION")
        manager.associate(platformRequest, @Suppress("OVERRIDE_DEPRECATION") object : Callback() {
            override fun onDeviceFound(chooserLauncher: IntentSender) {
                launchChooser(chooserLauncher)
            }

            override fun onAssociationPending(intentSender: IntentSender) {
                launchChooser(intentSender)
            }

            override fun onAssociationCreated(associationInfo: AssociationInfo) {
                val associationId = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) associationInfo.id.toLong() else null
                result.complete(BleAssociationResult(BleAssociationState.ASSOCIATED, associationId))
            }

            override fun onFailure(error: CharSequence?) {
                result.complete(BleAssociationResult(BleAssociationState.ERROR_RECOVERABLE, sanitizedCode = "association_failed"))
            }
        }, Handler(Looper.getMainLooper()))
        return try {
            withTimeout(30_000) { result.await() }
        } catch (_: Exception) {
            BleAssociationResult(BleAssociationState.TIMEOUT, sanitizedCode = "association_timeout")
        } finally {
            pending = null
            inProgress.set(false)
        }
    }

    override fun cancel() {
        pending?.complete(BleAssociationResult(BleAssociationState.CANCELLED))
        pending = null
        inProgress.set(false)
    }
}

class AndroidBleGattClient(
    private val context: Context,
    private val scanner: AndroidBleScanner,
) : BleGattClient {
    override suspend fun connect(candidate: BleDeviceCandidate, limits: BleLimits): BleConnection {
        val device = scanner.resolve(candidate) ?: error("scan_candidate_expired")
        return AndroidBleConnection(context, device, candidate, limits)
    }

    @SuppressLint("MissingPermission")
    suspend fun captureNotifications(
        candidate: BleDeviceCandidate,
        serviceUuid: String,
        characteristicUuid: String,
        limits: BleLimits = BleLimits(),
        captureLimits: BleCaptureLimits = BleCaptureLimits(),
    ): BleCapture {
        val device = scanner.resolve(candidate) ?: error("scan_candidate_expired")
        val events = mutableListOf<BleCaptureEvent>()
        val started = System.nanoTime()
        var payloadBytes = 0
        var gatt: BluetoothGatt? = null
        val finished = AtomicBoolean(false)
        fun relativeTime() = ((System.nanoTime() - started) / 1_000_000).coerceAtMost(captureLimits.maximumDurationMs)
        fun result(state: String): BleCapture {
            if (events.lastOrNull()?.connectionState != state && events.size < captureLimits.maximumEvents) {
                events += BleCaptureEvent(eventType = "connection", relativeTimestampMs = relativeTime(), connectionState = state)
            }
            return BleCapture(
                captureId = "cap_${UUID.randomUUID().toString().replace("-", "")}",
                deviceFingerprint = candidate.deviceFingerprint,
                events = events.sortedBy { it.relativeTimestampMs },
            )
        }
        return try {
            withTimeout(limits.connectionTimeoutMs + limits.discoveryTimeoutMs + captureLimits.maximumDurationMs) {
                suspendCancellableCoroutine { continuation ->
                    fun complete(state: String) {
                        if (finished.compareAndSet(false, true) && continuation.isActive) continuation.resume(result(state))
                    }
                    fun accept(bytes: ByteArray) {
                        if (finished.get()) return
                        if (events.size >= captureLimits.maximumEvents - 1) return complete("event_limit")
                        if (payloadBytes + bytes.size > captureLimits.maximumBytes) return complete("byte_limit")
                        payloadBytes += bytes.size
                        events += BleCaptureEvent(
                            serviceUuid = serviceUuid.lowercase(),
                            characteristicUuid = characteristicUuid.lowercase(),
                            eventType = "notification",
                            relativeTimestampMs = relativeTime(),
                            payload = Base64.getEncoder().encodeToString(bytes),
                        )
                    }
                    val callback = object : BluetoothGattCallback() {
                        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
                            if (status != BluetoothGatt.GATT_SUCCESS) return complete("gatt_connection_error")
                            if (newState == android.bluetooth.BluetoothProfile.STATE_CONNECTED) {
                                events += BleCaptureEvent(eventType = "connection", relativeTimestampMs = relativeTime(), connectionState = "connected")
                                if (!gatt.discoverServices()) complete("discovery_not_started")
                            } else if (newState == android.bluetooth.BluetoothProfile.STATE_DISCONNECTED) {
                                complete("disconnected")
                            }
                        }

                        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
                            if (status != BluetoothGatt.GATT_SUCCESS) return complete("gatt_discovery_error")
                            val service = runCatching { gatt.getService(UUID.fromString(serviceUuid)) }.getOrNull()
                                ?: return complete("selected_service_missing")
                            val characteristic = runCatching { service.getCharacteristic(UUID.fromString(characteristicUuid)) }.getOrNull()
                                ?: return complete("selected_characteristic_missing")
                            val supportsNotify = characteristic.properties and BluetoothGattCharacteristic.PROPERTY_NOTIFY != 0
                            val supportsIndicate = characteristic.properties and BluetoothGattCharacteristic.PROPERTY_INDICATE != 0
                            if (!supportsNotify && !supportsIndicate) return complete("selected_characteristic_unsupported")
                            if (!gatt.setCharacteristicNotification(characteristic, true)) return complete("notification_subscription_failed")
                            val cccd = characteristic.getDescriptor(CLIENT_CHARACTERISTIC_CONFIGURATION)
                                ?: return complete("cccd_missing")
                            val value = if (supportsIndicate && !supportsNotify) BluetoothGattDescriptor.ENABLE_INDICATION_VALUE else BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                            val startedWrite = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                                gatt.writeDescriptor(cccd, value) == BluetoothStatusCodes.SUCCESS
                            } else {
                                @Suppress("DEPRECATION")
                                cccd.value = value
                                @Suppress("DEPRECATION")
                                gatt.writeDescriptor(cccd)
                            }
                            if (!startedWrite) complete("cccd_write_failed")
                        }

                        override fun onDescriptorWrite(gatt: BluetoothGatt, descriptor: BluetoothGattDescriptor, status: Int) {
                            if (descriptor.uuid == CLIENT_CHARACTERISTIC_CONFIGURATION && status != BluetoothGatt.GATT_SUCCESS) complete("cccd_write_failed")
                        }

                        @Deprecated("Legacy callback retained for API 26-32")
                        override fun onCharacteristicChanged(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic) {
                            @Suppress("DEPRECATION")
                            accept(characteristic.value?.copyOf() ?: byteArrayOf())
                        }

                        override fun onCharacteristicChanged(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic, value: ByteArray) {
                            accept(value.copyOf())
                        }
                    }
                    gatt = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
                    else @Suppress("DEPRECATION") device.connectGatt(context, false, callback)
                    continuation.invokeOnCancellation {
                        runCatching { gatt?.disconnect() }
                        runCatching { gatt?.close() }
                    }
                }
            }
        } catch (_: kotlinx.coroutines.TimeoutCancellationException) {
            result("timeout")
        } catch (_: SecurityException) {
            result("permission_required")
        } finally {
            runCatching { gatt?.disconnect() }
            runCatching { gatt?.close() }
        }
    }

    private companion object {
        val CLIENT_CHARACTERISTIC_CONFIGURATION: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
    }
}

private class AndroidBleConnection(
    private val context: Context,
    private val device: BluetoothDevice,
    private val candidate: BleDeviceCandidate,
    private val initialLimits: BleLimits,
) : BleConnection {
    private val mutableState = MutableStateFlow(BleGattState.IDLE)
    private val closed = AtomicBoolean(false)
    private var gatt: BluetoothGatt? = null
    override val state: Flow<BleGattState> = mutableState.asStateFlow()

    @SuppressLint("MissingPermission")
    override suspend fun inspect(limits: BleLimits): BleGattInspection = try {
        withTimeout(limits.connectionTimeoutMs + limits.discoveryTimeoutMs) {
            suspendCancellableCoroutine { continuation ->
                val callback = object : BluetoothGattCallback() {
                    override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
                        if (status != BluetoothGatt.GATT_SUCCESS) {
                            mutableState.value = BleGattState.ERROR_RECOVERABLE
                            if (continuation.isActive) continuation.resume(BleGattInspection(BleGattState.ERROR_RECOVERABLE, null, emptyList(), "gatt_connection_error"))
                            return
                        }
                        if (newState == android.bluetooth.BluetoothProfile.STATE_CONNECTED) {
                            mutableState.value = BleGattState.DISCOVERING
                            if (!gatt.discoverServices() && continuation.isActive) {
                                continuation.resume(BleGattInspection(BleGattState.UNSUPPORTED, null, emptyList(), "discovery_not_started"))
                            }
                        } else if (newState == android.bluetooth.BluetoothProfile.STATE_DISCONNECTED && continuation.isActive) {
                            mutableState.value = BleGattState.DISCONNECTED
                            continuation.resume(BleGattInspection(BleGattState.DISCONNECTED, null, emptyList(), "disconnected"))
                        }
                    }

                    override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
                        val inspection = if (status == BluetoothGatt.GATT_SUCCESS) snapshot(gatt.services, limits) else
                            BleGattInspection(BleGattState.ERROR_RECOVERABLE, null, emptyList(), "gatt_discovery_error")
                        mutableState.value = inspection.state
                        if (continuation.isActive) continuation.resume(inspection)
                    }
                }
                mutableState.value = BleGattState.CONNECTING
                gatt = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
                else @Suppress("DEPRECATION") device.connectGatt(context, false, callback)
                continuation.invokeOnCancellation { close() }
            }
        }
    } catch (_: kotlinx.coroutines.TimeoutCancellationException) {
        mutableState.value = BleGattState.TIMEOUT
        BleGattInspection(BleGattState.TIMEOUT, null, emptyList(), "gatt_timeout")
    } catch (_: SecurityException) {
        mutableState.value = BleGattState.PERMISSION_REQUIRED
        BleGattInspection(BleGattState.PERMISSION_REQUIRED, null, emptyList(), "permission_required")
    } finally {
        close()
    }

    private fun snapshot(services: List<BluetoothGattService>, limits: BleLimits): BleGattInspection {
        if (services.size > limits.maximumServices) return BleGattInspection(BleGattState.UNSUPPORTED, null, emptyList(), "service_limit")
        var characteristicCount = 0
        var descriptorCount = 0
        val snapshots = services.map { service ->
            characteristicCount += service.characteristics.size
            BleGattServiceSnapshot(
                uuid = normalizedUuid(service.uuid),
                characteristics = service.characteristics.map { characteristic ->
                    descriptorCount += characteristic.descriptors.size
                    BleGattCharacteristicSnapshot(
                        uuid = normalizedUuid(characteristic.uuid),
                        properties = characteristicProperties(characteristic.properties),
                        descriptorCount = characteristic.descriptors.size,
                    )
                },
            )
        }
        if (characteristicCount > limits.maximumCharacteristics) return BleGattInspection(BleGattState.UNSUPPORTED, null, emptyList(), "characteristic_limit")
        if (descriptorCount > limits.maximumDescriptors) return BleGattInspection(BleGattState.UNSUPPORTED, null, emptyList(), "descriptor_limit")
        val fingerprint = shortFingerprint(snapshots.joinToString("|") { service -> service.uuid + ":" + service.characteristics.joinToString(",") { it.uuid } })
        return BleGattInspection(BleGattState.DISCOVERED, fingerprint, snapshots, "ok")
    }

    @SuppressLint("MissingPermission")
    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        runCatching { gatt?.disconnect() }
        runCatching { gatt?.close() }
        gatt = null
        if (mutableState.value !in setOf(BleGattState.DISCOVERED, BleGattState.TIMEOUT, BleGattState.PERMISSION_REQUIRED, BleGattState.ERROR_RECOVERABLE)) {
            mutableState.value = BleGattState.DISCONNECTED
        }
    }
}
