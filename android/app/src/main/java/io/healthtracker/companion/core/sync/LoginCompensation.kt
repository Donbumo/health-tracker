package io.healthtracker.companion.core.sync

import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext

internal suspend fun <T> authenticatedLoginWithCompensation(
    remoteLogin: suspend () -> Unit,
    authenticatedWork: suspend () -> T,
    remoteLogout: suspend () -> Unit,
    localCleanup: suspend () -> Unit,
): T {
    var remoteSessionCreated = false
    try {
        remoteLogin()
        remoteSessionCreated = true
        return authenticatedWork()
    } catch (original: Exception) {
        if (!remoteSessionCreated) throw original
        withContext(NonCancellable) {
            try {
                remoteLogout()
            } catch (_: Exception) {
                // The authenticated failure remains authoritative.
            }
            try {
                localCleanup()
            } catch (cleanupFailure: Exception) {
                original.addSuppressed(cleanupFailure)
            }
        }
        throw original
    }
}
