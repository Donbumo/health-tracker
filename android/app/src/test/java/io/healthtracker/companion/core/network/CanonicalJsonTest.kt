package io.healthtracker.companion.core.network

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class CanonicalJsonTest {
    @Test fun keyOrderDoesNotChangeHash() {
        val json = Json
        val first = json.parseToJsonElement("{\"b\":2,\"a\":{\"z\":1,\"x\":0}}")
        val second = json.parseToJsonElement("{\"a\":{\"x\":0,\"z\":1},\"b\":2}")
        assertEquals(CanonicalJson.sha256(first), CanonicalJson.sha256(second))
        assertEquals("dd509768f814cf066b8e7fe99aa527fd718e13d8718be4639ce07ae172590a59", CanonicalJson.sha256(first))
    }

    @Test fun packageHashFieldCanBeExcluded() {
        val json = Json
        val first = json.parseToJsonElement("{\"a\":1,\"package_hash\":\"old\"}")
        val second = json.parseToJsonElement("{\"package_hash\":\"new\",\"a\":1}")
        assertNotEquals(CanonicalJson.sha256(first), CanonicalJson.sha256(second))
        assertEquals(
            CanonicalJson.sha256(first, "package_hash"),
            CanonicalJson.sha256(second, "package_hash"),
        )
    }
}
