package io.healthtracker.companion.core.network

import io.healthtracker.companion.core.model.ApiErrorBody
import io.healthtracker.companion.core.model.AppErrorCode
import io.healthtracker.companion.core.model.AppFailure
import java.io.IOException
import java.net.SocketTimeoutException
import java.net.ConnectException
import java.net.UnknownHostException
import javax.net.ssl.SSLException

object ErrorMapper {
    fun http(status: Int, error: ApiErrorBody?, retryAfter: Long?): AppFailure {
        val serverCode = error?.code.orEmpty()
        val code = when {
            status == 429 -> AppErrorCode.RATE_LIMITED
            status >= 500 -> AppErrorCode.SERVER_ERROR
            serverCode in setOf("token_expired", "invalid_token", "invalid_refresh_token", "refresh_token_reused") -> AppErrorCode.REFRESH_FAILED
            serverCode == "session_revoked" -> AppErrorCode.DEVICE_REVOKED
            serverCode in setOf("companion_protocol_unsupported", "workout_schema_unsupported", "result_schema_unsupported", "capability_mismatch") -> AppErrorCode.SERVER_INCOMPATIBLE
            serverCode == "package_hash_mismatch" -> AppErrorCode.PACKAGE_HASH_MISMATCH
            serverCode in setOf("revision_conflict", "delivery_state_conflict", "progress_sequence_conflict") -> AppErrorCode.REVISION_CONFLICT
            serverCode in setOf("event_conflict", "progress_event_conflict", "idempotency_conflict") -> AppErrorCode.SUBMISSION_CONFLICT
            status == 401 -> AppErrorCode.UNAUTHORIZED
            status in 400..499 -> AppErrorCode.VALIDATION_ERROR
            else -> AppErrorCode.UNKNOWN
        }
        val message = when (code) {
            AppErrorCode.RATE_LIMITED -> "Demasiados intentos. Espera y vuelve a intentar."
            AppErrorCode.SERVER_ERROR -> "El servidor tuvo un problema temporal."
            AppErrorCode.REFRESH_FAILED -> "La sesión venció. Inicia sesión nuevamente."
            AppErrorCode.DEVICE_REVOKED -> "Este dispositivo fue revocado desde el servidor."
            AppErrorCode.SERVER_INCOMPATIBLE -> "El servidor no ofrece una versión compatible."
            AppErrorCode.PACKAGE_HASH_MISMATCH -> "El entrenamiento descargado no pasó la verificación de integridad."
            AppErrorCode.REVISION_CONFLICT -> "El entrenamiento cambió en el servidor. Revisa el conflicto antes de continuar."
            AppErrorCode.SUBMISSION_CONFLICT -> "El servidor detectó contenido distinto para la misma operación."
            AppErrorCode.UNAUTHORIZED -> "No fue posible autenticar la solicitud."
            AppErrorCode.VALIDATION_ERROR -> error?.message ?: "Revisa los datos e inténtalo de nuevo."
            else -> "No fue posible completar la operación."
        }
        return AppFailure(
            code = code,
            userMessage = message,
            retryable = code in setOf(AppErrorCode.RATE_LIMITED, AppErrorCode.SERVER_ERROR),
            retryAfterSeconds = retryAfter,
            requestId = error?.requestId,
            serverCode = error?.code,
        )
    }

    fun network(error: IOException): AppFailure = when (error) {
        is SocketTimeoutException -> AppFailure(AppErrorCode.TIMEOUT, "El servidor tardó demasiado en responder.", true)
        is UnknownHostException -> AppFailure(AppErrorCode.NETWORK_UNAVAILABLE, "No se encontró el servidor configurado. Revisa la red y la URL.", true)
        is ConnectException -> AppFailure(AppErrorCode.NETWORK_UNAVAILABLE, "El servidor rechazó o no aceptó la conexión. Tus cambios siguen guardados.", true)
        is SSLException -> AppFailure(AppErrorCode.TLS_ERROR, "No se pudo validar la conexión segura con el servidor.", false)
        else -> AppFailure(AppErrorCode.NETWORK_UNAVAILABLE, "No hay conexión con el servidor. Tus cambios siguen guardados.", true)
    }
}
