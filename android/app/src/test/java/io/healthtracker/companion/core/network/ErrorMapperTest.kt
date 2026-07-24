package io.healthtracker.companion.core.network

import io.healthtracker.companion.core.model.AppErrorCode
import io.healthtracker.companion.core.model.AppFailure
import java.io.IOException
import java.net.SocketTimeoutException
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
            AppErrorCode.SERVER_ERROR,
            AppErrorCode.RATE_LIMITED,
        ).forEach { code ->
            assertEquals(
                RefreshFailureDisposition.PRESERVE_LOCAL_SESSION,
                refreshFailureDisposition(AppFailure(code, "QA temporal", true)),
            )
        }
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
