package io.healthtracker.companion.core.sync

import android.content.Context
import android.os.SystemClock
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import io.healthtracker.companion.HealthTrackerApplication
import io.healthtracker.companion.core.healthconnect.HealthConnectScheduler
import io.healthtracker.companion.core.model.AppFailure
import io.healthtracker.companion.core.network.CanonicalJson
import java.lang.ref.WeakReference
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.flow.first

class SyncWorker(context: Context, parameters: WorkerParameters) : CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result {
        val app = applicationContext as HealthTrackerApplication
        val local = app.container.preferences.values.first()
        app.container.tokens.bindLegacyServerIfMissing(local.serverUrl)
        val scope = local.accountScope ?: return Result.success()
        if (!local.offlineSessionEligible) return Result.success()
        return try {
            var observedGeneration = SyncScheduler.generation()
            repeat(3) {
                if (app.container.tokens.accessToken(local.serverUrl) == null) {
                    app.container.repository.restoreOnlineSession(scope)
                }
                app.container.engagementRepository.synchronize(scope)
                local.serverUrl?.let { server ->
                    app.container.medicalRepository.synchronize(scope, CanonicalJson.serverIdentity(server))
                }
                app.container.repository.synchronize(scope)
                val nextGeneration = SyncScheduler.generation()
                if (nextGeneration == observedGeneration && !app.container.repository.hasReadyPending(scope)) {
                    return Result.success()
                }
                observedGeneration = nextGeneration
            }
            Result.retry()
        } catch (failure: AppFailure) {
            if (failure.code in DEFINITIVE_SESSION_FAILURES) {
                app.container.repository.clearConfirmedInvalidSession(scope)
                return Result.failure()
            }
            if (failure.retryable) Result.retry() else Result.failure()
        } catch (error: Exception) {
            error.rethrowIfCancellation()
            Result.retry()
        }
    }

    private companion object {
        val DEFINITIVE_SESSION_FAILURES = setOf(
            io.healthtracker.companion.core.model.AppErrorCode.DEVICE_REVOKED,
            io.healthtracker.companion.core.model.AppErrorCode.REFRESH_FAILED,
        )
    }
}

enum class SyncTrigger(val urgent: Boolean) {
    LOGIN_BOOTSTRAP(true),
    DOWNLOAD_ACK(true),
    PENDING_OPERATION(true),
    REFRESH_SUCCESS(true),
    CONNECTIVITY_RECOVERED(false),
    FOREGROUND(false),
}

internal fun shouldEnqueueSync(trigger: SyncTrigger, lastAmbientAt: Long, now: Long, minimumIntervalMs: Long): Boolean =
    trigger.urgent || lastAmbientAt == Long.MIN_VALUE || now - lastAmbientAt >= minimumIntervalMs

object SyncScheduler {
    private var contextReference: WeakReference<Context>? = null
    private val triggerGeneration = AtomicLong(0)
    private val lastAmbientRequestAt = AtomicLong(Long.MIN_VALUE)

    fun initialize(value: Context) { contextReference = WeakReference(value.applicationContext) }

    fun schedulePeriodic() {
        val appContext = contextReference?.get() ?: return
        val request = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(appContext).enqueueUniquePeriodicWork(
            PERIODIC, ExistingPeriodicWorkPolicy.UPDATE, request,
        )
    }

    fun enqueueNow(trigger: SyncTrigger) {
        val appContext = contextReference?.get() ?: return
        val now = SystemClock.elapsedRealtime()
        val previous = lastAmbientRequestAt.get()
        if (!shouldEnqueueSync(trigger, previous, now, AMBIENT_MIN_INTERVAL_MS)) return
        if (!trigger.urgent) lastAmbientRequestAt.set(now)
        triggerGeneration.incrementAndGet()
        val request = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(appContext).enqueueUniqueWork(ONE_TIME, ExistingWorkPolicy.KEEP, request)
    }

    fun cancelAll() {
        val manager = contextReference?.get()?.let { WorkManager.getInstance(it) } ?: return
        manager.cancelUniqueWork(ONE_TIME)
        manager.cancelUniqueWork(PERIODIC)
        HealthConnectScheduler.cancelAll()
    }

    internal fun generation(): Long = triggerGeneration.get()

    private const val PERIODIC = "health_tracker_periodic_sync_v1"
    private const val ONE_TIME = "health_tracker_immediate_sync_v1"
    private const val AMBIENT_MIN_INTERVAL_MS = 5_000L
}
