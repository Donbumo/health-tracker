package io.healthtracker.companion.core.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class ActivityExportMessageTest {
    @Test fun exportLimitMessageRemainsValidUtf8Spanish() {
        assertEquals("La exportación supera el límite local.", ACTIVITY_EXPORT_TOO_LARGE_MESSAGE)
        assertFalse(ACTIVITY_EXPORT_TOO_LARGE_MESSAGE.contains("Ã"))
    }
}
