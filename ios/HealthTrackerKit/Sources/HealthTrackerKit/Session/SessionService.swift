import Foundation

public struct LoginOutcome: Sendable, Equatable {
    public let scope: String
    public let profile: UserProfile
}

/// Server connection and session lifecycle (Android `CompanionRepository` auth subset).
/// Stage 2 extends `login`/`restoreOnlineSession` with bootstrap, negotiation and the offline cache.
public final class SessionService: Sendable {
    public let api: APIClient
    public let preferences: PreferenceStore
    public let tokens: TokenStore
    private let accounts: AccountStore
    private let appVersion: String
    private let now: @Sendable () -> Date

    public init(
        api: APIClient,
        preferences: PreferenceStore,
        tokens: TokenStore,
        accounts: AccountStore,
        appVersion: String,
        now: @escaping @Sendable () -> Date = Date.init
    ) {
        self.api = api
        self.preferences = preferences
        self.tokens = tokens
        self.accounts = accounts
        self.appVersion = appVersion
        self.now = now
    }

    /// Validates the URL and checks that the server identifies itself as Health Tracker.
    public func testServer(_ rawURL: String, explicitLocalHTTP: Bool) async throws -> String {
        let validated = ServerURLValidator.validate(rawURL, explicitLocalHTTP: explicitLocalHTTP)
        guard let url = validated.normalizedURL else {
            throw AppFailure(.validationError, validated.error ?? "URL inválida.", retryable: false)
        }
        let health = try await api.health(baseURL: url)
        guard health.status == "ok", health.app == "health-tracker" else {
            throw AppFailure(.serverIncompatible, "El servidor no se identifica como Health Tracker.", retryable: false)
        }
        return url
    }

    public func login(
        rawURL: String,
        explicitLocalHTTP: Bool,
        email: String,
        password: String,
        deviceName: String,
        osVersion: String
    ) async throws -> LoginOutcome {
        let baseURL = try await testServer(rawURL, explicitLocalHTTP: explicitLocalHTTP)
        preferences.configureServer(baseURL, allowLocalHTTP: explicitLocalHTTP)
        let deviceId = preferences.ensureDeviceId()
        let request = LoginRequest(
            email: email.trimmingCharacters(in: .whitespacesAndNewlines),
            password: password,
            device: DeviceRegistration(deviceId: deviceId, name: deviceName, appVersion: appVersion, osVersion: osVersion)
        )
        let api = self.api
        let createdScope = ScopeBox()
        return try await authenticatedLoginWithCompensation(
            remoteLogin: { _ = try await api.login(baseURL: baseURL, request: request) },
            authenticatedWork: { [self] in
                let profile = try await api.me()
                let scope = CanonicalJSON.accountScope(serverURL: baseURL, userPublicId: profile.id)
                createdScope.value = scope
                preferences.setAccountScope(scope)
                try accounts.upsert(AccountRecord(
                    scope: scope, serverURL: baseURL, userPublicId: profile.id, displayEmail: profile.email,
                    deviceId: deviceId, timezone: profile.timezone, createdAt: ISO8601DateFormatter().string(from: now())
                ))
                preferences.setOfflineSessionEligible(true)
                return LoginOutcome(scope: scope, profile: profile)
            },
            remoteLogout: { try await api.logout() },
            localCleanup: { [self] in try cleanupIncompleteLogin(createdScope.value) }
        )
    }

    /// Restores a session from local state only, so the app is usable offline.
    public func restoreLocalSession() -> UserProfile? {
        let local = preferences.values
        guard let scope = local.accountScope, local.offlineSessionEligible,
              let serverURL = local.serverURL, !local.deviceId.isEmpty,
              tokens.refreshToken(serverIdentity: serverURL) != nil,
              let account = accounts.account(scope),
              account.scope == scope, account.serverURL == serverURL, account.deviceId == local.deviceId else { return nil }
        return UserProfile(
            id: account.userPublicId,
            email: account.displayEmail,
            role: "offline_cache",
            timezone: account.timezone,
            createdAt: account.createdAt
        )
    }

    public func restoreOnlineSession(scope: String) async throws -> UserProfile {
        let local = preferences.values
        guard let account = accounts.account(scope) else {
            throw AppFailure(.localStorageError, "Falta la identidad local de la cuenta.", retryable: false)
        }
        guard local.accountScope == scope, account.serverURL == local.serverURL, account.deviceId == local.deviceId else {
            throw AppFailure(.localStorageError, "La sesión local no corresponde a esta cuenta y dispositivo.", retryable: false)
        }
        try await api.restoreSession()
        let profile = try await api.me()
        guard CanonicalJSON.accountScope(serverURL: account.serverURL, userPublicId: profile.id) == scope else {
            throw AppFailure(.refreshFailed, "La sesión restaurada no corresponde a la cuenta local.", retryable: false)
        }
        return profile
    }

    public func logout(scope: String, revokeDevice: Bool) async throws {
        if revokeDevice {
            try await api.revokeDevice(preferences.values.deviceId)
        } else {
            try? await api.logout()
        }
        try clearLocal(scope: scope)
    }

    public func logoutAll(scope: String) async throws {
        try await api.logoutAll()
        try clearLocal(scope: scope)
    }

    public func clearLocal(scope: String) throws {
        try accounts.clearAccountData(scope)
        tokens.clear()
        preferences.setOfflineSessionEligible(false)
        preferences.setAccountScope(nil)
    }

    public func clearConfirmedInvalidSession(scope: String) throws {
        if preferences.values.accountScope == scope { try clearLocal(scope: scope) }
    }

    /// Ends the active session but keeps local rows under their scope; a new login derives a new scope.
    public func detachForServerSwitch() {
        tokens.clear()
        preferences.setOfflineSessionEligible(false)
        preferences.setAccountScope(nil)
    }

    private func cleanupIncompleteLogin(_ scope: String?) throws {
        tokens.clear()
        preferences.setOfflineSessionEligible(false)
        preferences.setAccountScope(nil)
        if let scope { try accounts.clearAccountData(scope) }
    }
}

private final class ScopeBox: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: String?
    var value: String? {
        get { lock.withLock { stored } }
        set { lock.withLock { stored = newValue } }
    }
}
