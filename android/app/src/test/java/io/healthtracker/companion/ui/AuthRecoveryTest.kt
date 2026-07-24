package io.healthtracker.companion.ui

import io.healthtracker.companion.core.model.AppErrorCode
import io.healthtracker.companion.core.model.AppFailure
import io.healthtracker.companion.core.model.AuthState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AuthRecoveryTest {
    @Test fun temporaryFailuresAllowCachedOfflineResume() {
        listOf(
            AppErrorCode.NETWORK_UNAVAILABLE,
            AppErrorCode.TIMEOUT,
            AppErrorCode.SERVER_ERROR,
            AppErrorCode.RATE_LIMITED,
        ).forEach { code ->
            val decision = classifyRestoreFailure(AppFailure(code, "QA temporal", true))
            assertEquals(AuthState.AUTHENTICATED, decision.state)
            assertFalse(decision.clearLocalSession)
        }
    }

    @Test fun revokedExpiredAndIncompatibleSessionsRemainBlocked() {
        val revoked = classifyRestoreFailure(AppFailure(AppErrorCode.DEVICE_REVOKED, "QA revoked", false))
        assertEquals(AuthState.DEVICE_REVOKED, revoked.state)
        assertTrue(revoked.clearLocalSession)
        val expired = classifyRestoreFailure(AppFailure(AppErrorCode.REFRESH_FAILED, "QA expired", false))
        assertEquals(AuthState.TOKEN_EXPIRED, expired.state)
        assertTrue(expired.clearLocalSession)
        assertEquals(
            AuthState.SERVER_INCOMPATIBLE,
            classifyRestoreFailure(AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "QA schema", false)).state,
        )
    }
}
