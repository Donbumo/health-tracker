package io.healthtracker.companion.core.notifications

import java.time.Instant
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneId
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ReminderDomainTest {
    private val planner = ReminderPlanner()

    @Test fun dstGapMovesToNextValidInstantAndOverlapUsesEarlierOffsetOnce() {
        val newYork = ZoneId.of("America/New_York")
        val gap = planner.resolve(LocalDateTime.of(2026, 3, 8, 2, 30), newYork)
        assertTrue(gap.adjustedForDstGap)
        assertEquals("03:30", gap.instant.atZone(newYork).toLocalTime().toString())
        val overlap = planner.resolve(LocalDateTime.of(2026, 11, 1, 1, 30), newYork)
        assertFalse(overlap.adjustedForDstGap)
        assertEquals(newYork.rules.getValidOffsets(overlap.localDateTime).first(), overlap.instant.atZone(newYork).offset)
        val phoenix = planner.resolve(LocalDateTime.of(2026, 3, 8, 2, 30), ZoneId.of("America/Phoenix"))
        assertEquals("02:30", phoenix.instant.atZone(ZoneId.of("America/Phoenix")).toLocalTime().toString())
    }

    @Test fun repeatedHourAndTimezoneChangeKeepLogicalDedupeStable() {
        val dedupe = ReminderDeduplicator()
        val a = dedupe.key("scope", "rule", "2026-11-01T01:30", "log_weight", null)
        val b = dedupe.key("scope", "rule", "2026-11-01T01:30", "log_weight", null)
        assertEquals(a, b)
        assertNotEquals(a, dedupe.key("scope", "rule", "2026-11-02T01:30", "log_weight", null))
    }

    @Test fun quietHoursCooldownLimitsCompletionAndDedupeAreEnforced() {
        val rule = rule(quietStart = LocalTime.of(22, 0), quietEnd = LocalTime.of(7, 0))
        val now = Instant.parse("2026-07-31T05:00:00Z") // 23:00 previous day in Mexico City.
        val deferred = ReminderEvaluator().evaluate(rule, EvaluationContext(now, true, 0, 0, 0, null, false, false))
        assertTrue(deferred is ReminderDecision.Defer && deferred.reason == "quiet_hours")
        assertEquals("action_completed", (ReminderEvaluator().evaluate(rule.copy(quietStart = null, quietEnd = null),
            EvaluationContext(now, true, 0, 0, 0, null, true, false)) as ReminderDecision.Suppress).reason)
        assertEquals("duplicate", (ReminderEvaluator().evaluate(rule.copy(quietStart = null, quietEnd = null),
            EvaluationContext(now, true, 0, 0, 0, null, false, true)) as ReminderDecision.Suppress).reason)
        assertEquals("global_daily_limit", (ReminderEvaluator(2).evaluate(rule.copy(quietStart = null, quietEnd = null),
            EvaluationContext(now, true, 0, 0, 2, null, false, false)) as ReminderDecision.Suppress).reason)
    }

    @Test fun contextualPermissionNeverPromptsAtLoginOrRepeatsAfterDenial() {
        assertFalse(ReminderPermissionPolicy.shouldRequestOnActivation(36, false, null))
        assertTrue(ReminderPermissionPolicy.shouldRequestOnActivation(36, true, null))
        assertFalse(ReminderPermissionPolicy.shouldRequestOnActivation(36, true, ReminderPermissionSnapshot(true, false)))
        assertFalse(ReminderPermissionPolicy.shouldRequestOnActivation(32, true, null))
    }

    @Test fun notificationFactoryIsGenericPrivateAndWeeklySummaryRequiresGoalsAndData() {
        listOf("scheduled_workout_pending", "log_weight", "log_nutrition", "conflict_attention", "weekly_summary").forEach {
            val notification = ReminderNotificationFactory().create(it)
            assertTrue(notification.visibilityPrivate)
            assertFalse(notification.body.contains("kg"))
            assertFalse(notification.body.any(Char::isDigit))
            assertTrue(notification.channelId in NotificationChannels.ALL)
        }
        assertTrue(WeeklySummaryPolicy.shouldGenerate(true, true, true))
        assertFalse(WeeklySummaryPolicy.shouldGenerate(false, true, true))
        assertFalse(WeeklySummaryPolicy.shouldGenerate(true, false, true))
    }

    private fun rule(quietStart: LocalTime?, quietEnd: LocalTime?) = ReminderRuleSpec(
        "rule", "log_weight", LocalTime.of(18, 0), (1..7).toSet(), ZoneId.of("America/Mexico_City"),
        quietStart, quietEnd, ZoneId.of("America/Mexico_City"), 1, 60, true,
    )
}
