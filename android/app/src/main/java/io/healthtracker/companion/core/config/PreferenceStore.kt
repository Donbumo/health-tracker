package io.healthtracker.companion.core.config

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "companion_preferences_v1")

enum class ThemePreference { SYSTEM, LIGHT, DARK }
enum class UnitPreference { KG, LB }

data class AppPreferences(
    val serverUrl: String? = null,
    val allowLocalHttp: Boolean = false,
    val deviceId: String,
    val accountScope: String? = null,
    val offlineSessionEligible: Boolean = false,
    val theme: ThemePreference = ThemePreference.SYSTEM,
    val unit: UnitPreference = UnitPreference.KG,
    val lastSyncAt: String? = null,
)

class PreferenceStore(private val context: Context) {
    val values: Flow<AppPreferences> = context.dataStore.data.map { prefs ->
        AppPreferences(
            serverUrl = prefs[SERVER_URL],
            allowLocalHttp = prefs[ALLOW_LOCAL_HTTP] ?: false,
            deviceId = prefs[DEVICE_ID] ?: "",
            accountScope = prefs[ACCOUNT_SCOPE],
            // Existing Alpha installs predate this flag. A retained scoped session is
            // eligible until an explicit logout removes both the scope and the flag.
            offlineSessionEligible = prefs[OFFLINE_SESSION_ELIGIBLE] ?: (prefs[ACCOUNT_SCOPE] != null),
            theme = prefs[THEME]?.let { runCatching { ThemePreference.valueOf(it) }.getOrNull() }
                ?: ThemePreference.SYSTEM,
            unit = prefs[UNIT]?.let { runCatching { UnitPreference.valueOf(it) }.getOrNull() }
                ?: UnitPreference.KG,
            lastSyncAt = prefs[LAST_SYNC_AT],
        )
    }

    suspend fun ensureDeviceId(): String {
        val current = values.first().deviceId
        if (current.isNotBlank()) return current
        val generated = UUID.randomUUID().toString()
        context.dataStore.edit { it[DEVICE_ID] = generated }
        return generated
    }

    suspend fun configureServer(url: String, allowLocalHttp: Boolean) {
        context.dataStore.edit {
            it[SERVER_URL] = url
            it[ALLOW_LOCAL_HTTP] = allowLocalHttp
        }
    }

    suspend fun setAccountScope(scope: String?) {
        context.dataStore.edit {
            if (scope == null) it.remove(ACCOUNT_SCOPE) else it[ACCOUNT_SCOPE] = scope
        }
    }

    suspend fun setOfflineSessionEligible(eligible: Boolean) {
        context.dataStore.edit { it[OFFLINE_SESSION_ELIGIBLE] = eligible }
    }

    suspend fun setTheme(value: ThemePreference) {
        context.dataStore.edit { it[THEME] = value.name }
    }

    suspend fun setUnit(value: UnitPreference) {
        context.dataStore.edit { it[UNIT] = value.name }
    }

    suspend fun setLastSyncAt(value: String) {
        context.dataStore.edit { it[LAST_SYNC_AT] = value }
    }

    private companion object {
        val SERVER_URL = stringPreferencesKey("server_url")
        val ALLOW_LOCAL_HTTP = booleanPreferencesKey("allow_local_http")
        val DEVICE_ID = stringPreferencesKey("device_id")
        val ACCOUNT_SCOPE = stringPreferencesKey("account_scope")
        val OFFLINE_SESSION_ELIGIBLE = booleanPreferencesKey("offline_session_eligible")
        val THEME = stringPreferencesKey("theme")
        val UNIT = stringPreferencesKey("unit")
        val LAST_SYNC_AT = stringPreferencesKey("last_sync_at")
    }
}
