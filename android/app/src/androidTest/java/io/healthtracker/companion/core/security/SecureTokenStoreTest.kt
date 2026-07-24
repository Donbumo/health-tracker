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
}
