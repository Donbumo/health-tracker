import Foundation

public enum ErrorMapper {
    public static func http(status: Int, error: APIErrorBody?, retryAfter: Int64?) -> AppFailure {
        let serverCode = error?.code ?? ""
        let code: AppErrorCode
        switch true {
        case status == 429: code = .rateLimited
        case status >= 500: code = .serverError
        case ["token_expired", "invalid_token", "invalid_refresh_token", "refresh_token_reused"].contains(serverCode):
            code = .refreshFailed
        case serverCode == "session_revoked": code = .deviceRevoked
        case ["companion_protocol_unsupported", "workout_schema_unsupported", "result_schema_unsupported", "capability_mismatch"].contains(serverCode):
            code = .serverIncompatible
        case serverCode == "package_hash_mismatch": code = .packageHashMismatch
        case ["revision_conflict", "delivery_state_conflict", "progress_sequence_conflict"].contains(serverCode):
            code = .revisionConflict
        case ["event_conflict", "progress_event_conflict", "idempotency_conflict"].contains(serverCode):
            code = .submissionConflict
        case status == 401: code = .unauthorized
        case (400...499).contains(status): code = .validationError
        default: code = .unknown
        }
        let message: String
        switch code {
        case .rateLimited: message = "Demasiados intentos. Espera y vuelve a intentar."
        case .serverError: message = "El servidor tuvo un problema temporal."
        case .refreshFailed: message = "La sesión venció. Inicia sesión nuevamente."
        case .deviceRevoked: message = "Este dispositivo fue revocado desde el servidor."
        case .serverIncompatible: message = "El servidor no ofrece una versión compatible."
        case .packageHashMismatch: message = "El entrenamiento descargado no pasó la verificación de integridad."
        case .revisionConflict: message = "El entrenamiento cambió en el servidor. Revisa el conflicto antes de continuar."
        case .submissionConflict: message = "El servidor detectó contenido distinto para la misma operación."
        case .unauthorized: message = "No fue posible autenticar la solicitud."
        case .validationError: message = error?.message ?? "Revisa los datos e inténtalo de nuevo."
        default: message = "No fue posible completar la operación."
        }
        return AppFailure(
            code,
            message,
            retryable: code == .rateLimited || code == .serverError,
            retryAfterSeconds: retryAfter,
            requestId: error?.requestId,
            serverCode: error?.code
        )
    }

    /// Maps transport failures to sanitized messages; host names and certificate details never leak.
    public static func network(_ error: Error) -> AppFailure {
        guard let urlError = error as? URLError else {
            return AppFailure(.networkUnavailable, "No hay conexión con el servidor. Tus cambios siguen guardados.", retryable: true)
        }
        switch urlError.code {
        case .timedOut:
            return AppFailure(.timeout, "El servidor tardó demasiado en responder.", retryable: true)
        case .cannotFindHost, .dnsLookupFailed:
            return AppFailure(.networkUnavailable, "No se encontró el servidor configurado. Revisa la red y la URL.", retryable: true)
        case .cannotConnectToHost:
            return AppFailure(.networkUnavailable, "El servidor rechazó o no aceptó la conexión. Tus cambios siguen guardados.", retryable: true)
        case .secureConnectionFailed, .serverCertificateHasBadDate, .serverCertificateUntrusted,
             .serverCertificateHasUnknownRoot, .serverCertificateNotYetValid, .clientCertificateRejected,
             .clientCertificateRequired, .appTransportSecurityRequiresSecureConnection:
            return AppFailure(.tlsError, "No se pudo validar la conexión segura con el servidor.", retryable: false)
        default:
            return AppFailure(.networkUnavailable, "No hay conexión con el servidor. Tus cambios siguen guardados.", retryable: true)
        }
    }
}

public enum RefreshFailureDisposition: Sendable {
    case preserveLocalSession, clearLocalSession
}

public func refreshFailureDisposition(_ error: AppFailure) -> RefreshFailureDisposition {
    switch error.code {
    case .refreshFailed, .deviceRevoked: return .clearLocalSession
    default: return .preserveLocalSession
    }
}
