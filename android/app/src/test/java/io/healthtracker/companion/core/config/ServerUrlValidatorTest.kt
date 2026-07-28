package io.healthtracker.companion.core.config

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ServerUrlValidatorTest {
    @Test fun httpsIsNormalized() {
        val result = ServerUrlValidator.validate(" https://Tracker.Example/ ", false)
        assertTrue(result.error, result.valid)
        assertEquals("https://tracker.example", result.normalizedUrl)
    }

    @Test fun arbitrarySchemesCredentialsQueriesAndFragmentsAreRejected() {
        assertFalse(ServerUrlValidator.validate("javascript:alert(1)", false).valid)
        assertFalse(ServerUrlValidator.validate("file:///tmp/app", false).valid)
        assertFalse(ServerUrlValidator.validate("https://user:pass@example.test", false).valid)
        assertFalse(ServerUrlValidator.validate("https://example.test/?debug=true", false).valid)
        assertFalse(ServerUrlValidator.validate("https://example.test/#fragment", false).valid)
    }

    @Test fun portAndBasePathArePreservedWithOneCanonicalTrailingSlashPolicy() {
        val result = ServerUrlValidator.validate("https://Tracker.Example:8443/health/tracker///", false)
        assertTrue(result.valid)
        assertEquals("https://tracker.example:8443/health/tracker", result.normalizedUrl)
    }

    @Test fun relativeOrAmbiguousBasePathsAreRejected() {
        assertFalse(ServerUrlValidator.validate("https://example.test/a/../private", false).valid)
        assertFalse(ServerUrlValidator.validate("https://example.test/a//private", false).valid)
    }

    @Test fun localHostPolicyRecognizesOnlyExplicitLocalRanges() {
        assertTrue(ServerUrlValidator.isLocalDevelopmentHost("localhost"))
        assertTrue(ServerUrlValidator.isLocalDevelopmentHost("10.0.2.2"))
        assertTrue(ServerUrlValidator.isLocalDevelopmentHost("192.168.1.20"))
        assertFalse(ServerUrlValidator.isLocalDevelopmentHost("8.8.8.8"))
        assertFalse(ServerUrlValidator.isLocalDevelopmentHost("private.example.test"))
    }

    @Test fun localHttpRequiresDebugCapabilityAndExplicitConfirmation() {
        val confirmedDebug = ServerUrlValidator.validate("http://192.168.1.20:8000/base", true)
        assertTrue(confirmedDebug.error, confirmedDebug.valid)
        assertEquals("http://192.168.1.20:8000/base", confirmedDebug.normalizedUrl)
        assertFalse(ServerUrlValidator.validate("http://192.168.1.20:8000", false).valid)
        assertFalse(ServerUrlValidator.validate("http://203.0.113.20:8000", true).valid)
    }
}
