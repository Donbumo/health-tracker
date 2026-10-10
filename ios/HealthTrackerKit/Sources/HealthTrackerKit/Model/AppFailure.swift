import Foundation

public let contractVersion = "1.0"

public enum AuthState: Sendable, Equatable {
    case noServer, signedOut, authenticating, authenticated, tokenExpired
    case deviceRevoked, serverIncompatible, offline, temporaryError, permanentError
}

public enum AppErrorCode: String, Sendable, CaseIterable {
    case networkUnavailable, timeout, tlsError, unauthorized, refreshFailed, deviceRevoked
    case serverIncompatible, schemaIncompatible, packageHashMismatch, packageExpired
    case revisionConflict, submissionConflict, validationError, rateLimited
    case serverError, localStorageError, draftCorrupt, unknown
}

/// Stable, user-safe failure. `userMessage` never contains raw server or transport details.
public struct AppFailure: Error, Sendable, Equatable, LocalizedError {
    public let code: AppErrorCode
    public let userMessage: String
    public let retryable: Bool
    public let retryAfterSeconds: Int64?
    public let requestId: String?
    public let serverCode: String?

    public init(
        _ code: AppErrorCode,
        _ userMessage: String,
        retryable: Bool,
        retryAfterSeconds: Int64? = nil,
        requestId: String? = nil,
        serverCode: String? = nil
    ) {
        self.code = code
        self.userMessage = userMessage
        self.retryable = retryable
        self.retryAfterSeconds = retryAfterSeconds
        self.requestId = requestId
        self.serverCode = serverCode
    }

    public var errorDescription: String? { userMessage }
}
