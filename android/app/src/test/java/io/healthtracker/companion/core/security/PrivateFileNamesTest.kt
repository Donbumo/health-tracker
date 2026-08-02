package io.healthtracker.companion.core.security

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class PrivateFileNamesTest {
    @Test fun remoteIdentifiersNeverBecomePathSegments() {
        val malicious = "../../secure_session_v1\\..\\token"
        val value = PrivateFileNames.opaque("medical-document", malicious, "pdf")

        assertTrue(value.matches(Regex("medical-document-[0-9a-f]{32}\\.pdf")))
        assertFalse(value.contains(malicious))
        assertFalse(value.contains("/"))
        assertFalse(value.contains("\\"))
        assertFalse(value.contains(".."))
    }

    @Test fun namesAreDeterministicAndPurposeSeparated() {
        val first = PrivateFileNames.opaque("activity-route", "qa-remote-id", "json")
        assertEquals(first, PrivateFileNames.opaque("activity-route", "qa-remote-id", "json"))
        assertNotEquals(first, PrivateFileNames.opaque("activity-series", "qa-remote-id", "json"))
    }

    @Test fun callerControlledLabelsAndExtensionsAreRejected() {
        assertThrows(IllegalArgumentException::class.java) {
            PrivateFileNames.opaque("../escape", "qa", "json")
        }
        assertThrows(IllegalArgumentException::class.java) {
            PrivateFileNames.opaque("safe", "qa", "../db")
        }
    }
}
