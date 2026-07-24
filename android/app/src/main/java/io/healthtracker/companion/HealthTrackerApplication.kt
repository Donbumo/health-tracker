package io.healthtracker.companion

import android.app.Application
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import io.healthtracker.companion.core.config.PreferenceStore
import io.healthtracker.companion.core.database.CompanionDatabase
import io.healthtracker.companion.core.network.ApiClient
import io.healthtracker.companion.core.network.ConnectivityObserver
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
        ProcessLifecycleOwner.get().lifecycle.addObserver(
            object : DefaultLifecycleObserver {
                override fun onStart(owner: LifecycleOwner) {
                    SyncScheduler.enqueueNow(io.healthtracker.companion.core.sync.SyncTrigger.FOREGROUND)
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
}
