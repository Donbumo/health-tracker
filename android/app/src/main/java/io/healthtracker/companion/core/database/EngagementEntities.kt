package io.healthtracker.companion.core.database

import androidx.room.Entity
import androidx.room.Index

@Entity(
    tableName = "goals",
    primaryKeys = ["accountScope", "serverIdentity", "publicId"],
    indices = [
        Index(value = ["accountScope", "serverIdentity", "state", "updatedAt"]),
        Index(value = ["accountScope", "serverIdentity", "goalType"]),
    ],
)
data class GoalEntity(
    val accountScope: String,
    val serverIdentity: String,
    val publicId: String,
    val goalType: String,
    val targetValue: String,
    val unit: String,
    val period: String,
    val applicableDaysJson: String,
    val timezone: String,
    val startDate: String,
    val endDate: String?,
    val state: String,
    val revision: Int,
    val source: String,
    val relatedPublicId: String?,
    val syncStatus: String,
    val createdAt: String,
    val updatedAt: String,
)

@Entity(
    tableName = "reminder_rules",
    primaryKeys = ["accountScope", "serverIdentity", "publicId"],
    indices = [
        Index(value = ["accountScope", "serverIdentity", "enabled", "nextOccurrence"]),
        Index(value = ["accountScope", "serverIdentity", "goalPublicId"]),
    ],
)
data class ReminderRuleEntity(
    val accountScope: String,
    val serverIdentity: String,
    val publicId: String,
    val reminderType: String,
    val goalPublicId: String?,
    val localTime: String,
    val applicableDaysJson: String,
    val leadMinutes: Int,
    val quietStart: String?,
    val quietEnd: String?,
    val quietTimezone: String?,
    val snoozeOptionsJson: String,
    val maxPerDay: Int,
    val cooldownMinutes: Int,
    val enabled: Boolean,
    val revision: Int,
    val timezone: String,
    val nextOccurrence: String?,
    val lastTriggeredAt: String?,
    val lastAcknowledgedAt: String?,
    val relatedPublicId: String?,
    val source: String,
    val requiresDeviceConfirmation: Boolean,
    val syncStatus: String,
    val createdAt: String,
    val updatedAt: String,
)

@Entity(
    tableName = "reminder_events",
    primaryKeys = ["accountScope", "serverIdentity", "publicId"],
    indices = [
        Index(value = ["accountScope", "serverIdentity", "deduplicationKey"], unique = true),
        Index(value = ["accountScope", "serverIdentity", "state", "scheduledFor"]),
        Index(value = ["accountScope", "serverIdentity", "rulePublicId"]),
    ],
)
data class ReminderEventEntity(
    val accountScope: String,
    val serverIdentity: String,
    val publicId: String,
    val rulePublicId: String,
    val parentEventPublicId: String?,
    val scheduledFor: String,
    val scheduledLocal: String,
    val eventType: String,
    val relatedPublicId: String?,
    val triggeredAt: String?,
    val state: String,
    val acknowledgedAt: String?,
    val snoozedUntil: String?,
    val dismissedAt: String?,
    val deduplicationKey: String,
    val errorCode: String?,
    val syncStatus: String,
    val revision: Int,
    val createdAt: String,
    val updatedAt: String,
)

@Entity(
    tableName = "reminder_schedules",
    primaryKeys = ["accountScope", "serverIdentity", "rulePublicId"],
    indices = [Index(value = ["accountScope", "serverIdentity", "scheduledEpochMillis"])],
)
data class ReminderScheduleEntity(
    val accountScope: String,
    val serverIdentity: String,
    val rulePublicId: String,
    val scheduledLocal: String,
    val scheduledInstant: String,
    val scheduledEpochMillis: Long,
    val timezone: String,
    val ruleRevision: Int,
    val workName: String,
    val updatedAt: String,
)

@Entity(
    tableName = "reminder_permission_state",
    primaryKeys = ["accountScope", "serverIdentity"],
)
data class ReminderPermissionStateEntity(
    val accountScope: String,
    val serverIdentity: String,
    val requested: Boolean,
    val granted: Boolean,
    val rationaleShown: Boolean,
    val deniedAt: String?,
    val checkedAt: String,
)

@Entity(
    tableName = "adherence_cache",
    primaryKeys = ["accountScope", "serverIdentity", "rangeDays"],
    indices = [Index(value = ["accountScope", "serverIdentity", "updatedAt"])],
)
data class AdherenceCacheEntity(
    val accountScope: String,
    val serverIdentity: String,
    val rangeDays: Int,
    val periodFrom: String,
    val periodTo: String,
    val timezone: String,
    val status: String,
    val summaryJson: String,
    val updatedAt: String,
)
