package io.healthtracker.companion.ui

import io.healthtracker.companion.core.model.AppErrorCode
import io.healthtracker.companion.core.model.AppFailure
import io.healthtracker.companion.core.model.AuthState

internal data class AuthRecoveryDecision(
    val state: AuthState,
    val message: String,
    val clearLocalSession: Boolean = false,
)

internal fun classifyRestoreFailure(error: Throwable): AuthRecoveryDecision {
    val failure = error as? AppFailure
        ?: return AuthRecoveryDecision(AuthState.SIGNED_OUT, "No fue posible restaurar la sesión.")
    return when (failure.code) {
        AppErrorCode.NETWORK_UNAVAILABLE,
        AppErrorCode.TIMEOUT,
        AppErrorCode.SERVER_ERROR,
        AppErrorCode.RATE_LIMITED -> AuthRecoveryDecision(
            AuthState.AUTHENTICATED,
            "Modo offline: puedes continuar con los entrenamientos ya descargados.",
        )
        AppErrorCode.DEVICE_REVOKED -> AuthRecoveryDecision(
            AuthState.DEVICE_REVOKED,
            "Este dispositivo fue revocado desde el servidor.",
            clearLocalSession = true,
        )
        AppErrorCode.SERVER_INCOMPATIBLE,
        AppErrorCode.SCHEMA_INCOMPATIBLE -> AuthRecoveryDecision(
            AuthState.SERVER_INCOMPATIBLE,
            failure.userMessage,
        )
        AppErrorCode.REFRESH_FAILED,
        AppErrorCode.UNAUTHORIZED -> AuthRecoveryDecision(
            AuthState.TOKEN_EXPIRED,
            "La sesión venció. Inicia sesión nuevamente.",
            clearLocalSession = true,
        )
        else -> AuthRecoveryDecision(AuthState.SIGNED_OUT, failure.userMessage)
    }
}
