package io.healthtracker.companion.core.security

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SecureTokenStoreTest {
    @Test fun refreshTokenIsEncryptedAndCanBeCleared() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val store = SecureTokenStore(context)
        store.clear()
        store.setTokens("access-qa", "refresh-secret-qa")
        assertEquals("access-qa", store.accessToken())
        assertEquals("refresh-secret-qa", store.refreshToken())
        val raw = context.getSharedPreferences("secure_session_v1", android.content.Context.MODE_PRIVATE).all.values.joinToString()
        assertFalse(raw.contains("refresh-secret-qa"))
        store.clear()
        assertNull(store.refreshToken())
    }

    @Test fun processDeathRetainsRefreshOnlyForItsBoundServer() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        SecureTokenStore(context).also {
            it.clear()
            it.setTokens("access-qa", "refresh-secret-qa", "https://nas-a.example")
        }
        val restored = SecureTokenStore(context)
        assertEquals("refresh-secret-qa", restored.refreshToken("https://nas-a.example"))
        assertNull(restored.refreshToken("https://nas-b.example"))
        assertNull(restored.accessToken("https://nas-a.example"))
        restored.clear()
    }

    @Test fun legacyRefreshIsBoundOnceToPersistedServerDuringUpgrade() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val store = SecureTokenStore(context).also { it.clear(); it.setTokens("access-qa", "refresh-qa") }
        assertNull(store.refreshToken("https://nas-a.example"))
        store.bindLegacyServerIfMissing("https://nas-a.example")
        assertEquals("refresh-qa", store.refreshToken("https://nas-a.example"))
        store.bindLegacyServerIfMissing("https://nas-b.example")
        assertNull(store.refreshToken("https://nas-b.example"))
        store.clear()
    }
}
