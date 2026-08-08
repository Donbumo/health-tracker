package io.healthtracker.companion.core.bluetooth

import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow

class FakeBleEnvironment(var current: BleEnvironmentState = BleEnvironmentState.READY) : BleEnvironment {
    override fun state(): BleEnvironmentState = current
}

class FakeBlePermissionController(
    var current: BlePermissionState = BlePermissionState.GRANTED,
    private val permissions: Set<String> = setOf("fixture_scan", "fixture_connect"),
) : BlePermissionController {
    override fun requiredPermissions(): Set<String> = permissions
    override fun state(): BlePermissionState = current
}

class FakeBleScanner : BleScanner {
    var startCount = 0
        private set
    var lastSession: FakeBleScanSession? = null
        private set

    override fun start(config: BleScanConfig): BleScanSession {
        startCount++
        return FakeBleScanSession().also { lastSession = it }
    }
}

class FakeBleScanSession : BleScanSession {
    private val mutableResults = MutableStateFlow<List<BleDeviceCandidate>>(emptyList())
    private val mutableActive = MutableStateFlow(true)
    var cancelCount = 0
        private set
    override val results: Flow<List<BleDeviceCandidate>> = mutableResults.asStateFlow()
    override val active: Flow<Boolean> = mutableActive.asStateFlow()

    fun publish(values: List<BleDeviceCandidate>) {
        if (mutableActive.value) mutableResults.value = values
    }

    override fun select(sessionDeviceId: String): BleDeviceCandidate? {
        val candidate = mutableResults.value.firstOrNull { it.sessionDeviceId == sessionDeviceId } ?: return null
        cancel()
        return candidate
    }

    override fun cancel() {
        if (!mutableActive.value) return
        cancelCount++
        mutableActive.value = false
    }
}

class FakeBleAssociationManager : BleAssociationManager {
    private val active = AtomicBoolean(false)
    var next = BleAssociationResult(BleAssociationState.ASSOCIATED, 1)
    var cancelCount = 0
        private set
    override fun supported(): Boolean = true
    override suspend fun request(request: BleAssociationRequest): BleAssociationResult {
        if (!active.compareAndSet(false, true)) return BleAssociationResult(BleAssociationState.SEARCHING, sanitizedCode = "association_in_progress")
        return try { next } finally { active.set(false) }
    }
    override fun cancel() { cancelCount++; active.set(false) }
}

class FakeBleGattClient(
    var inspection: BleGattInspection = BleGattInspection(BleGattState.DISCOVERED, "f1c710a1f1c710a1f1c710a1", emptyList(), "ok"),
) : BleGattClient {
    var connectCount = 0
        private set
    var lastConnection: FakeBleConnection? = null
        private set
    override suspend fun connect(candidate: BleDeviceCandidate, limits: BleLimits): BleConnection {
        connectCount++
        return FakeBleConnection(inspection).also { lastConnection = it }
    }
}

class FakeBleConnection(private val result: BleGattInspection) : BleConnection {
    private val mutableState = MutableStateFlow(BleGattState.IDLE)
    var closed = false
        private set
    override val state: Flow<BleGattState> = mutableState.asStateFlow()
    override suspend fun inspect(limits: BleLimits): BleGattInspection {
        mutableState.value = result.state
        return result
    }
    override fun close() { closed = true }
}

class FakeBleNotificationStream : BleNotificationStream {
    private val mutableNotifications = MutableSharedFlow<BleNotification>(extraBufferCapacity = 32)
    var closed = false
        private set
    override val notifications: Flow<BleNotification> = mutableNotifications.asSharedFlow()
    fun emit(value: BleNotification): Boolean = mutableNotifications.tryEmit(value)
    override fun close() { closed = true }
}
