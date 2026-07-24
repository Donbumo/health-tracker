package io.healthtracker.companion.core.sync

import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class LoginCompensationTest {
    @Test
    fun remoteLoginFailureDoesNotLogoutOrCleanAuthenticatedState() = runTest {
        val events = mutableListOf<String>()
        val original = IllegalStateException("qa_login_failed")

        val caught = runCatching {
            authenticatedLoginWithCompensation(
                remoteLogin = { events += "login"; throw original },
                authenticatedWork = { events += "bootstrap" },
                remoteLogout = { events += "logout" },
                localCleanup = { events += "cleanup" },
            )
        }.exceptionOrNull()

        assertSame(original, caught)
        assertEquals(listOf("login"), events)
    }

    @Test
    fun bootstrapFailureLogsOutBeforeTokenCleanupAndRethrowsOriginal() = runTest {
        val events = mutableListOf<String>()
        val original = IllegalArgumentException("qa_bootstrap_failed")
        var tokensAvailable = false

        val caught = runCatching {
            authenticatedLoginWithCompensation(
                remoteLogin = { tokensAvailable = true; events += "login" },
                authenticatedWork = { events += "bootstrap"; throw original },
                remoteLogout = { assertTrue(tokensAvailable); events += "logout" },
                localCleanup = { tokensAvailable = false; events += "cleanup" },
            )
        }.exceptionOrNull()

        assertSame(original, caught)
        assertEquals(listOf("login", "bootstrap", "logout", "cleanup"), events)
    }

    @Test
    fun successfulLoginBootstrapAndNegotiationDoNotCompensate() = runTest {
        val events = mutableListOf<String>()

        val outcome = authenticatedLoginWithCompensation(
            remoteLogin = { events += "login" },
            authenticatedWork = {
                events += "bootstrap"
                events += "negotiate"
                "qa_success"
            },
            remoteLogout = { events += "logout" },
            localCleanup = { events += "cleanup" },
        )

        assertEquals("qa_success", outcome)
        assertEquals(listOf("login", "bootstrap", "negotiate"), events)
    }

    @Test
    fun compensatingLogoutFailureKeepsOriginalAndStillCleansLocally() = runTest {
        val events = mutableListOf<String>()
        val original = IllegalArgumentException("qa_bootstrap_failed")
        val secondary = IllegalStateException("qa_logout_failed")

        val caught = runCatching {
            authenticatedLoginWithCompensation(
                remoteLogin = { events += "login" },
                authenticatedWork = { events += "bootstrap"; throw original },
                remoteLogout = { events += "logout"; throw secondary },
                localCleanup = { events += "cleanup" },
            )
        }.exceptionOrNull()

        assertSame(original, caught)
        assertEquals(listOf("login", "bootstrap", "logout", "cleanup"), events)
    }
}
