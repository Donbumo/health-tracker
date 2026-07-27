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
import io.healthtracker.companion.core.security.SecureTokenStore
import io.healthtracker.companion.core.sync.CompanionRepository
import io.healthtracker.companion.core.sync.SyncScheduler

class HealthTrackerApplication : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
        SyncScheduler.initialize(this)
        SyncScheduler.schedulePeriodic()
        HealthConnectScheduler.initialize(this)
        HealthConnectScheduler.schedulePeriodic()
        ProcessLifecycleOwner.get().lifecycle.addObserver(
            object : DefaultLifecycleObserver {
                override fun onStart(owner: LifecycleOwner) {
                    SyncScheduler.enqueueNow(io.healthtracker.companion.core.sync.SyncTrigger.FOREGROUND)
                    HealthConnectScheduler.enqueue(HealthConnectTrigger.FOREGROUND)
                }
            },
        )
    }
}

class AppContainer(application: Application) {
    val preferences = PreferenceStore(application)
    val tokens = SecureTokenStore(application)
    val database = CompanionDatabase.create(application)
    val api = ApiClient(preferences, tokens)
    val connectivity = ConnectivityObserver(application)
    val repository = CompanionRepository(database, preferences, tokens, api)
    val healthConnectGateway = AndroidHealthConnectGateway(application)
    val healthConnectStore = HealthConnectStore(database)
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
}
