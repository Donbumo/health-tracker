package io.healthtracker.companion.core.notifications

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.BackoffPolicy
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import io.healthtracker.companion.HealthTrackerApplication
import io.healthtracker.companion.MainActivity
import io.healthtracker.companion.core.database.CompanionDatabase
import io.healthtracker.companion.core.database.ReminderEventEntity
import io.healthtracker.companion.core.database.ReminderPermissionStateEntity
import io.healthtracker.companion.core.database.ReminderScheduleEntity
import io.healthtracker.companion.core.network.CanonicalJson
import io.healthtracker.companion.core.sync.SyncScheduler
import io.healthtracker.companion.core.sync.SyncTrigger
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.serialization.json.int
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

class AndroidReminderScheduler(
    private val context: Context,
    private val database: CompanionDatabase,
    private val planner: ReminderPlanner = ReminderPlanner(),
) : ReminderScheduler {
    override suspend fun schedule(accountScope: String, serverIdentity: String, rule: ReminderRuleSpec, revision: Int) {
        val occurrence = planner.next(rule, Instant.now()) ?: return cancel(accountScope, serverIdentity, rule.publicId)
        scheduleOccurrence(accountScope, serverIdentity, rule.publicId, revision, occurrence)
    }

    override suspend fun cancel(accountScope: String, serverIdentity: String, rulePublicId: String) {
        WorkManager.getInstance(context).cancelUniqueWork(workName(accountScope, serverIdentity, rulePublicId))
        database.companionDao().deleteReminderSchedule(accountScope, serverIdentity, rulePublicId)
    }

    override suspend fun rescheduleAll(accountScope: String, serverIdentity: String) {
        database.companionDao().enabledReminderRules(accountScope, serverIdentity).forEach { rule ->
            schedule(accountScope, serverIdentity, rule.toDomainSpec(), rule.revision)
        }
    }

    override suspend fun scheduleSnooze(
        accountScope: String, serverIdentity: String, rulePublicId: String, parentEventPublicId: String,
        scheduledLocal: String, revision: Int, instant: Instant,
    ) {
        val name = "reminder_snooze_v1_${(accountScope + serverIdentity + parentEventPublicId + scheduledLocal).hashCode().toUInt()}"
        val delay = Duration.between(Instant.now(), instant).toMillis().coerceAtLeast(0)
        val data = Data.Builder().putString(SCOPE, accountScope).putString(IDENTITY, serverIdentity)
            .putString(RULE, rulePublicId).putString(PARENT_EVENT, parentEventPublicId)
            .putString(SCHEDULED_LOCAL, scheduledLocal).putInt(REVISION, revision).build()
        val request = OneTimeWorkRequestBuilder<SnoozeReminderWorker>().setInputData(data)
            .setInitialDelay(delay, TimeUnit.MILLISECONDS)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).build()
        WorkManager.getInstance(context).enqueueUniqueWork(name, ExistingWorkPolicy.REPLACE, request)
    }

    suspend fun defer(accountScope: String, serverIdentity: String, rulePublicId: String, revision: Int, instant: Instant) {
        val current = database.companionDao().reminderSchedule(accountScope, serverIdentity, rulePublicId) ?: return
        enqueue(current.workName, accountScope, serverIdentity, rulePublicId, revision, instant)
    }

    private suspend fun scheduleOccurrence(
        scope: String, identity: String, ruleId: String, revision: Int, occurrence: PlannedOccurrence,
    ) {
        val name = workName(scope, identity, ruleId)
        database.companionDao().upsertReminderSchedule(ReminderScheduleEntity(
            scope, identity, ruleId, occurrence.localDateTime.toString(), occurrence.instant.toString(),
            occurrence.instant.toEpochMilli(), occurrence.timezone.id, revision, name, Instant.now().toString(),
        ))
        enqueue(name, scope, identity, ruleId, revision, occurrence.instant)
    }

    private fun enqueue(name: String, scope: String, identity: String, ruleId: String, revision: Int, instant: Instant) {
        val delay = Duration.between(Instant.now(), instant).toMillis().coerceAtLeast(0)
        val request = OneTimeWorkRequestBuilder<ReminderWorker>()
            .setInputData(Data.Builder().putString(SCOPE, scope).putString(IDENTITY, identity)
                .putString(RULE, ruleId).putInt(REVISION, revision).build())
            .setInitialDelay(delay, TimeUnit.MILLISECONDS)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(name, ExistingWorkPolicy.REPLACE, request)
    }

    companion object {
        const val SCOPE = "account_scope"
        const val IDENTITY = "server_identity"
        const val RULE = "rule_public_id"
        const val REVISION = "rule_revision"
        const val PARENT_EVENT = "parent_event_public_id"
        const val SCHEDULED_LOCAL = "scheduled_local"
        fun workName(scope: String, identity: String, ruleId: String): String =
            "reminder_v1_${shortHash("$scope|$identity|$ruleId")}" 
        private fun shortHash(value: String) = java.security.MessageDigest.getInstance("SHA-256")
            .digest(value.toByteArray()).take(12).joinToString("") { "%02x".format(it) }
    }
}

class ReminderWorker(context: Context, parameters: WorkerParameters) : CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result {
        val app = applicationContext as HealthTrackerApplication
        val scope = inputData.getString(AndroidReminderScheduler.SCOPE) ?: return Result.success()
        val identity = inputData.getString(AndroidReminderScheduler.IDENTITY) ?: return Result.success()
        val ruleId = inputData.getString(AndroidReminderScheduler.RULE) ?: return Result.success()
        val revision = inputData.getInt(AndroidReminderScheduler.REVISION, -1)
        val preferences = app.container.preferences.values.first()
        if (preferences.accountScope != scope || CanonicalJson.serverIdentity(preferences.serverUrl ?: return Result.success()) != identity) return Result.success()
        val dao = app.container.database.companionDao()
        val rule = dao.reminderRule(scope, identity, ruleId) ?: return Result.success()
        if (!rule.enabled || rule.requiresDeviceConfirmation || rule.revision != revision) return Result.success()
        val schedule = dao.reminderSchedule(scope, identity, ruleId) ?: return Result.success()
        val now = Instant.now()
        val key = ReminderDeduplicator().key(scope, rule.publicId, schedule.scheduledLocal, rule.reminderType, rule.relatedPublicId)
        val zone = ZoneId.of(rule.timezone)
        val dayStart = now.atZone(zone).toLocalDate().atStartOfDay(zone).toInstant().toString()
        val permission = ReminderPermissionController.isGranted(applicationContext)
        val relatedCompleted = (rule.relatedPublicId?.let { dao.planned(scope, it)?.status == "completed" } ?: false) ||
            (rule.goalPublicId?.let { dao.goal(scope, identity, it)?.state != "active" } ?: false)
        val channelTypes = NotificationChannels.eventTypes(NotificationChannels.forType(rule.reminderType))
        val decision = ReminderEvaluator().evaluate(rule.toDomainSpec(), EvaluationContext(
            now, permission, dao.reminderCountSince(scope, identity, rule.reminderType, dayStart),
            dao.reminderChannelCountSince(scope, identity, channelTypes, dayStart),
            dao.reminderGlobalCountSince(scope, identity, dayStart), dao.lastReminderTrigger(scope, identity, rule.reminderType)?.let(Instant::parse),
            relatedCompleted, dao.reminderEventByDedupe(scope, identity, key) != null,
        ))
        if (rule.reminderType == "weekly_summary") {
            val cache = dao.observeAdherence(scope, identity, 7).first()
            val summary = cache?.summaryJson?.let { runCatching { kotlinx.serialization.json.Json.parseToJsonElement(it).jsonObject }.getOrNull() }
            val items = summary?.get("items")?.jsonArray
            val hasData = items?.any { item ->
                val row = item.jsonObject
                (row["completed"]?.jsonPrimitive?.intOrNull ?: 0) > 0 || (row["expected"]?.jsonPrimitive?.intOrNull ?: 0) > 0
            } == true
            if (!WeeklySummaryPolicy.shouldGenerate(items?.isNotEmpty() == true, hasData, rule.enabled)) {
                app.container.reminderScheduler.schedule(scope, identity, rule.toDomainSpec(), revision)
                return Result.success()
            }
        }
        when (decision) {
            is ReminderDecision.Defer -> {
                app.container.reminderScheduler.defer(scope, identity, ruleId, revision, decision.until)
                return Result.success()
            }
            is ReminderDecision.Suppress -> {
                if (decision.reason !in setOf("permission_denied", "rule_disabled")) {
                    app.container.engagementRepository.recordEvent(event(scope, identity, rule, schedule, key, "suppressed", decision.reason))
                }
            }
            ReminderDecision.Deliver -> {
                val event = event(scope, identity, rule, schedule, key, "triggered", null)
                if (app.container.engagementRepository.recordEvent(event)) {
                    NotificationPublisher.show(applicationContext, ReminderNotificationFactory().create(rule.reminderType), event)
                    SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
                }
            }
        }
        app.container.reminderScheduler.schedule(scope, identity, rule.toDomainSpec(), revision)
        return Result.success()
    }

    private fun event(
        scope: String, identity: String, rule: io.healthtracker.companion.core.database.ReminderRuleEntity,
        schedule: ReminderScheduleEntity, key: String, state: String, code: String?,
    ): ReminderEventEntity {
        val now = Instant.now().toString()
        return ReminderEventEntity(scope, identity, UUID.randomUUID().toString(), rule.publicId, null,
            schedule.scheduledInstant, schedule.scheduledLocal, rule.reminderType, rule.relatedPublicId,
            if (state == "triggered") now else null, state, null, null, null, key, code, "pending", 1, now, now)
    }
}

class SnoozeReminderWorker(context: Context, parameters: WorkerParameters) : CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result {
        val app = applicationContext as HealthTrackerApplication
        val scope = inputData.getString(AndroidReminderScheduler.SCOPE) ?: return Result.success()
        val identity = inputData.getString(AndroidReminderScheduler.IDENTITY) ?: return Result.success()
        val ruleId = inputData.getString(AndroidReminderScheduler.RULE) ?: return Result.success()
        val parentId = inputData.getString(AndroidReminderScheduler.PARENT_EVENT) ?: return Result.success()
        val scheduledLocal = inputData.getString(AndroidReminderScheduler.SCHEDULED_LOCAL) ?: return Result.success()
        val revision = inputData.getInt(AndroidReminderScheduler.REVISION, -1)
        val prefs = app.container.preferences.values.first()
        if (prefs.accountScope != scope || CanonicalJson.serverIdentity(prefs.serverUrl ?: return Result.success()) != identity) return Result.success()
        val dao = app.container.database.companionDao()
        val parent = dao.reminderEvent(scope, identity, parentId) ?: return Result.success()
        val rule = dao.reminderRule(scope, identity, ruleId) ?: return Result.success()
        if (parent.state != "snoozed" || !rule.enabled || rule.revision != revision || !ReminderPermissionController.isGranted(applicationContext)) return Result.success()
        val now = Instant.now()
        val zone = ZoneId.of(rule.timezone)
        val dayStart = now.atZone(zone).toLocalDate().atStartOfDay(zone).toInstant().toString()
        val key = ReminderDeduplicator().key(scope, ruleId, scheduledLocal, rule.reminderType, rule.relatedPublicId)
        val decision = ReminderEvaluator().evaluate(rule.toDomainSpec(), EvaluationContext(
            now, true, dao.reminderCountSince(scope, identity, rule.reminderType, dayStart),
            dao.reminderChannelCountSince(scope, identity, NotificationChannels.eventTypes(NotificationChannels.forType(rule.reminderType)), dayStart),
            dao.reminderGlobalCountSince(scope, identity, dayStart), dao.lastReminderTrigger(scope, identity, rule.reminderType)?.let(Instant::parse),
            rule.relatedPublicId?.let { dao.planned(scope, it)?.status == "completed" } ?: false,
            dao.reminderEventByDedupe(scope, identity, key) != null,
        ))
        if (decision is ReminderDecision.Defer) {
            app.container.reminderScheduler.scheduleSnooze(scope, identity, ruleId, parentId, scheduledLocal, revision, decision.until)
            return Result.success()
        }
        if (decision != ReminderDecision.Deliver) return Result.success()
        val timestamp = now.toString()
        val child = ReminderEventEntity(scope, identity, UUID.randomUUID().toString(), ruleId, parentId,
            timestamp, scheduledLocal, rule.reminderType, rule.relatedPublicId, timestamp, "triggered",
            null, null, null, key, null, "pending", 1, timestamp, timestamp)
        if (app.container.engagementRepository.recordEvent(child)) {
            NotificationPublisher.show(applicationContext, ReminderNotificationFactory().create(rule.reminderType), child)
            SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        }
        return Result.success()
    }
}

object NotificationChannelRegistrar {
    fun create(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(NotificationManager::class.java)
        val channels = listOf(
            NotificationChannel(NotificationChannels.WORKOUTS, "Entrenamientos", NotificationManager.IMPORTANCE_DEFAULT),
            NotificationChannel(NotificationChannels.DAILY_HEALTH, "Salud diaria", NotificationManager.IMPORTANCE_DEFAULT),
            NotificationChannel(NotificationChannels.SUMMARIES, "Resúmenes", NotificationManager.IMPORTANCE_LOW),
            NotificationChannel(NotificationChannels.ATTENTION, "Atención requerida", NotificationManager.IMPORTANCE_DEFAULT),
        )
        channels.forEach { channel ->
            channel.description = "Recordatorios locales de Health Tracker"
            channel.lockscreenVisibility = Notification.VISIBILITY_PRIVATE
            channel.enableVibration(false)
        }
        manager.createNotificationChannels(channels)
    }
}

object NotificationPublisher {
    @SuppressLint("MissingPermission")
    fun show(context: Context, safe: SafeNotification, event: ReminderEventEntity) {
        if (!ReminderPermissionController.isGranted(context)) return
        val open = PendingIntent.getActivity(context, stableCode("open|${event.publicId}"), Intent(context, MainActivity::class.java)
            .putExtra("destination", "today"), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val snooze = actionIntent(context, event, ReminderActionReceiver.ACTION_SNOOZE)
        val review = actionIntent(context, event, ReminderActionReceiver.ACTION_ACKNOWLEDGE)
        val notification = NotificationCompat.Builder(context, safe.channelId)
            .setSmallIcon(io.healthtracker.companion.R.drawable.ic_launcher_foreground)
            .setContentTitle(safe.title).setContentText(safe.body).setContentIntent(open).setAutoCancel(true)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setPublicVersion(NotificationCompat.Builder(context, safe.channelId)
                .setSmallIcon(io.healthtracker.companion.R.drawable.ic_launcher_foreground)
                .setContentTitle("Health Tracker").setContentText("Tienes un recordatorio.")
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC).build())
            .setDeleteIntent(actionIntent(context, event, ReminderActionReceiver.ACTION_DISMISS))
            .addAction(0, "Posponer 15 min", snooze).addAction(0, "Revisado", review).build()
        NotificationManagerCompat.from(context).notify(stableCode(event.deduplicationKey), notification)
    }

    @SuppressLint("MissingPermission")
    fun showTest(context: Context): Boolean {
        if (!ReminderPermissionController.isGranted(context)) return false
        val safe = ReminderNotificationFactory().create("weekly_summary")
        val notification = NotificationCompat.Builder(context, safe.channelId)
            .setSmallIcon(io.healthtracker.companion.R.drawable.ic_launcher_foreground)
            .setContentTitle(safe.title).setContentText(safe.body).setVisibility(NotificationCompat.VISIBILITY_PRIVATE).build()
        NotificationManagerCompat.from(context).notify(stableCode("explicit-test"), notification)
        return true
    }

    private fun actionIntent(context: Context, event: ReminderEventEntity, action: String): PendingIntent {
        val intent = Intent(context, ReminderActionReceiver::class.java).setAction(action)
            .putExtra(AndroidReminderScheduler.SCOPE, event.accountScope)
            .putExtra(AndroidReminderScheduler.IDENTITY, event.serverIdentity)
            .putExtra("event_public_id", event.publicId)
        return PendingIntent.getBroadcast(context, stableCode("$action|${event.publicId}"), intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }
    private fun stableCode(value: String) = value.hashCode() and Int.MAX_VALUE
}

object ReminderPermissionController {
    fun isGranted(context: Context): Boolean = Build.VERSION.SDK_INT < 33 ||
        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    suspend fun record(context: Context, database: CompanionDatabase, scope: String, identity: String, requested: Boolean, rationale: Boolean) {
        val granted = isGranted(context)
        val now = Instant.now().toString()
        database.companionDao().upsertReminderPermissionState(ReminderPermissionStateEntity(
            scope, identity, requested, granted, rationale, if (requested && !granted) now else null, now,
        ))
    }
}

class ReminderActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val pendingResult = goAsync()
        val app = context.applicationContext as HealthTrackerApplication
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            try {
                val scope = intent.getStringExtra(AndroidReminderScheduler.SCOPE) ?: return@launch
                val identity = intent.getStringExtra(AndroidReminderScheduler.IDENTITY) ?: return@launch
                val eventId = intent.getStringExtra("event_public_id") ?: return@launch
                val prefs = app.container.preferences.values.first()
                if (prefs.accountScope != scope || CanonicalJson.serverIdentity(prefs.serverUrl ?: return@launch) != identity) return@launch
                val event = app.container.database.companionDao().reminderEvent(scope, identity, eventId) ?: return@launch
                val rule = app.container.database.companionDao().reminderRule(scope, identity, event.rulePublicId) ?: return@launch
                if (!rule.enabled) return@launch
                when (intent.action) {
                    ACTION_SNOOZE -> app.container.engagementRepository.snooze(scope, identity, eventId, 15)
                    ACTION_ACKNOWLEDGE -> app.container.engagementRepository.acknowledge(scope, identity, eventId)
                    ACTION_DISMISS -> app.container.engagementRepository.dismiss(scope, identity, eventId)
                }
                SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
            } finally { pendingResult.finish() }
        }
    }
    companion object {
        const val ACTION_SNOOZE = "io.healthtracker.companion.reminder.SNOOZE"
        const val ACTION_ACKNOWLEDGE = "io.healthtracker.companion.reminder.ACKNOWLEDGE"
        const val ACTION_DISMISS = "io.healthtracker.companion.reminder.DISMISS"
    }
}

class ReminderBootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action !in setOf(Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED, Intent.ACTION_TIMEZONE_CHANGED, Intent.ACTION_TIME_CHANGED)) return
        val request = OneTimeWorkRequestBuilder<ReminderRescheduleWorker>().build()
        WorkManager.getInstance(context).enqueueUniqueWork("reminder_reschedule_v1", ExistingWorkPolicy.REPLACE, request)
    }
}

class ReminderRescheduleWorker(context: Context, parameters: WorkerParameters) : CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result {
        val app = applicationContext as HealthTrackerApplication
        val prefs = app.container.preferences.values.first()
        val scope = prefs.accountScope ?: return Result.success()
        val serverUrl = prefs.serverUrl ?: return Result.success()
        app.container.reminderScheduler.rescheduleAll(scope, CanonicalJson.serverIdentity(serverUrl))
        return Result.success()
    }
}

internal fun io.healthtracker.companion.core.database.ReminderRuleEntity.toDomainSpec() = ReminderRuleSpec(
    publicId, reminderType, java.time.LocalTime.parse(localTime),
    kotlinx.serialization.json.Json.parseToJsonElement(applicableDaysJson).let { it as kotlinx.serialization.json.JsonArray }
        .map { it.jsonPrimitive.int }.toSet(), ZoneId.of(timezone), quietStart?.let(java.time.LocalTime::parse),
    quietEnd?.let(java.time.LocalTime::parse), quietTimezone?.let(ZoneId::of), maxPerDay, cooldownMinutes, enabled, relatedPublicId,
)
