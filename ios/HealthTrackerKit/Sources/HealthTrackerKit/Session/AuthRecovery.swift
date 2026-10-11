import Foundation

public struct AuthRecoveryDecision: Sendable, Equatable {
    public let state: AuthState
    public let message: String
    public let clearLocalSession: Bool
}

/// Decides what a failed online restore means for a session that was already usable offline.
public func classifyRestoreFailure(_ error: Error) -> AuthRecoveryDecision {
    guard let failure = error as? AppFailure else {
        return AuthRecoveryDecision(state: .signedOut, message: "No fue posible restaurar la sesión.", clearLocalSession: false)
    }
    switch failure.code {
    case .networkUnavailable, .timeout, .tlsError, .serverError, .rateLimited, .unauthorized:
        return AuthRecoveryDecision(
            state: .authenticated,
            message: "Modo offline: puedes continuar con los entrenamientos ya descargados.",
            clearLocalSession: false
        )
    case .deviceRevoked:
        return AuthRecoveryDecision(state: .deviceRevoked, message: "Este dispositivo fue revocado desde el servidor.", clearLocalSession: true)
    case .serverIncompatible, .schemaIncompatible:
        return AuthRecoveryDecision(state: .serverIncompatible, message: failure.userMessage, clearLocalSession: false)
    case .refreshFailed:
        return AuthRecoveryDecision(state: .tokenExpired, message: "La sesión venció. Inicia sesión nuevamente.", clearLocalSession: true)
    default:
        return AuthRecoveryDecision(state: .signedOut, message: failure.userMessage, clearLocalSession: false)
    }
}

/// Runs authenticated setup after a remote login. If setup fails, the remote session is logged out
/// and local state cleaned even when the caller is cancelled; the original error always wins.
public func authenticatedLoginWithCompensation<T: Sendable>(
    remoteLogin: @Sendable () async throws -> Void,
    authenticatedWork: @Sendable () async throws -> T,
    remoteLogout: @escaping @Sendable () async throws -> Void,
    localCleanup: @escaping @Sendable () async throws -> Void
) async throws -> T {
    try await remoteLogin()
    do {
        return try await authenticatedWork()
    } catch {
        // An unstructured task does not inherit cancellation (Kotlin's NonCancellable).
        await Task {
            try? await remoteLogout()
            try? await localCleanup()
        }.value
        throw error
    }
}
