package io.healthtracker.companion.core.network

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.healthtracker.companion.core.config.PreferenceStore
import io.healthtracker.companion.core.model.DeviceRegistration
import io.healthtracker.companion.core.model.LoginRequest
import io.healthtracker.companion.core.model.AppErrorCode
import io.healthtracker.companion.core.model.AppFailure
import io.healthtracker.companion.core.security.SecureTokenStore
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ApiClientMockWebServerTest {
    private lateinit var server: MockWebServer

    @Before fun start() { server = MockWebServer().also { it.start() } }
    @After fun stop() { server.shutdown() }

    @Test fun loginUsesJsonAndNeverCookieFallback() = runBlocking {
        server.enqueue(MockResponse().setHeader("Content-Type", "application/json").setBody(tokenEnvelope("access-one", "refresh-one")))
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val preferences = PreferenceStore(context)
        val tokenStore = SecureTokenStore(context).also { it.clear() }
        val client = ApiClient(preferences, tokenStore)
        client.login(
            server.url("/").toString().trimEnd('/'),
            LoginRequest("qa@example.test", "qa-password", DeviceRegistration("11111111-1111-4111-8111-111111111111", "QA Android", appVersion = "qa", osVersion = "qa")),
        )
        val request = server.takeRequest()
        assertEquals("/api/v1/auth/login", request.path)
        assertEquals("POST", request.method)
        assertTrue(request.getHeader("Cookie") == null)
        assertTrue(request.body.readUtf8().contains("qa@example.test"))
        tokenStore.clear()
    }

    @Test fun configuredBasePathIsPreservedForApiRequests() = runBlocking {
        server.enqueue(MockResponse().setHeader("Content-Type", "application/json").setBody(
            """{"data":{"status":"ok","app":"health-tracker"},"meta":{"api_version":"1","request_id":"qa"}}""",
        ))
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val client = ApiClient(PreferenceStore(context), SecureTokenStore(context).also { it.clear() })

        client.health(server.url("/tracker/base").toString().trimEnd('/'))

        assertEquals("/tracker/base/api/v1/health", server.takeRequest().path)
    }

    @Test fun tokenRefreshIsRotatedAndOriginalRequestIsRetriedOnce() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val preferences = PreferenceStore(context)
        preferences.configureServer(server.url("/").toString().trimEnd('/'), true)
        val tokenStore = SecureTokenStore(context).also { it.clear(); it.setTokens("expired", "refresh-old") }
        val client = ApiClient(preferences, tokenStore)
        server.enqueue(MockResponse().setResponseCode(401).setHeader("Content-Type", "application/json").setBody(errorEnvelope("token_expired")))
        server.enqueue(MockResponse().setHeader("Content-Type", "application/json").setBody(tokenEnvelope("access-new", "refresh-new")))
        server.enqueue(MockResponse().setHeader("Content-Type", "application/json").setBody(
            """{"data":{"id":"11111111-1111-4111-8111-111111111111","email":"qa@example.test","role":"user","timezone":"UTC","created_at":"2026-07-17T00:00:00Z","capabilities":{}},"meta":{"api_version":"1","request_id":"qa"}}""",
        ))
        assertEquals("qa@example.test", client.me().email)
        assertEquals("refresh-new", tokenStore.refreshToken())
        assertEquals("/api/v1/me", server.takeRequest().path)
        assertEquals("/api/v1/auth/refresh", server.takeRequest().path)
        assertEquals("/api/v1/me", server.takeRequest().path)
        tokenStore.clear()
    }

    @Test fun revokedDeviceDoesNotAttemptRefreshLoop() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val preferences = PreferenceStore(context)
        preferences.configureServer(server.url("/").toString().trimEnd('/'), true)
        val tokenStore = SecureTokenStore(context).also { it.clear(); it.setTokens("revoked", "refresh-unused") }
        val client = ApiClient(preferences, tokenStore)
        server.enqueue(MockResponse().setResponseCode(401).setHeader("Content-Type", "application/json").setBody(errorEnvelope("session_revoked")))

        val failure = runCatching { client.me() }.exceptionOrNull() as AppFailure

        assertEquals(AppErrorCode.DEVICE_REVOKED, failure.code)
        assertEquals(1, server.requestCount)
        assertTrue(tokenStore.refreshToken() == null)
    }

    @Test fun temporaryRefreshFailureKeepsEncryptedSessionForOfflineUse() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val preferences = PreferenceStore(context)
        preferences.configureServer(server.url("/").toString().trimEnd('/'), true)
        SecureTokenStore(context).also { it.clear(); it.setTokens("qa-expired", "qa-refresh-retained") }
        val afterProcessDeath = SecureTokenStore(context)
        val client = ApiClient(preferences, afterProcessDeath)
        server.enqueue(
            MockResponse().setResponseCode(503).setHeader("Content-Type", "application/json")
                .setBody(errorEnvelope("temporary_unavailable")),
        )

        val failure = runCatching { client.restoreSession() }.exceptionOrNull() as AppFailure

        assertEquals(AppErrorCode.SERVER_ERROR, failure.code)
        assertEquals("qa-refresh-retained", afterProcessDeath.refreshToken())
        afterProcessDeath.clear()
    }

    @Test fun invalidRefreshTokenIsDefinitiveAndClearsEncryptedSession() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val preferences = PreferenceStore(context)
        preferences.configureServer(server.url("/").toString().trimEnd('/'), true)
        SecureTokenStore(context).also { it.clear(); it.setTokens("qa-expired", "qa-invalid-refresh") }
        val afterProcessDeath = SecureTokenStore(context)
        val client = ApiClient(preferences, afterProcessDeath)
        server.enqueue(
            MockResponse().setResponseCode(401).setHeader("Content-Type", "application/json")
                .setBody(errorEnvelope("invalid_refresh_token")),
        )

        val failure = runCatching { client.restoreSession() }.exceptionOrNull() as AppFailure

        assertEquals(AppErrorCode.REFRESH_FAILED, failure.code)
        assertTrue(afterProcessDeath.refreshToken() == null)
    }

    @Test fun retryAfterAndMalformedContractsMapToStableErrors() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val client = ApiClient(PreferenceStore(context), SecureTokenStore(context).also { it.clear() })
        val base = server.url("/").toString().trimEnd('/')
        server.enqueue(
            MockResponse().setResponseCode(429).setHeader("Retry-After", "120")
                .setHeader("Content-Type", "application/json").setBody(errorEnvelope("rate_limited")),
        )
        val limited = runCatching { client.health(base) }.exceptionOrNull() as AppFailure
        assertEquals(AppErrorCode.RATE_LIMITED, limited.code)
        assertEquals(120L, limited.retryAfterSeconds)

        server.enqueue(MockResponse().setHeader("Content-Type", "application/json").setBody("{not-json"))
        val malformed = runCatching { client.health(base) }.exceptionOrNull() as AppFailure
        assertEquals(AppErrorCode.SCHEMA_INCOMPATIBLE, malformed.code)
    }

    private fun tokenEnvelope(access: String, refresh: String) =
        """{"data":{"access_token":"$access","refresh_token":"$refresh","token_type":"Bearer","expires_in":900,"refresh_expires_at":"2026-08-17T00:00:00Z"},"meta":{"api_version":"1","request_id":"qa"}}"""

    private fun errorEnvelope(code: String) =
        """{"error":{"code":"$code","message":"QA","details":{}},"meta":{"api_version":"1","request_id":"qa"}}"""
}
