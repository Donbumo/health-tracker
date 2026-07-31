package io.healthtracker.companion

import android.app.Application
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import io.healthtracker.companion.core.config.PreferenceStore
import io.healthtracker.companion.core.database.CompanionDatabase
import io.healthtracker.companion.core.network.ApiClient
import io.healthtracker.companion.core.network.ConnectivityObserver
import io.healthtracker.companion.core.healthconnect.AndroidHealthConnectGateway
import io.healthtracker.companion.core.healthconnect.HealthConnectManager
import io.healthtracker.companion.core.healthconnect.HealthConnectScheduler
import io.healthtracker.companion.core.healthconnect.HealthConnectStore
import io.healthtracker.companion.core.healthconnect.HealthConnectSyncCoordinator
import io.healthtracker.companion.core.healthconnect.HealthConnectTrigger
import io.healthtracker.companion.core.healthconnect.HealthConnectScaleDiagnosticService
import io.healthtracker.companion.core.external.ExternalSourceStore
import io.healthtracker.companion.core.external.ExternalDeviceManager
import io.healthtracker.companion.core.bluetooth.AndroidBleEnvironment
import io.healthtracker.companion.core.bluetooth.AndroidBlePermissionController
import io.healthtracker.companion.core.bluetooth.AndroidBleScanner
import io.healthtracker.companion.core.bluetooth.AndroidBleGattClient
import io.healthtracker.companion.core.bluetooth.EncryptedBleCaptureStore
import io.healthtracker.companion.core.bluetooth.BleCaptureExporter
import io.healthtracker.companion.core.security.SecureTokenStore
import io.healthtracker.companion.core.sync.CompanionRepository
import io.healthtracker.companion.core.sync.SyncScheduler
import io.healthtracker.companion.core.portability.PortabilityRepository
import io.healthtracker.companion.core.notifications.AndroidReminderScheduler
import io.healthtracker.companion.core.notifications.EngagementRepository
import io.healthtracker.companion.core.notifications.NotificationChannelRegistrar
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

class HealthTrackerApplication : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
        NotificationChannelRegistrar.create(this)
        SyncScheduler.initialize(this)
        SyncScheduler.schedulePeriodic()
        HealthConnectScheduler.initialize(this)
        HealthConnectScheduler.schedulePeriodic()
        ProcessLifecycleOwner.get().lifecycle.addObserver(
            object : DefaultLifecycleObserver {
                override fun onStart(owner: LifecycleOwner) {
                    SyncScheduler.enqueueNow(io.healthtracker.companion.core.sync.SyncTrigger.FOREGROUND)
                    HealthConnectScheduler.enqueue(HealthConnectTrigger.FOREGROUND)
                    val local = container.preferences.values
                    kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.IO).launch {
                        val preferences = local.first()
                        val scope = preferences.accountScope ?: return@launch
                        val server = preferences.serverUrl ?: return@launch
                        container.reminderScheduler.rescheduleAll(scope, io.healthtracker.companion.core.network.CanonicalJson.serverIdentity(server))
                    }
                }

                override fun onStop(owner: LifecycleOwner) {
                    container.externalDeviceManager.cancelScan()
                    container.externalDeviceManager.cancelCapture()
                }
            },
        )
    }
}

class AppContainer(application: Application) {
    private val applicationScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    val preferences = PreferenceStore(application)
    val tokens = SecureTokenStore(application)
    val database = CompanionDatabase.create(application)
    val api = ApiClient(preferences, tokens)
    val connectivity = ConnectivityObserver(application)
    val portabilityRepository = PortabilityRepository(application, database, api)
    val bleCaptureStore = EncryptedBleCaptureStore(application)
    val reminderScheduler = AndroidReminderScheduler(application, database)
    val engagementRepository = EngagementRepository(database, api, reminderScheduler)
    val repository = CompanionRepository(
        database,
        preferences,
        tokens,
        api,
        onBeforeClearAccount = { scope ->
            val identity = engagementRepository.identity(scope)
            if (identity != null) {
                database.companionDao().enabledReminderRules(scope, identity).forEach { rule ->
                    reminderScheduler.cancel(scope, identity, rule.publicId)
                }
            }
            portabilityRepository.fileStore.deleteScope(scope)
            database.companionDao().bleCaptureMetadataForAccount(scope).forEach { metadata ->
                check(bleCaptureStore.deleteEncryptedFile(metadata.encryptedFileName)) { "capture_cleanup_failed" }
            }
        },
    )
    val healthConnectGateway = AndroidHealthConnectGateway(application)
    val healthConnectStore = HealthConnectStore(database)
    val externalSourceStore = ExternalSourceStore(database)
    val healthConnectCoordinator = HealthConnectSyncCoordinator(
        gateway = healthConnectGateway,
        store = healthConnectStore,
        accountZone = { scope ->
            val timezone = database.companionDao().account(scope)?.timezone ?: "UTC"
            runCatching { java.time.ZoneId.of(timezone) }.getOrDefault(java.time.ZoneOffset.UTC)
        },
        onServerQueueReady = { SyncScheduler.enqueueNow(io.healthtracker.companion.core.sync.SyncTrigger.PENDING_OPERATION) },
    )
    val healthConnectManager = HealthConnectManager(healthConnectGateway, healthConnectStore)
    val healthConnectScaleDiagnostic = HealthConnectScaleDiagnosticService(
        healthConnectGateway,
        healthConnectStore::isRecordImported,
        { scope, origin -> externalSourceStore.observeOrigin(scope, origin); Unit },
    )
    val bleEnvironment = AndroidBleEnvironment(application)
    val blePermissionController = AndroidBlePermissionController(application)
    val bleScanner = AndroidBleScanner(application, applicationScope)
    val bleGattClient = AndroidBleGattClient(application, bleScanner)
    val bleCaptureExporter = BleCaptureExporter(application, bleCaptureStore).also { it.cleanupTemporaryExports() }
    val externalDeviceManager = ExternalDeviceManager(
        database,
        bleEnvironment,
        blePermissionController,
        bleScanner,
        bleGattClient,
        bleCaptureStore,
        applicationScope,
    )
}
