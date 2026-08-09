package io.healthtracker.companion.core.network

import java.security.MessageDigest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

object CanonicalJson {
    private val json = Json { explicitNulls = true }

    fun sha256(element: JsonElement, excludingTopLevelKey: String? = null): String {
        val source = if (excludingTopLevelKey != null && element is JsonObject) {
            JsonObject(element.filterKeys { it != excludingTopLevelKey })
        } else element
        val bytes = json.encodeToString(JsonElement.serializer(), sorted(source)).toByteArray(Charsets.UTF_8)
        return MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    }

    fun accountScope(serverUrl: String, userPublicId: String): String {
        val bytes = "$serverUrl\u0000$userPublicId".toByteArray(Charsets.UTF_8)
        return MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    }

    fun serverIdentity(serverUrl: String): String {
        val normalized = serverUrl.trim().trimEnd('/').lowercase()
        return MessageDigest.getInstance("SHA-256").digest(normalized.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
    }

    private fun sorted(element: JsonElement): JsonElement = when (element) {
        is JsonObject -> JsonObject(element.entries.sortedBy { it.key }.associate { it.key to sorted(it.value) })
        is JsonArray -> JsonArray(element.map(::sorted))
        else -> element
    }
}
