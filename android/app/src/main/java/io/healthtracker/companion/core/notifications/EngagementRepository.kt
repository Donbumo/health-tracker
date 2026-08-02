package io.healthtracker.companion.core.notifications

import androidx.room.withTransaction
import io.healthtracker.companion.core.database.AdherenceCacheEntity
import io.healthtracker.companion.core.database.CompanionDatabase
import io.healthtracker.companion.core.database.GoalEntity
import io.healthtracker.companion.core.database.PendingActionEntity
import io.healthtracker.companion.core.database.ReminderEventEntity
import io.healthtracker.companion.core.database.ReminderRuleEntity
import io.healthtracker.companion.core.network.ApiClient
import io.healthtracker.companion.core.network.CanonicalJson
import io.healthtracker.companion.core.sync.rethrowIfCancellation
import java.time.Instant
import java.time.LocalDate
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

class EngagementRepository(
    private val database: CompanionDatabase,
    private val api: ApiClient,
    private val scheduler: ReminderScheduler,
) : ReminderActionHandler {
    private val dao = database.companionDao()

    suspend fun identity(scope: String): String? = dao.account(scope)?.let { CanonicalJson.serverIdentity(it.serverUrl) }

    fun observeGoals(scope: String, serverIdentity: String): Flow<List<GoalEntity>> = dao.observeGoals(scope, serverIdentity)
    fun observeRules(scope: String, serverIdentity: String): Flow<List<ReminderRuleEntity>> = dao.observeReminderRules(scope, serverIdentity)
    fun observeEvents(scope: String, serverIdentity: String): Flow<List<ReminderEventEntity>> = dao.observeReminderEvents(scope, serverIdentity)
    fun observeAdherence(scope: String, serverIdentity: String, days: Int): Flow<AdherenceCacheEntity?> =
        dao.observeAdherence(scope, serverIdentity, days)
    fun observePermission(scope: String, serverIdentity: String) = dao.observeReminderPermissionState(scope, serverIdentity)

    suspend fun recordPermission(scope: String, requested: Boolean, rationaleShown: Boolean, granted: Boolean) {
        val identity = requireIdentity(scope)
        val now = Instant.now().toString()
        dao.upsertReminderPermissionState(io.healthtracker.companion.core.database.ReminderPermissionStateEntity(
            scope, identity, requested, granted, rationaleShown, if (requested && !granted) now else null, now,
        ))
    }

    suspend fun cleanOldEvents(scope: String): Int {
        val identity = requireIdentity(scope)
        return dao.deleteOldReminderEvents(scope, identity, Instant.now().minusSeconds(30L * 24 * 60 * 60).toString())
    }

    suspend fun createGoal(scope: String, payload: JsonObject): String {
        val identity = requireIdentity(scope)
        val now = Instant.now().toString()
        val publicId = payload.string("public_id") ?: UUID.randomUUID().toString()
        val finalPayload = JsonObject(payload + ("public_id" to JsonPrimitive(publicId)))
        val local = goalFromJson(scope, identity, finalPayload, "pending", now)
        database.withTransaction {
            dao.upsertGoal(local)
            queueLocked(scope, "engagement_goal_create", publicId, finalPayload)
        }
        return publicId
    }

    suspend fun updateGoal(scope: String, publicId: String, changes: JsonObject) {
        val identity = requireIdentity(scope)
        val current = dao.goal(scope, identity, publicId) ?: return
        val payload = goalPayload(current, changes)
        database.withTransaction {
            dao.upsertGoal(goalFromJson(scope, identity, payload, "pending", current.createdAt))
            queueMutationLocked(scope, "engagement_goal", publicId, payload)
        }
    }

    suspend fun archiveGoal(scope: String, publicId: String) {
        val identity = requireIdentity(scope)
        val current = dao.goal(scope, identity, publicId) ?: return
        val create = dao.pendingAction(scope, publicId, "engagement_goal_create")
        database.withTransaction {
            if (create != null) {
                dao.deletePendingForEntity(scope, publicId)
                dao.deleteGoal(scope, identity, publicId)
            } else {
                dao.upsertGoal(current.copy(state = "archived", syncStatus = "pending", updatedAt = Instant.now().toString()))
                queueLocked(scope, "engagement_goal_delete", publicId, buildJsonObject { put("base_revision", current.revision) })
            }
        }
    }

    suspend fun createRule(scope: String, payload: JsonObject): String {
        val identity = requireIdentity(scope)
        val now = Instant.now().toString()
        val publicId = payload.string("public_id") ?: UUID.randomUUID().toString()
        val finalPayload = JsonObject(payload + ("public_id" to JsonPrimitive(publicId)))
        val local = ruleFromJson(scope, identity, finalPayload, "pending", now)
        database.withTransaction {
            dao.upsertReminderRule(local)
            queueLocked(scope, "engagement_rule_create", publicId, finalPayload)
        }
        scheduleLocal(local)
        return publicId
    }

    suspend fun updateRule(scope: String, publicId: String, changes: JsonObject) {
        val identity = requireIdentity(scope)
        val current = dao.reminderRule(scope, identity, publicId) ?: return
        val payload = rulePayload(current, changes)
        val updated = ruleFromJson(scope, identity, payload, "pending", current.createdAt)
        database.withTransaction {
            dao.upsertReminderRule(updated)
            queueMutationLocked(scope, "engagement_rule", publicId, payload)
        }
        scheduleLocal(updated)
    }

    suspend fun deleteRule(scope: String, publicId: String) {
        val identity = requireIdentity(scope)
        val current = dao.reminderRule(scope, identity, publicId) ?: return
        val create = dao.pendingAction(scope, publicId, "engagement_rule_create")
        database.withTransaction {
            dao.deleteReminderSchedule(scope, identity, publicId)
            if (create != null) {
                dao.deletePendingForEntity(scope, publicId)
                dao.deleteReminderRule(scope, identity, publicId)
            } else {
                dao.upsertReminderRule(current.copy(enabled = false, syncStatus = "pending", updatedAt = Instant.now().toString()))
                queueLocked(scope, "engagement_rule_delete", publicId, buildJsonObject { put("base_revision", current.revision) })
            }
        }
        scheduler.cancel(scope, identity, publicId)
    }

    suspend fun recordEvent(event: ReminderEventEntity): Boolean {
        val inserted = dao.insertReminderEvent(event) != -1L
        if (inserted) queue(scope = event.accountScope, type = "engagement_event_create", entityId = event.publicId, payload = eventPayload(event))
        return inserted
    }

    override suspend fun acknowledge(accountScope: String, serverIdentity: String, eventPublicId: String) =
        updateEvent(accountScope, serverIdentity, eventPublicId, "acknowledge", null)

    override suspend fun dismiss(accountScope: String, serverIdentity: String, eventPublicId: String) =
        updateEvent(accountScope, serverIdentity, eventPublicId, "dismiss", null)

    override suspend fun snooze(accountScope: String, serverIdentity: String, eventPublicId: String, minutes: Int?) {
        val event = dao.reminderEvent(accountScope, serverIdentity, eventPublicId) ?: return
        val rule = dao.reminderRule(accountScope, serverIdentity, event.rulePublicId) ?: return
        val now = Instant.now()
        val until = if (minutes == null) {
            val zone = java.time.ZoneId.of(rule.timezone)
            val tomorrow = now.atZone(zone).toLocalDate().plusDays(1).atTime(java.time.LocalTime.parse(rule.localTime))
            ReminderPlanner().resolve(tomorrow, zone).instant
        } else now.plusSeconds(minutes * 60L)
        updateEvent(accountScope, serverIdentity, eventPublicId, "snooze", until.toString())
        scheduler.scheduleSnooze(
            accountScope, serverIdentity, rule.publicId, event.publicId,
            "${event.scheduledLocal}|snooze|$until", rule.revision, until,
        )
    }

    private suspend fun updateEvent(scope: String, identity: String, eventId: String, action: String, until: String?) {
        val event = dao.reminderEvent(scope, identity, eventId) ?: return
        val now = Instant.now().toString()
        val payload = buildJsonObject {
            put("base_revision", event.revision); put("action", action)
            if (until != null) put("snoozed_until", until)
        }
        val updated = when (action) {
            "acknowledge" -> event.copy(state = "acknowledged", acknowledgedAt = now)
            "dismiss" -> event.copy(state = "dismissed", dismissedAt = now)
            else -> event.copy(state = "snoozed", snoozedUntil = until)
        }.copy(syncStatus = "pending", revision = event.revision + 1, updatedAt = now)
        database.withTransaction { dao.upsertReminderEvent(updated); queueLocked(scope, "engagement_event_update", eventId, payload) }
    }

    suspend fun synchronize(scope: String) {
        val identity = requireIdentity(scope)
        repeat(100) {
            val pending = dao.readyEngagementPending(scope, System.currentTimeMillis(), 1).firstOrNull() ?: return@repeat
            try {
                val payload = api.json.parseToJsonElement(pending.payloadJson).jsonObject
                when (pending.actionType) {
                    "engagement_goal_create" -> saveGoal(scope, identity, api.createGoal(payload, pending.idempotencyKey))
                    "engagement_goal_update" -> saveGoal(scope, identity, api.patchGoal(pending.entityId, payload, pending.idempotencyKey))
                    "engagement_goal_delete" -> saveGoal(scope, identity, api.deleteGoal(pending.entityId, payload, pending.idempotencyKey))
                    "engagement_rule_create" -> saveRule(scope, identity, api.createReminderRule(payload, pending.idempotencyKey))
                    "engagement_rule_update" -> saveRule(scope, identity, api.patchReminderRule(pending.entityId, payload, pending.idempotencyKey))
                    "engagement_rule_delete" -> { api.deleteReminderRule(pending.entityId, payload, pending.idempotencyKey); dao.deleteReminderRule(scope, identity, pending.entityId) }
                    "engagement_event_create" -> saveEvent(scope, identity, api.createReminderEvent(payload, pending.idempotencyKey))
                    "engagement_event_update" -> saveEvent(scope, identity, api.patchReminderEvent(pending.entityId, payload, pending.idempotencyKey))
                    else -> return@repeat
                }
                dao.deletePending(pending.localId)
            } catch (error: Exception) {
                error.rethrowIfCancellation()
                dao.updatePending(pending.localId, "pending", "engagement_sync_failed", System.currentTimeMillis() + 60_000L)
                return@repeat
            }
        }
        refresh(scope, identity)
    }

    suspend fun refresh(scope: String, suppliedIdentity: String? = null) {
        val identity = suppliedIdentity ?: requireIdentity(scope)
        val now = Instant.now().toString()
        val goals = api.goals()["items"]?.jsonArray.orEmpty().map { goalFromJson(scope, identity, it.jsonObject, "synced", now) }
        val rules = api.reminderRules()["items"]?.jsonArray.orEmpty().map { ruleFromJson(scope, identity, it.jsonObject, "synced", now) }
        database.withTransaction { dao.upsertGoals(goals); dao.upsertReminderRules(rules) }
        for (rule in rules) scheduleLocal(rule)
        val timezone = dao.account(scope)?.timezone ?: "UTC"
        for (days in listOf(7, 30, 90)) {
            val summary = api.adherenceSummary(days, timezone)
            val period = summary["period"]!!.jsonObject
            dao.upsertAdherenceCache(AdherenceCacheEntity(
                scope, identity, days, period.string("from")!!, period.string("to")!!,
                period.string("timezone")!!, summary.string("status")!!, summary.toString(), now,
            ))
        }
    }

    private suspend fun saveGoal(scope: String, identity: String, json: JsonObject) =
        dao.upsertGoal(goalFromJson(scope, identity, json, "synced", Instant.now().toString()))
    private suspend fun saveRule(scope: String, identity: String, json: JsonObject) {
        val rule = ruleFromJson(scope, identity, json, "synced", Instant.now().toString())
        dao.upsertReminderRule(rule); scheduleLocal(rule)
    }
    private suspend fun saveEvent(scope: String, identity: String, json: JsonObject) {
        val mapped = eventFromJson(scope, identity, json, "synced", Instant.now().toString())
        val existing = dao.reminderEvent(scope, identity, mapped.publicId)
        dao.upsertReminderEvent(if (existing == null) mapped else mapped.copy(
            parentEventPublicId = existing.parentEventPublicId,
            deduplicationKey = existing.deduplicationKey,
        ))
    }

    private suspend fun scheduleLocal(rule: ReminderRuleEntity) {
        val spec = rule.toSpec()
        if (!rule.enabled || rule.requiresDeviceConfirmation) scheduler.cancel(rule.accountScope, rule.serverIdentity, rule.publicId)
        else scheduler.schedule(rule.accountScope, rule.serverIdentity, spec, rule.revision)
    }

    private suspend fun queue(scope: String, type: String, entityId: String, payload: JsonObject) =
        database.withTransaction { queueLocked(scope, type, entityId, payload) }

    private suspend fun queueMutationLocked(scope: String, prefix: String, entityId: String, payload: JsonObject) {
        val create = dao.pendingAction(scope, entityId, "${prefix}_create")
        if (create != null) dao.updatePendingEntity(create.copy(payloadJson = payload.toString(), payloadHash = CanonicalJson.sha256(payload)))
        else {
            dao.pendingAction(scope, entityId, "${prefix}_update")?.let { dao.deletePending(it.localId) }
            queueLocked(scope, "${prefix}_update", entityId, payload)
        }
    }

    private suspend fun queueLocked(scope: String, type: String, entityId: String, payload: JsonObject) {
        dao.insertPending(PendingActionEntity(
            accountScope = scope, actionType = type, entityId = entityId,
            idempotencyKey = UUID.randomUUID().toString(), payloadJson = payload.toString(),
            payloadHash = CanonicalJson.sha256(payload), createdAt = Instant.now().toString(),
        ))
    }

    private suspend fun requireIdentity(scope: String): String = identity(scope) ?: error("account_missing")
}

private fun GoalEntity.toJson(): JsonObject = buildJsonObject {
    put("public_id", publicId); put("goal_type", goalType); put("target_value", targetValue); put("unit", unit)
    put("period", period); put("applicable_days", JsonArray(parseArray(applicableDaysJson))); put("timezone", timezone)
    put("start_date", startDate); putNullable("end_date", endDate); put("state", state); putNullable("related_public_id", relatedPublicId)
}

private fun goalPayload(current: GoalEntity, changes: JsonObject): JsonObject = JsonObject(current.toJson() + changes + ("base_revision" to JsonPrimitive(current.revision)))

private fun goalFromJson(scope: String, identity: String, value: JsonObject, sync: String, fallbackCreated: String): GoalEntity = GoalEntity(
    scope, identity, value.string("public_id")!!, value.string("goal_type")!!, value.string("target_value")!!,
    value.string("unit")!!, value.string("period")!!, value["applicable_days"]?.toString() ?: "[]",
    value.string("timezone")!!, value.string("start_date")!!, value.string("end_date"), value.string("state") ?: "active",
    value.int("revision") ?: 1, value.string("source") ?: "manual", value.string("related_public_id"), sync,
    value.string("created_at") ?: fallbackCreated, value.string("updated_at") ?: Instant.now().toString(),
)

private fun ReminderRuleEntity.toJson(): JsonObject = buildJsonObject {
    put("public_id", publicId); put("reminder_type", reminderType); putNullable("goal_public_id", goalPublicId)
    put("local_time", localTime); put("applicable_days", JsonArray(parseArray(applicableDaysJson))); put("lead_minutes", leadMinutes)
    putNullable("quiet_start", quietStart); putNullable("quiet_end", quietEnd); putNullable("quiet_timezone", quietTimezone)
    put("snooze_options", JsonArray(parseArray(snoozeOptionsJson))); put("max_per_day", maxPerDay); put("cooldown_minutes", cooldownMinutes)
    put("enabled", enabled); put("timezone", timezone); putNullable("related_public_id", relatedPublicId)
}

private fun rulePayload(current: ReminderRuleEntity, changes: JsonObject): JsonObject = JsonObject(current.toJson() + changes + ("base_revision" to JsonPrimitive(current.revision)))

private fun ruleFromJson(scope: String, identity: String, value: JsonObject, sync: String, fallbackCreated: String): ReminderRuleEntity = ReminderRuleEntity(
    scope, identity, value.string("public_id")!!, value.string("reminder_type")!!, value.string("goal_public_id"),
    value.string("local_time")!!, value["applicable_days"]?.toString() ?: "[]", value.int("lead_minutes") ?: 0,
    value.string("quiet_start"), value.string("quiet_end"), value.string("quiet_timezone"), value["snooze_options"]?.toString() ?: "[15,30,60,\"tomorrow\"]",
    value.int("max_per_day") ?: 1, value.int("cooldown_minutes") ?: 0, value.boolean("enabled") ?: false,
    value.int("revision") ?: 1, value.string("timezone") ?: "UTC", value.string("next_occurrence"), value.string("last_triggered_at"),
    value.string("last_acknowledged_at"), value.string("related_public_id"), value.string("source") ?: "manual",
    value.boolean("requires_device_confirmation") ?: false, sync, value.string("created_at") ?: fallbackCreated,
    value.string("updated_at") ?: Instant.now().toString(),
)

private fun ReminderRuleEntity.toSpec() = ReminderRuleSpec(
    publicId, reminderType, java.time.LocalTime.parse(localTime), parseArray(applicableDaysJson).map { it.jsonPrimitive.int }.toSet(),
    java.time.ZoneId.of(timezone), quietStart?.let(java.time.LocalTime::parse), quietEnd?.let(java.time.LocalTime::parse),
    quietTimezone?.let(java.time.ZoneId::of), maxPerDay, cooldownMinutes, enabled, relatedPublicId,
)

private fun eventPayload(event: ReminderEventEntity) = buildJsonObject {
    put("public_id", event.publicId); put("rule_public_id", event.rulePublicId); put("scheduled_for", event.scheduledFor)
    put("scheduled_local", event.scheduledLocal); put("event_type", event.eventType); putNullable("related_public_id", event.relatedPublicId)
    putNullable("triggered_at", event.triggeredAt); put("state", event.state)
}

private fun eventFromJson(scope: String, identity: String, value: JsonObject, sync: String, fallbackCreated: String) = ReminderEventEntity(
    scope, identity, value.string("public_id")!!, value.string("rule_public_id")!!, null, value.string("scheduled_for")!!,
    value.string("scheduled_local")!!, value.string("event_type")!!, value.string("related_public_id"), value.string("triggered_at"),
    value.string("state")!!, value.string("acknowledged_at"), value.string("snoozed_until"), value.string("dismissed_at"),
    value.string("deduplication_fingerprint") ?: "server:${value.string("public_id")}", value.string("error_code"), sync,
    value.int("revision") ?: 1, value.string("created_at") ?: fallbackCreated, value.string("updated_at") ?: Instant.now().toString(),
)

private fun JsonObject.string(name: String): String? = get(name)?.let { if (it is JsonNull) null else it.jsonPrimitive.contentOrNull }
private fun JsonObject.int(name: String): Int? = get(name)?.jsonPrimitive?.intOrNull
private fun JsonObject.boolean(name: String): Boolean? = get(name)?.jsonPrimitive?.contentOrNull?.toBooleanStrictOrNull()
private fun parseArray(value: String) = runCatching { kotlinx.serialization.json.Json.parseToJsonElement(value).jsonArray.toList() }.getOrDefault(emptyList())
private fun kotlinx.serialization.json.JsonObjectBuilder.putNullable(name: String, value: String?) {
    if (value == null) put(name, JsonNull) else put(name, value)
}
