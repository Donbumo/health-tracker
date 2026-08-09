package io.healthtracker.companion.core.network

import io.healthtracker.companion.core.model.ApiEnvelope
import io.healthtracker.companion.core.model.BootstrapResponse
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BootstrapResponseTest {
    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        isLenient = false
        coerceInputValues = false
        encodeDefaults = true
    }

    @Test
    fun historicalWebSessionWithNullClientEventIdDecodesFromBootstrapEnvelope() {
        val fixture = requireNotNull(
            javaClass.getResource("/fixtures/sync_bootstrap_historical_session.json"),
        ).readText()

        val envelope = json.decodeFromString<ApiEnvelope<BootstrapResponse>>(fixture)
        val bootstrap = envelope.data

        assertEquals("1.0", bootstrap.schemaVersion)
        assertEquals("44444444-4444-4444-8444-444444444444", bootstrap.device.deviceId)
        assertEquals("55555555-5555-4555-8555-555555555555", bootstrap.device.sessionId)
        assertEquals(50, bootstrap.limits.pushOperations)
        assertEquals(200, bootstrap.limits.pullLimit)
        assertEquals(1_048_576, bootstrap.limits.jsonBytes)
        assertTrue(bootstrap.capabilities.getValue("companion_delivery"))
        assertEquals("1.0", bootstrap.schemas.getValue("completed_workout"))
        assertEquals("1.0", bootstrap.companion.versions.getValue("protocol"))
        assertTrue(bootstrap.companion.deliveries.isEmpty())
        assertNull(bootstrap.companion.profile)
        assertNull(bootstrap.completedWorkouts.single().clientEventId)
    }
}
