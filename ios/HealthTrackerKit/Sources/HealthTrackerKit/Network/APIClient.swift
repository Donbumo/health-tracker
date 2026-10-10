import Foundation
import os

/// Typed `/api/v1` client. Mirrors the Android `ApiClient` request policy: bearer auth bound to
/// the configured server, single-flight refresh on 401, no redirects, bounded responses, and
/// sanitized `AppFailure`s for every error path.
public actor APIClient {
    private let preferences: PreferenceStore
    private let tokens: TokenStore
    private let transport: HTTPTransport
    private var refreshTask: Task<Void, Error>?
    private let logger = Logger(subsystem: "io.healthtracker.companion", category: "HealthTrackerContract")

    static let maxResponseBytes = 4 * 1024 * 1024
    static let maxRetryAfterSeconds: Int64 = 6 * 60 * 60

    public init(preferences: PreferenceStore, tokens: TokenStore, transport: HTTPTransport = URLSessionTransport()) {
        self.preferences = preferences
        self.tokens = tokens
        self.transport = transport
    }

    // MARK: Auth and identity

    public func health(baseURL: String? = nil) async throws -> HealthResponse {
        try await call("/api/v1/health", method: "GET", baseOverride: baseURL, requiresAuth: false)
    }

    public func login(baseURL: String, request: LoginRequest) async throws -> TokenResponse {
        let expected = tokens.mutationVersion
        let result: TokenResponse = try await call(
            "/api/v1/auth/login", method: "POST", body: try Self.encode(request), baseOverride: baseURL, requiresAuth: false
        )
        guard try tokens.replaceTokensIfVersion(expected, access: result.accessToken, refresh: result.refreshToken, serverIdentity: baseURL) else {
            throw AppFailure(.unauthorized, "La sesión cambió durante el inicio de sesión.", retryable: false)
        }
        return result
    }

    public func me() async throws -> UserProfile {
        try await call("/api/v1/me", method: "GET")
    }

    /// Obtains a fresh access token from the stored refresh token when none is in memory.
    public func restoreSession() async throws {
        guard let base = preferences.values.serverURL else {
            throw AppFailure(.refreshFailed, "Falta la configuración del servidor.", retryable: false)
        }
        if tokens.accessToken(serverIdentity: base) == nil, tokens.refreshToken(serverIdentity: base) != nil {
            try await refreshSingleFlight(base: base, failedAccess: nil)
        }
    }

    public func logout() async throws {
        let _: EmptyPayload = try await call("/api/v1/auth/logout", method: "POST", body: Data("{}".utf8))
    }

    public func logoutAll() async throws {
        let _: EmptyPayload = try await call("/api/v1/auth/logout-all", method: "POST", body: Data("{}".utf8))
    }

    public func revokeDevice(_ deviceId: String) async throws {
        let _: EmptyPayload = try await call("/api/v1/devices/\(Self.encodePathComponent(deviceId))", method: "DELETE")
    }

    // MARK: Generic request plumbing

    /// Decodes the `data` member of the standard envelope.
    public func call<T: Decodable & Sendable>(
        _ path: String,
        method: String,
        body: Data? = nil,
        baseOverride: String? = nil,
        requiresAuth: Bool = true,
        idempotencyKey: String? = nil
    ) async throws -> T {
        let raw = try await rawCall(path, method: method, body: body, baseOverride: baseOverride, requiresAuth: requiresAuth, idempotencyKey: idempotencyKey)
        do {
            return try JSONDecoder().decode(APIEnvelope<T>.self, from: raw).data
        } catch {
            logContractDecodeFailure(path: path, error: error)
            throw AppFailure(.schemaIncompatible, "El servidor respondió con un contrato incompatible.", retryable: false)
        }
    }

    /// Returns the envelope's `data` member as a lossless JSON tree.
    public func callJSON(
        _ path: String,
        method: String,
        body: Data? = nil,
        requiresAuth: Bool = true,
        idempotencyKey: String? = nil
    ) async throws -> JSONValue {
        let raw = try await rawCall(path, method: method, body: body, requiresAuth: requiresAuth, idempotencyKey: idempotencyKey)
        guard let root = try? JSONValue.parse(raw), let data = root["data"] else {
            logContractDecodeFailure(path: path, error: nil)
            throw AppFailure(.schemaIncompatible, "El servidor respondió con un contrato incompatible.", retryable: false)
        }
        return data
    }

    func rawCall(
        _ path: String,
        method: String,
        body: Data? = nil,
        baseOverride: String? = nil,
        requiresAuth: Bool = true,
        idempotencyKey: String? = nil,
        allowRefresh: Bool = true
    ) async throws -> Data {
        guard let base = baseOverride ?? preferences.values.serverURL else {
            throw AppFailure(.serverIncompatible, "Configura un servidor antes de continuar.", retryable: false)
        }
        let failedAccess = tokens.accessToken(serverIdentity: base)
        let requestVersion = tokens.mutationVersion
        let response = try await execute(base: base, path: path, method: method, body: body, requiresAuth: requiresAuth, idempotencyKey: idempotencyKey)
        if response.status == 401, requiresAuth, allowRefresh {
            let parsed = try? JSONDecoder().decode(ErrorEnvelope.self, from: response.body).error
            if parsed?.code == "session_revoked" {
                guard tokens.clearIfVersion(requestVersion) else {
                    throw AppFailure(.unauthorized, "La sesión cambió durante la solicitud.", retryable: false)
                }
                throw ErrorMapper.http(status: 401, error: parsed, retryAfter: nil)
            }
            try await refreshSingleFlight(base: base, failedAccess: failedAccess)
            return try await rawCall(path, method: method, body: body, baseOverride: base, requiresAuth: true, idempotencyKey: idempotencyKey, allowRefresh: false)
        }
        return try checked(response)
    }

    private func execute(base: String, path: String, method: String, body: Data?, requiresAuth: Bool, idempotencyKey: String?) async throws -> HTTPResult {
        guard let url = URL(string: Self.trimTrailingSlash(base) + path) else {
            throw AppFailure(.validationError, "La URL del servidor no es válida.", retryable: false)
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if requiresAuth {
            guard let token = tokens.accessToken(serverIdentity: base) else {
                throw AppFailure(.unauthorized, "Inicia sesión para continuar.", retryable: false)
            }
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let idempotencyKey { request.setValue(idempotencyKey, forHTTPHeaderField: "Idempotency-Key") }
        if let body {
            request.httpBody = body
            request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        }
        do {
            return try await transport.send(request)
        } catch let failure as AppFailure {
            throw failure
        } catch {
            throw ErrorMapper.network(error)
        }
    }

    private func checked(_ response: HTTPResult) throws -> Data {
        if let declared = response.header("Content-Length").flatMap(Int.init), declared > Self.maxResponseBytes {
            throw AppFailure(.schemaIncompatible, "La respuesta del servidor excede el límite permitido.", retryable: false)
        }
        guard response.body.count <= Self.maxResponseBytes else {
            throw AppFailure(.schemaIncompatible, "La respuesta del servidor excede el límite permitido.", retryable: false)
        }
        if (200...299).contains(response.status) { return response.body }
        let parsed = try? JSONDecoder().decode(ErrorEnvelope.self, from: response.body).error
        throw ErrorMapper.http(status: response.status, error: parsed, retryAfter: Self.parseRetryAfter(response.header("Retry-After")))
    }

    // MARK: Refresh

    private func refreshSingleFlight(base: String, failedAccess: String?) async throws {
        if let running = refreshTask {
            try await running.value
            return
        }
        if let current = tokens.accessToken(serverIdentity: base), current != failedAccess { return }
        let task = Task { try await self.performRefresh(base: base) }
        refreshTask = task
        defer { refreshTask = nil }
        try await task.value
    }

    private func performRefresh(base: String) async throws {
        let expected = tokens.mutationVersion
        guard let refresh = tokens.refreshToken(serverIdentity: base) else {
            tokens.clearIfVersion(expected)
            throw AppFailure(.refreshFailed, "La sesión venció. Inicia sesión nuevamente.", retryable: false)
        }
        do {
            let response: TokenResponse = try await call(
                "/api/v1/auth/refresh", method: "POST", body: try Self.encode(RefreshRequest(refreshToken: refresh)),
                baseOverride: base, requiresAuth: false
            )
            guard try tokens.replaceTokensIfVersion(expected, access: response.accessToken, refresh: response.refreshToken, serverIdentity: base) else {
                throw AppFailure(.unauthorized, "La sesión cambió durante la renovación.", retryable: false)
            }
        } catch let error as AppFailure {
            if tokens.mutationVersion != expected { throw error }
            if refreshFailureDisposition(error) == .preserveLocalSession { throw error }
            tokens.clearIfVersion(expected)
            if error.code == .deviceRevoked { throw error }
            throw AppFailure(.refreshFailed, "No fue posible renovar la sesión. Inicia sesión nuevamente.", retryable: false)
        }
    }

    // MARK: Helpers

    static func encode<T: Encodable>(_ value: T) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.withoutEscapingSlashes]
        return try encoder.encode(value)
    }

    /// `application/x-www-form-urlencoded` style, matching Java `URLEncoder` used by Android.
    public static func encodeQuery(_ value: String) -> String {
        var allowed = CharacterSet.alphanumerics.intersection(CharacterSet(charactersIn: Unicode.Scalar(0)..<Unicode.Scalar(128)))
        allowed.insert(charactersIn: ".-*_ ")
        let encoded = value.addingPercentEncoding(withAllowedCharacters: allowed) ?? ""
        return encoded.replacingOccurrences(of: " ", with: "+")
    }

    static func encodePathComponent(_ value: String) -> String {
        var allowed = CharacterSet.alphanumerics.intersection(CharacterSet(charactersIn: Unicode.Scalar(0)..<Unicode.Scalar(128)))
        allowed.insert(charactersIn: "-._~")
        return value.addingPercentEncoding(withAllowedCharacters: allowed) ?? ""
    }

    static func parseRetryAfter(_ value: String?, now: Date = Date()) -> Int64? {
        guard let value else { return nil }
        if let seconds = Int64(value.trimmingCharacters(in: .whitespaces)) {
            return min(max(seconds, 0), maxRetryAfterSeconds)
        }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "GMT")
        formatter.dateFormat = "EEE, dd MMM yyyy HH:mm:ss zzz"
        guard let date = formatter.date(from: value) else { return nil }
        return min(max(Int64(date.timeIntervalSince(now)), 0), maxRetryAfterSeconds)
    }

    private static func trimTrailingSlash(_ value: String) -> String {
        var result = value
        while result.hasSuffix("/") { result.removeLast() }
        return result
    }

    private func logContractDecodeFailure(path: String, error: Error?) {
        #if DEBUG
        let endpoint = String(
            path.split(separator: "?", maxSplits: 1).first.map(String.init)?
                .replacingOccurrences(of: "/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}", with: "/{id}", options: .regularExpression)
                .prefix(160) ?? ""
        )
        var codingPath = ""
        if case let .keyNotFound(key, context)? = error as? DecodingError {
            codingPath = (context.codingPath + [key]).map(\.stringValue).joined(separator: ".")
        } else if case let .typeMismatch(_, context)? = error as? DecodingError {
            codingPath = context.codingPath.map(\.stringValue).joined(separator: ".")
        } else if case let .valueNotFound(_, context)? = error as? DecodingError {
            codingPath = context.codingPath.map(\.stringValue).joined(separator: ".")
        }
        let pathDiagnostic = codingPath.isEmpty ? "" : " path=\(codingPath.prefix(160))"
        logger.warning("contract_decode_failed endpoint=\(endpoint, privacy: .public) code=contract_field_incompatible\(pathDiagnostic, privacy: .public)")
        #endif
    }
}

// MARK: Mobile Sync and Companion negotiation

extension APIClient {
    public func bootstrap() async throws -> BootstrapResponse {
        try await call("/api/v1/sync/bootstrap", method: "GET")
    }

    public func pull(cursor: String, limit: Int) async throws -> PullResponse {
        try await call("/api/v1/sync/pull?cursor=\(Self.encodeQuery(cursor))&limit=\(limit)", method: "GET")
    }

    public func syncStatus() async throws -> SyncStatusResponse {
        try await call("/api/v1/sync/status", method: "GET")
    }

    public func negotiate(_ request: NegotiationRequest) async throws -> NegotiationResponse {
        try await call("/api/v1/companion/negotiate", method: "POST", body: try Self.encode(request))
    }
}
