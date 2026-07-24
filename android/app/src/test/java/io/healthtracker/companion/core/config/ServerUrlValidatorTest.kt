package io.healthtracker.companion.core.config

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ServerUrlValidatorTest {
    @Test fun httpsIsNormalized() {
        val result = ServerUrlValidator.validate(" https://Tracker.Example/ ", false)
        assertTrue(result.valid)
        assertEquals("https://tracker.example", result.normalizedUrl)
    }

    @Test fun arbitrarySchemesCredentialsAndPathsAreRejected() {
        assertFalse(ServerUrlValidator.validate("javascript:alert(1)", false).valid)
        assertFalse(ServerUrlValidator.validate("file:///tmp/app", false).valid)
        assertFalse(ServerUrlValidator.validate("https://user:pass@example.test", false).valid)
        assertFalse(ServerUrlValidator.validate("https://example.test/private", false).valid)
    }

    @Test fun localHostPolicyRecognizesOnlyExplicitLocalRanges() {
        assertTrue(ServerUrlValidator.isLocalDevelopmentHost("localhost"))
        assertTrue(ServerUrlValidator.isLocalDevelopmentHost("10.0.2.2"))
        assertTrue(ServerUrlValidator.isLocalDevelopmentHost("192.168.1.20"))
        assertFalse(ServerUrlValidator.isLocalDevelopmentHost("8.8.8.8"))
    }
}
