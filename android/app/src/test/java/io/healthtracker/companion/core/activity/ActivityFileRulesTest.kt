package io.healthtracker.companion.core.activity

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ActivityFileRulesTest {
    @Test fun acceptsOnlyExplicitActivityExtensions() {
        assertEquals("fit", ActivityFileRules.formatFor("fictional-ride.FIT"))
        assertEquals("gpx", ActivityFileRules.formatFor("fictional-route.gpx"))
        assertEquals("tcx", ActivityFileRules.formatFor("fictional-workout.tcx"))
        assertNull(ActivityFileRules.formatFor("route.gpx.html"))
        assertNull(ActivityFileRules.formatFor("activity.zip"))
        assertNull(ActivityFileRules.formatFor("activity"))
    }

    @Test fun shortHashNeverExposesTheCompleteDigest() {
        val digest = "0123456789abcdef".repeat(4)
        assertEquals("0123456789ab", ActivityFileRules.shortHash(digest))
    }

    @Test fun workNameIsUniquePerAccountServerAndImport() {
        val first = ActivityImportScheduler.workName("scope-a", "server-a", "import-a")
        assertEquals(first, ActivityImportScheduler.workName("scope-a", "server-a", "import-a"))
        assertNotEquals(first, ActivityImportScheduler.workName("scope-a", "server-b", "import-a"))
        assertNotEquals(first, ActivityImportScheduler.workName("scope-b", "server-a", "import-a"))
        assertNotEquals(first, ActivityImportScheduler.workName("scope-a", "server-a", "import-b"))
    }
}
