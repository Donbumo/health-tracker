package io.healthtracker.companion.core.security

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RedactionTest {
    @Test fun secretsAreRemovedFromDiagnostics() {
        val output = Redaction.sanitize("Authorization: Bearer-secret password=hunter2 refresh_token=rt1.secret")
        assertFalse(output.contains("hunter2"))
        assertFalse(output.contains("rt1.secret"))
        assertTrue(output.contains("[REDACTED]"))
    }
}
