package io.healthtracker.companion.core.notifications

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.healthtracker.companion.core.config.PreferenceStore
import io.healthtracker.companion.core.database.AccountEntity
import io.healthtracker.companion.core.database.CompanionDatabase
import io.healthtracker.companion.core.database.ReminderEventEntity
import io.healthtracker.companion.core.network.ApiClient
import io.healthtracker.companion.core.security.SecureTokenStore
import java.time.Instant
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class EngagementOfflineTest {
    private val context get() = ApplicationProvider.getApplicationContext<android.content.Context>()
    private lateinit var database: CompanionDatabase
    private lateinit var repository: EngagementRepository
    private val scheduler = FakeScheduler()

    @Before fun create() = runBlocking {
        database = Room.inMemoryDatabaseBuilder(context, CompanionDatabase::class.java).allowMainThreadQueries().build()
        database.companionDao().upsertAccount(AccountEntity(
            SCOPE, "https://qa.invalid", "qa-user", "qa@example.invalid", "qa-device", "UTC", Instant.now().toString(),
        ))
        repository = EngagementRepository(database, ApiClient(PreferenceStore(context), SecureTokenStore(context)), scheduler)
    }

    @After fun close() = database.close()

    @Test fun offlineGoalCreateUpdateDeleteCoalescesWithoutHttp() = runBlocking {
        val id = repository.createGoal(SCOPE, goalPayload())
        repository.updateGoal(SCOPE, id, buildJsonObject { put("target_value", "4") })
        val identity = repository.identity(SCOPE)!!
        assertEquals("4", database.companionDao().goal(SCOPE, identity, id)?.targetValue)
        assertEquals(listOf("engagement_goal_create"), database.companionDao().queuedActions(SCOPE, 10).map { it.actionType })
        repository.archiveGoal(SCOPE, id)
        assertTrue(database.companionDao().observeGoals(SCOPE, identity).first().isEmpty())
        assertTrue(database.companionDao().queuedActions(SCOPE, 10).isEmpty())
    }

    @Test fun ruleDisableCancelsScheduleAndDedupeLedgerRejectsDoubleWorker() = runBlocking {
        val ruleId = repository.createRule(SCOPE, rulePayload())
        val identity = repository.identity(SCOPE)!!
        val rule = database.companionDao().reminderRule(SCOPE, identity, ruleId)!!
        repository.updateRule(SCOPE, ruleId, buildJsonObject { put("enabled", false) })
        assertTrue(ruleId in scheduler.cancelled)
        val now = Instant.now().toString()
        val event = ReminderEventEntity(SCOPE, identity, "event-a", ruleId, null, now, "2026-07-31T18:00",
            rule.reminderType, null, now, "triggered", null, null, null, "same-dedupe", null, "pending", 1, now, now)
        val duplicate = event.copy(publicId = "event-b")
        assertTrue(repository.recordEvent(event))
        assertFalse(repository.recordEvent(duplicate))
        assertEquals(1, database.companionDao().observeReminderEvents(SCOPE, identity).first().size)
    }

    private fun goalPayload() = buildJsonObject {
        put("public_id", "91000000-0000-4000-8000-000000000018"); put("goal_type", "training_sessions_per_week")
        put("target_value", "3"); put("unit", "session"); put("period", "weekly")
        put("applicable_days", JsonArray((1..7).map(::JsonPrimitive))); put("timezone", "UTC"); put("start_date", "2026-07-31")
    }
    private fun rulePayload() = buildJsonObject {
        put("public_id", "92000000-0000-4000-8000-000000000018"); put("reminder_type", "log_weight")
        put("local_time", "08:00"); put("applicable_days", JsonArray(listOf(JsonPrimitive(1))))
        put("lead_minutes", 0); put("snooze_options", JsonArray(listOf(JsonPrimitive(15))))
        put("max_per_day", 1); put("cooldown_minutes", 60); put("enabled", true); put("timezone", "UTC")
    }

    private class FakeScheduler : ReminderScheduler {
        val cancelled = mutableSetOf<String>()
        override suspend fun schedule(accountScope: String, serverIdentity: String, rule: ReminderRuleSpec, revision: Int) = Unit
        override suspend fun cancel(accountScope: String, serverIdentity: String, rulePublicId: String) { cancelled += rulePublicId }
        override suspend fun rescheduleAll(accountScope: String, serverIdentity: String) = Unit
        override suspend fun scheduleSnooze(accountScope: String, serverIdentity: String, rulePublicId: String, parentEventPublicId: String, scheduledLocal: String, revision: Int, instant: Instant) = Unit
    }

    private companion object { const val SCOPE = "qa-scope" }
}
