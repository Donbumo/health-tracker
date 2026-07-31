package io.healthtracker.companion.core.notifications

import java.security.MessageDigest
import java.time.DateTimeException
import java.time.Instant
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneId

data class ReminderRuleSpec(
    val publicId: String,
    val reminderType: String,
    val localTime: LocalTime,
    val applicableDays: Set<Int>,
    val timezone: ZoneId,
    val quietStart: LocalTime?,
    val quietEnd: LocalTime?,
    val quietTimezone: ZoneId?,
    val maxPerDay: Int,
    val cooldownMinutes: Int,
    val enabled: Boolean,
    val relatedPublicId: String? = null,
)

data class PlannedOccurrence(
    val localDateTime: LocalDateTime,
    val instant: Instant,
    val timezone: ZoneId,
    val adjustedForDstGap: Boolean,
)

interface ReminderScheduler {
    suspend fun schedule(accountScope: String, serverIdentity: String, rule: ReminderRuleSpec, revision: Int)
    suspend fun cancel(accountScope: String, serverIdentity: String, rulePublicId: String)
    suspend fun rescheduleAll(accountScope: String, serverIdentity: String)
    suspend fun scheduleSnooze(
        accountScope: String, serverIdentity: String, rulePublicId: String, parentEventPublicId: String,
        scheduledLocal: String, revision: Int, instant: Instant,
    )
}

class ReminderPlanner {
    fun next(rule: ReminderRuleSpec, after: Instant): PlannedOccurrence? {
        if (!rule.enabled || rule.applicableDays.isEmpty()) return null
        val localAfter = after.atZone(rule.timezone)
        for (offset in 0..14) {
            val day = localAfter.toLocalDate().plusDays(offset.toLong())
            if (day.dayOfWeek.value !in rule.applicableDays) continue
            val resolved = resolve(day.atTime(rule.localTime), rule.timezone)
            if (resolved.instant > after) return resolved
        }
        return null
    }

    fun resolve(local: LocalDateTime, zone: ZoneId): PlannedOccurrence {
        val rules = zone.rules
        val offsets = rules.getValidOffsets(local)
        return when {
            offsets.isNotEmpty() -> {
                // During an overlap choose the earlier offset exactly once.
                val offset = offsets.first()
                PlannedOccurrence(local, local.toInstant(offset), zone, false)
            }
            else -> {
                val transition = rules.getTransition(local)
                    ?: throw DateTimeException("timezone_transition_missing")
                // Preserve the requested minutes by moving forward by the gap size
                // (02:30 becomes 03:30 in a one-hour spring transition).
                val shifted = local.plusSeconds(transition.duration.seconds)
                PlannedOccurrence(shifted, shifted.toInstant(transition.offsetAfter), zone, true)
            }
        }
    }
}

data class EvaluationContext(
    val now: Instant,
    val permissionGranted: Boolean,
    val triggeredTodayForType: Int,
    val triggeredTodayForChannel: Int,
    val triggeredTodayGlobal: Int,
    val lastTriggeredAt: Instant?,
    val relatedActionCompleted: Boolean,
    val dedupeExists: Boolean,
)

sealed interface ReminderDecision {
    data object Deliver : ReminderDecision
    data class Defer(val until: Instant, val reason: String) : ReminderDecision
    data class Suppress(val reason: String) : ReminderDecision
}

class ReminderEvaluator(private val globalDailyLimit: Int = 6, private val channelDailyLimit: Int = 3) {
    fun evaluate(rule: ReminderRuleSpec, context: EvaluationContext): ReminderDecision {
        if (!rule.enabled) return ReminderDecision.Suppress("rule_disabled")
        if (!context.permissionGranted) return ReminderDecision.Suppress("permission_denied")
        if (context.relatedActionCompleted) return ReminderDecision.Suppress("action_completed")
        if (context.dedupeExists) return ReminderDecision.Suppress("duplicate")
        if (context.triggeredTodayGlobal >= globalDailyLimit) return ReminderDecision.Suppress("global_daily_limit")
        if (context.triggeredTodayForChannel >= channelDailyLimit) return ReminderDecision.Suppress("channel_daily_limit")
        if (context.triggeredTodayForType >= rule.maxPerDay) return ReminderDecision.Suppress("rule_daily_limit")
        val cooldownEnd = context.lastTriggeredAt?.plusSeconds(rule.cooldownMinutes * 60L)
        if (cooldownEnd != null && cooldownEnd > context.now) return ReminderDecision.Defer(cooldownEnd, "cooldown")
        quietEnd(rule, context.now)?.let { return ReminderDecision.Defer(it, "quiet_hours") }
        return ReminderDecision.Deliver
    }

    fun quietEnd(rule: ReminderRuleSpec, now: Instant): Instant? {
        val start = rule.quietStart ?: return null
        val end = rule.quietEnd ?: return null
        val zone = rule.quietTimezone ?: rule.timezone
        val local = now.atZone(zone)
        val inQuiet = if (start < end) local.toLocalTime() >= start && local.toLocalTime() < end
            else local.toLocalTime() >= start || local.toLocalTime() < end
        if (!inQuiet) return null
        val endDate = if (start < end || local.toLocalTime() < end) local.toLocalDate() else local.toLocalDate().plusDays(1)
        return ReminderPlanner().resolve(endDate.atTime(end), zone).instant
    }
}

data class SafeNotification(
    val channelId: String,
    val title: String,
    val body: String,
    val visibilityPrivate: Boolean = true,
)

class ReminderNotificationFactory {
    fun create(type: String): SafeNotification = when (type) {
        "scheduled_workout_upcoming", "scheduled_workout_pending" ->
            SafeNotification(NotificationChannels.WORKOUTS, "Health Tracker", "Tienes un entrenamiento programado.")
        "weekly_summary" ->
            SafeNotification(NotificationChannels.SUMMARIES, "Health Tracker", "Tu resumen semanal está disponible.")
        "pending_sync_attention", "conflict_attention" ->
            SafeNotification(NotificationChannels.ATTENTION, "Health Tracker", "Hay un elemento que requiere atención.")
        else -> SafeNotification(NotificationChannels.DAILY_HEALTH, "Health Tracker", "Es momento de revisar tu registro diario.")
    }
}

interface ReminderActionHandler {
    suspend fun acknowledge(accountScope: String, serverIdentity: String, eventPublicId: String)
    suspend fun dismiss(accountScope: String, serverIdentity: String, eventPublicId: String)
    suspend fun snooze(accountScope: String, serverIdentity: String, eventPublicId: String, minutes: Int?)
}

class ReminderDeduplicator {
    fun key(accountScope: String, rulePublicId: String, scheduledLocal: String, eventType: String, relatedPublicId: String?): String {
        val canonical = listOf(accountScope, rulePublicId, scheduledLocal, eventType, relatedPublicId.orEmpty()).joinToString("|")
        return MessageDigest.getInstance("SHA-256").digest(canonical.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
    }
}

object NotificationChannels {
    const val WORKOUTS = "workouts_v1"
    const val DAILY_HEALTH = "daily_health_v1"
    const val SUMMARIES = "summaries_v1"
    const val ATTENTION = "attention_required_v1"
    val ALL = setOf(WORKOUTS, DAILY_HEALTH, SUMMARIES, ATTENTION)
    fun forType(type: String): String = when (type) {
        "scheduled_workout_upcoming", "scheduled_workout_pending" -> WORKOUTS
        "weekly_summary" -> SUMMARIES
        "pending_sync_attention", "conflict_attention" -> ATTENTION
        else -> DAILY_HEALTH
    }

    fun eventTypes(channel: String): List<String> = when (channel) {
        WORKOUTS -> listOf("scheduled_workout_upcoming", "scheduled_workout_pending")
        SUMMARIES -> listOf("weekly_summary")
        ATTENTION -> listOf("pending_sync_attention", "conflict_attention")
        else -> listOf("log_weight", "log_nutrition", "review_steps")
    }
}

data class ReminderPermissionSnapshot(val requested: Boolean, val granted: Boolean)

object ReminderPermissionPolicy {
    fun shouldRequestOnActivation(platformSdk: Int, userActivatedFirstRule: Boolean, state: ReminderPermissionSnapshot?): Boolean =
        platformSdk >= 33 && userActivatedFirstRule && state?.granted != true && state?.requested != true
}

object WeeklySummaryPolicy {
    fun shouldGenerate(hasGoals: Boolean, hasData: Boolean, enabled: Boolean): Boolean = enabled && hasGoals && hasData
}
