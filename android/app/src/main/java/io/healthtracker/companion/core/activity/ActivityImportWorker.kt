package io.healthtracker.companion.core.activity

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import io.healthtracker.companion.HealthTrackerApplication
import io.healthtracker.companion.core.model.AppFailure
import io.healthtracker.companion.core.network.CanonicalJson
import java.util.concurrent.TimeUnit
import java.security.MessageDigest
import kotlinx.coroutines.flow.first

class ActivityImportWorker(context: Context, parameters: WorkerParameters) : CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result {
        val scope = inputData.getString(KEY_SCOPE) ?: return Result.failure()
        val identity = inputData.getString(KEY_IDENTITY) ?: return Result.failure()
        val importId = inputData.getString(KEY_IMPORT) ?: return Result.failure()
        val app = applicationContext as HealthTrackerApplication
        val current = app.container.preferences.values.first()
        if (current.accountScope != scope || current.serverUrl == null || CanonicalJson.serverIdentity(current.serverUrl) != identity) {
            return Result.failure()
        }
        return try {
            app.container.activityRepository.uploadAndInspect(scope, identity, importId)
            Result.success()
        } catch (failure: AppFailure) {
            if (failure.retryable) Result.retry() else Result.failure()
        } catch (_: Exception) { Result.retry() }
    }

    companion object {
        const val KEY_SCOPE = "account_scope"; const val KEY_IDENTITY = "server_identity"; const val KEY_IMPORT = "import_id"
    }
}

object ActivityImportScheduler {
    fun enqueue(context: Context, scope: String, identity: String, importId: String) {
        val input = Data.Builder().putString(ActivityImportWorker.KEY_SCOPE, scope)
            .putString(ActivityImportWorker.KEY_IDENTITY, identity).putString(ActivityImportWorker.KEY_IMPORT, importId).build()
        val request = OneTimeWorkRequestBuilder<ActivityImportWorker>()
            .setInputData(input)
            .addTag(scopeTag(scope))
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).build()
        WorkManager.getInstance(context).enqueueUniqueWork(workName(scope, identity, importId), ExistingWorkPolicy.KEEP, request)
    }

    fun cancel(context: Context, scope: String, identity: String, importId: String) =
        WorkManager.getInstance(context).cancelUniqueWork(workName(scope, identity, importId))

    internal fun workName(scope: String, identity: String, importId: String) =
        "activity-import-${short(scope)}-${identity.take(12)}-$importId"
    internal fun scopeTag(scope: String) = "activity-import-scope-${short(scope)}"
    private fun short(value: String) = MessageDigest.getInstance("SHA-256").digest(value.toByteArray()).take(6).joinToString("") { "%02x".format(it) }
}
