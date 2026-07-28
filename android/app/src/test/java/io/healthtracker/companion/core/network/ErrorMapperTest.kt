package io.healthtracker.companion.core.network

import io.healthtracker.companion.core.model.AppErrorCode
import io.healthtracker.companion.core.model.AppFailure
import java.io.IOException
import java.net.SocketTimeoutException
import java.net.ConnectException
import java.net.UnknownHostException
import javax.net.ssl.SSLHandshakeException
import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ErrorMapperTest {
    @Test fun timeoutAndUnavailableServerRemainRetryableNotConflicts() {
        val timeout = ErrorMapper.network(SocketTimeoutException("qa-timeout"))
        val unavailable = ErrorMapper.network(IOException("qa-offline"))

        assertEquals(AppErrorCode.TIMEOUT, timeout.code)
        assertEquals(AppErrorCode.NETWORK_UNAVAILABLE, unavailable.code)
        assertTrue(timeout.retryable)
        assertTrue(unavailable.retryable)
    }

    @Test fun temporaryRefreshFailuresPreserveEncryptedOfflineSession() {
        listOf(
            AppErrorCode.NETWORK_UNAVAILABLE,
            AppErrorCode.TIMEOUT,
            AppErrorCode.TLS_ERROR,
            AppErrorCode.SERVER_ERROR,
            AppErrorCode.RATE_LIMITED,
        ).forEach { code ->
            assertEquals(
                RefreshFailureDisposition.PRESERVE_LOCAL_SESSION,
                refreshFailureDisposition(AppFailure(code, "QA temporal", true)),
            )
        }
    }

    @Test fun dnsRefusalAndTlsUseSanitizedStableCodes() {
        val dns = ErrorMapper.network(UnknownHostException("internal.qa.invalid"))
        val refused = ErrorMapper.network(ConnectException("Connection refused: secret-host"))
        val tls = ErrorMapper.network(SSLHandshakeException("certificate details"))

        assertEquals(AppErrorCode.NETWORK_UNAVAILABLE, dns.code)
        assertEquals(AppErrorCode.NETWORK_UNAVAILABLE, refused.code)
        assertEquals(AppErrorCode.TLS_ERROR, tls.code)
        assertFalse(dns.userMessage.contains("internal.qa.invalid"))
        assertFalse(refused.userMessage.contains("secret-host"))
        assertFalse(tls.userMessage.contains("certificate details"))
    }

    @Test fun expectedHttpFailuresHaveStableNonRawClassification() {
        assertEquals(AppErrorCode.UNAUTHORIZED, ErrorMapper.http(401, null, null).code)
        listOf(403, 404).forEach { assertEquals(AppErrorCode.VALIDATION_ERROR, ErrorMapper.http(it, null, null).code) }
        assertEquals(AppErrorCode.VALIDATION_ERROR, ErrorMapper.http(409, null, null).code)
        assertEquals(AppErrorCode.RATE_LIMITED, ErrorMapper.http(429, null, 3).code)
        listOf(500, 502, 503, 504).forEach { assertEquals(AppErrorCode.SERVER_ERROR, ErrorMapper.http(it, null, null).code) }
    }

    @Test fun definitiveRefreshFailureOrRevocationClearsSession() {
        listOf(AppErrorCode.REFRESH_FAILED, AppErrorCode.UNAUTHORIZED, AppErrorCode.DEVICE_REVOKED).forEach { code ->
            assertEquals(
                RefreshFailureDisposition.CLEAR_LOCAL_SESSION,
                refreshFailureDisposition(AppFailure(code, "QA definitiva", false)),
            )
        }
    }
}
