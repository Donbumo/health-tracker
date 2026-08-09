package io.healthtracker.companion.core.activity

import io.healthtracker.companion.core.database.ActivityDuplicateCandidateEntity
import io.healthtracker.companion.core.database.ActivityEntity
import io.healthtracker.companion.core.database.ActivityImportEntity
import io.healthtracker.companion.core.database.ActivityLapEntity
import io.healthtracker.companion.core.database.ActivityOperationEntity
import io.healthtracker.companion.core.database.ActivityRouteEntity
import io.healthtracker.companion.core.database.ActivitySeriesMetadataEntity
import io.healthtracker.companion.core.database.PlanActivityLinkEntity
import io.healthtracker.companion.core.database.PlanActualComparisonEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ActivityOfflineStateTest {
    private val scope = "qa-account-scope"
    private val server = "qa-server-identity"
    private val activityId = "a2000000-0000-4000-8000-000000000100"

    @Test fun pendingImportRetainsSafPermissionHashAndProcessDeathState() {
        val pending = importRow()
        val operation = ActivityOperationEntity(
            scope, server, "operation-qa", pending.publicId, "upload_inspect", "activity-upload-${pending.publicId}",
            "{\"route_policy\":\"redact\"}", "payload-hash-qa", "pending", 0, 0,
            "2026-07-31T00:00:00Z", null,
        )

        assertEquals("content://qa.invalid/document/fictional.fit", pending.sourceUri)
        assertTrue(pending.uriPermissionPersisted)
        assertEquals("fictional.partial", pending.partialFileName)
        assertEquals(64, pending.sha256.length)
        assertEquals(pending.publicId, operation.importPublicId)
        assertEquals("pending", operation.status)

        val resumed = pending.copy(state = "retry", errorCode = "network_unavailable")
        assertEquals(pending.publicId, resumed.publicId)
        assertEquals(pending.partialFileName, resumed.partialFileName)
        assertEquals(pending.sha256, resumed.sha256)
        assertEquals(scope, resumed.accountScope)
        assertEquals(server, resumed.serverIdentity)
    }

    @Test fun cancelAndLostPermissionStatesCannotPretendTheSourceStillExists() {
        val pending = importRow()
        val cancelled = pending.copy(state = "cancelled", partialFileName = null)
        val lost = pending.copy(state = "source_lost", partialFileName = null, errorCode = "source_lost")

        assertNull(cancelled.partialFileName)
        assertNull(lost.partialFileName)
        assertEquals("source_lost", lost.errorCode)
        assertNotEquals("pending_upload", cancelled.state)
    }

    @Test fun accountAndServerIdentityPartitionImportsAndWork() {
        val base = importRow()
        val anotherServer = base.copy(serverIdentity = "qa-second-server")
        val anotherAccount = base.copy(accountScope = "qa-second-account")

        assertNotEquals(base.serverIdentity, anotherServer.serverIdentity)
        assertNotEquals(base.accountScope, anotherAccount.accountScope)
        assertNotEquals(
            ActivityImportScheduler.workName(scope, server, base.publicId),
            ActivityImportScheduler.workName(scope, anotherServer.serverIdentity, base.publicId),
        )
        assertNotEquals(ActivityImportScheduler.scopeTag(scope), ActivityImportScheduler.scopeTag(anotherAccount.accountScope))
    }

    @Test fun cachedActivityGraphKeepsEveryChildInsideTheSameOwnerPartition() {
        val activity = ActivityEntity(scope, server, activityId, "cycling", null, "Actividad ficticia QA",
            "2026-07-31T10:00:00Z", "UTC", 3600, 3600, "20000", null, "120", "150", "fit",
            "Dispositivo QA", null, "imported", 1, "{}", "synced", "2026-07-31T11:00:00Z")
        val lap = ActivityLapEntity(scope, server, activityId, 0, activity.startedAt, "3600", "20000", "{}")
        val series = ActivitySeriesMetadataEntity(scope, server, activityId, 120, "[\"power\"]", activity.startedAt,
            "2026-07-31T11:00:00Z", "series-qa.json", "2026-07-31T11:00:00Z")
        val route = ActivityRouteEntity(scope, server, activityId, "available", "redact", 20, true,
            "route-qa.json", null, "2026-07-31T11:00:00Z")
        val duplicate = ActivityDuplicateCandidateEntity(scope, server, "duplicate-qa", activityId, "candidate-qa",
            "probable_duplicate", "{}", "pending", "2026-07-31T11:00:00Z")
        val link = PlanActivityLinkEntity(scope, server, "link-qa", activityId, "plan-qa", "strong",
            "strong_auto_link", "{}", "2026-07-31T11:00:00Z")
        val comparison = PlanActualComparisonEntity(scope, server, "comparison-qa", activityId, link.publicId,
            "comparable", "{\"duration\":{}}", "2026-07-31T11:00:00Z")

        listOf(lap.accountScope, series.accountScope, route.accountScope, duplicate.accountScope,
            link.accountScope, comparison.accountScope).forEach { assertEquals(activity.accountScope, it) }
        listOf(lap.serverIdentity, series.serverIdentity, route.serverIdentity, duplicate.serverIdentity,
            link.serverIdentity, comparison.serverIdentity).forEach { assertEquals(activity.serverIdentity, it) }
        listOf(lap.activityPublicId, series.activityPublicId, route.activityPublicId, duplicate.activityPublicId,
            link.activityPublicId, comparison.activityPublicId).forEach { assertEquals(activity.publicId, it) }
        assertEquals(120L, series.sampleCount)
        assertTrue(route.hasElevation)
        assertEquals("strong_auto_link", link.state)
        assertEquals("comparable", comparison.status)
    }

    @Test fun privateRouteDeletionDropsOnlyTheCachedRouteRepresentation() {
        val route = ActivityRouteEntity(scope, server, activityId, "available", "redact", 20, false,
            "route-qa.json", null, "2026-07-31T11:00:00Z")
        val removed = route.copy(visibilityState = "removed", privacyPolicy = "drop", pointCount = 0,
            cachedRouteFileName = null, deletedAt = "2026-07-31T12:00:00Z")

        assertEquals(activityId, removed.activityPublicId)
        assertEquals(0L, removed.pointCount)
        assertNull(removed.cachedRouteFileName)
        assertEquals("removed", removed.visibilityState)
        assertFalse(removed.hasElevation)
    }

    @Test fun weakPlanCandidateRequiresAnExplicitDecisionWhileStrongLinkIsIdentifiable() {
        val suggested = PlanActivityLinkEntity(scope, server, "link-suggested", activityId, "plan-qa", "suggested",
            "pending", "{\"time_delta_seconds\":600}", "2026-07-31T11:00:00Z")
        val confirmed = suggested.copy(linkType = "manual", state = "user_confirmed")
        val rejected = suggested.copy(state = "user_rejected")
        val strong = suggested.copy(linkType = "strong", state = "strong_auto_link")

        assertEquals("pending", suggested.state)
        assertEquals("user_confirmed", confirmed.state)
        assertEquals("user_rejected", rejected.state)
        assertEquals("strong_auto_link", strong.state)
    }

    private fun importRow() = ActivityImportEntity(
        scope, server, "import-qa", null, "fictional.fit", "fit", "application/octet-stream", 1024,
        "0123456789abcdef".repeat(4), "content://qa.invalid/document/fictional.fit", true, "fictional.partial",
        "redact", 250, 250, "pending_upload", "[]", null,
        "2026-07-31T00:00:00Z", "2026-07-31T00:00:00Z",
    )
}
