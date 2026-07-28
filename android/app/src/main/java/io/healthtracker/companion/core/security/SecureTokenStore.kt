package io.healthtracker.companion.core.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.core.content.edit
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class SecureTokenStore(context: Context) {
    private val preferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    @Volatile
    private var accessToken: String? = null

    fun accessToken(serverIdentity: String? = null): String? =
        accessToken.takeIf { identityMatches(serverIdentity) }

    fun setTokens(access: String, refresh: String, serverIdentity: String? = null) {
        accessToken = access
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, secretKey())
        val encrypted = cipher.doFinal(refresh.toByteArray(Charsets.UTF_8))
        preferences.edit {
            putString(KEY_REFRESH_CIPHER, Base64.encodeToString(encrypted, Base64.NO_WRAP))
            putString(KEY_REFRESH_IV, Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            if (serverIdentity == null) remove(KEY_SERVER_IDENTITY)
            else putString(KEY_SERVER_IDENTITY, serverIdentity)
        }
    }

    fun refreshToken(serverIdentity: String? = null): String? {
        if (!identityMatches(serverIdentity)) return null
        val cipherText = preferences.getString(KEY_REFRESH_CIPHER, null) ?: return null
        val iv = preferences.getString(KEY_REFRESH_IV, null) ?: return null
        return runCatching {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(
                Cipher.DECRYPT_MODE,
                secretKey(),
                GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)),
            )
            cipher.doFinal(Base64.decode(cipherText, Base64.NO_WRAP)).toString(Charsets.UTF_8)
        }.getOrNull()
    }

    fun clear() {
        accessToken = null
        preferences.edit { clear() }
    }

    fun bindLegacyServerIfMissing(serverIdentity: String?) {
        if (serverIdentity == null || preferences.getString(KEY_SERVER_IDENTITY, null) != null) return
        if (preferences.contains(KEY_REFRESH_CIPHER)) {
            preferences.edit { putString(KEY_SERVER_IDENTITY, serverIdentity) }
        }
    }

    private fun identityMatches(expected: String?): Boolean {
        if (expected == null) return true
        val stored = preferences.getString(KEY_SERVER_IDENTITY, null)
        return stored == expected
    }

    private fun secretKey(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE).run {
            init(
                KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true)
                    .build(),
            )
            generateKey()
        }
    }

    private companion object {
        const val PREFS_NAME = "secure_session_v1"
        const val KEY_REFRESH_CIPHER = "refresh_cipher"
        const val KEY_REFRESH_IV = "refresh_iv"
        const val KEY_SERVER_IDENTITY = "server_identity"
        const val KEY_ALIAS = "health_tracker_refresh_v1"
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
    }
}
