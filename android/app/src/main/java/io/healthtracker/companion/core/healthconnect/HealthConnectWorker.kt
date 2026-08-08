package io.healthtracker.companion.core.healthconnect

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import io.healthtracker.companion.HealthTrackerApplication
import io.healthtracker.companion.core.sync.rethrowIfCancellation
import java.lang.ref.WeakReference
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.flow.first

class HealthConnectWorker(context: Context, parameters: WorkerParameters) : CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result {
        val app = applicationContext as HealthTrackerApplication
        val preferences = app.container.preferences.values.first()
        val scope = preferences.accountScope ?: return Result.success()
        return try {
            app.container.healthConnectCoordinator.sync(scope, inputData.getBoolean(KEY_FOREGROUND, false))
            Result.success()
        } catch (error: Exception) {
            error.rethrowIfCancellation()
            Result.retry()
        }
    }

    companion object { const val KEY_FOREGROUND = "foreground_read" }
}

enum class HealthConnectTrigger(val foreground: Boolean) {
    INITIAL_CONNECTION(true),
    PERMISSIONS_GRANTED(true),
    MANUAL(true),
    FOREGROUND(true),
    SELECTION_CHANGED(true),
    PERIODIC(false),
}

object HealthConnectScheduler {
    private var contextReference: WeakReference<Context>? = null
    fun initialize(context: Context) { contextReference = WeakReference(context.applicationContext) }

    fun schedulePeriodic() {
        val context = contextReference?.get() ?: return
        val request = PeriodicWorkRequestBuilder<HealthConnectWorker>(6, TimeUnit.HOURS)
            .setInputData(Data.Builder().putBoolean(HealthConnectWorker.KEY_FOREGROUND, false).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.UPDATE, request)
    }

    fun enqueue(trigger: HealthConnectTrigger) {
        val context = contextReference?.get() ?: return
        val request = OneTimeWorkRequestBuilder<HealthConnectWorker>()
            .setInputData(Data.Builder().putBoolean(HealthConnectWorker.KEY_FOREGROUND, trigger.foreground).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(ONE_TIME, ExistingWorkPolicy.KEEP, request)
    }

    fun cancelAll() {
        val context = contextReference?.get() ?: return
        WorkManager.getInstance(context).cancelUniqueWork(ONE_TIME)
        WorkManager.getInstance(context).cancelUniqueWork(PERIODIC)
    }

    private const val ONE_TIME = "health_tracker_health_connect_sync_v1"
    private const val PERIODIC = "health_tracker_health_connect_periodic_v1"
}
