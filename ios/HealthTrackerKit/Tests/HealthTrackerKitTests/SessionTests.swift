import Foundation
import Testing
@testable import HealthTrackerKit

/// Scripted transport: responses are matched by "METHOD path" and consumed in order.
final class FakeTransport: HTTPTransport, @unchecked Sendable {
    private let lock = NSLock()
    private var scripted: [String: [HTTPResult]] = [:]
    private(set) var requests: [URLRequest] = []

    func on(_ method: String, _ path: String, status: Int = 200, json: String, headers: [String: String] = [:]) {
        lock.withLock { scripted["\(method) \(path)", default: []].append(HTTPResult(status: status, headers: headers, body: Data(json.utf8))) }
    }

    func send(_ request: URLRequest) async throws -> HTTPResult {
        try lock.withLock {
            requests.append(request)
            let key = "\(request.httpMethod ?? "GET") \(request.url?.path ?? "")"
            guard var queue = scripted[key], !queue.isEmpty else { throw URLError(.cannotConnectToHost) }
            let next = queue.removeFirst()
            scripted[key] = queue
            return next
        }
    }

    func count(_ method: String, _ path: String) -> Int {
        lock.withLock { requests.filter { $0.httpMethod == method && $0.url?.path == path }.count }
    }
}

let qaServer = "https://tracker.example"
let qaProfile = #"{"data":{"id":"qa-user-1","email":"qa@example.test","role":"user","timezone":"America/Mexico_City","created_at":"2026-01-01T00:00:00Z","capabilities":{"mobile":true}}}"#

func tokenJSON(_ suffix: String) -> String {
    #"{"data":{"access_token":"qa-access-\#(suffix)","refresh_token":"qa-refresh-\#(suffix)","token_type":"Bearer","expires_in":900,"refresh_expires_at":"2026-12-01T00:00:00Z"}}"#
}

struct Harness {
    let transport = FakeTransport()
    let preferences: PreferenceStore
    let tokens = TokenStore(storage: InMemorySecureStorage())
    let store: LocalStore
    let api: APIClient
    let session: SessionService

    init() throws {
        preferences = PreferenceStore(defaults: UserDefaults(suiteName: "qa.\(UUID().uuidString)")!)
        store = try LocalStore.make(inMemory: true)
        api = APIClient(preferences: preferences, tokens: tokens, transport: transport)
        session = SessionService(api: api, preferences: preferences, tokens: tokens, store: store, appVersion: "0.1.0-qa")
        transport.on("GET", "/api/v1/health", json: #"{"data":{"status":"ok","app":"health-tracker"}}"#)
    }

    func scriptBootstrapAndNegotiation(deviceId: String = "qa-device", cursor: String = "qa-cursor-0") {
        transport.on("GET", "/api/v1/sync/bootstrap", json: QAFixtures.bootstrap(deviceId: deviceId, cursor: cursor))
        transport.on("POST", "/api/v1/companion/negotiate", json: QAFixtures.negotiation(deviceId: deviceId))
    }

    func login() async throws -> LoginOutcome {
        transport.on("POST", "/api/v1/auth/login", json: tokenJSON("1"))
        transport.on("GET", "/api/v1/me", json: qaProfile)
        scriptBootstrapAndNegotiation()
        return try await session.login(rawURL: qaServer + "/", explicitLocalHTTP: false, email: " qa@example.test ", password: "qa-password", deviceName: "QA iPhone", osVersion: "iOS 18.2")
    }
}

struct LoginCompensationTests {
    actor Events {
        var items: [String] = []
        func add(_ value: String) { items.append(value) }
    }

    struct QAError: Error, Equatable { let name: String }

    @Test func remoteLoginFailureDoesNotLogoutOrCleanAuthenticatedState() async {
        let events = Events()
        await #expect(throws: QAError(name: "qa_login_failed")) {
            try await authenticatedLoginWithCompensation(
                remoteLogin: { await events.add("login"); throw QAError(name: "qa_login_failed") },
                authenticatedWork: { await events.add("bootstrap") },
                remoteLogout: { await events.add("logout") },
                localCleanup: { await events.add("cleanup") }
            )
        }
        #expect(await events.items == ["login"])
    }

    @Test func bootstrapFailureLogsOutBeforeCleanupAndRethrowsOriginal() async {
        let events = Events()
        await #expect(throws: QAError(name: "qa_bootstrap_failed")) {
            try await authenticatedLoginWithCompensation(
                remoteLogin: { await events.add("login") },
                authenticatedWork: { await events.add("bootstrap"); throw QAError(name: "qa_bootstrap_failed") },
                remoteLogout: { await events.add("logout") },
                localCleanup: { await events.add("cleanup") }
            )
        }
        #expect(await events.items == ["login", "bootstrap", "logout", "cleanup"])
    }

    @Test func successfulLoginDoesNotCompensate() async throws {
        let events = Events()
        let outcome = try await authenticatedLoginWithCompensation(
            remoteLogin: { await events.add("login") },
            authenticatedWork: { await events.add("bootstrap"); return "qa_success" },
            remoteLogout: { await events.add("logout") },
            localCleanup: { await events.add("cleanup") }
        )
        #expect(outcome == "qa_success")
        #expect(await events.items == ["login", "bootstrap"])
    }

    @Test func compensatingLogoutFailureKeepsOriginalAndStillCleansLocally() async {
        let events = Events()
        await #expect(throws: QAError(name: "qa_bootstrap_failed")) {
            try await authenticatedLoginWithCompensation(
                remoteLogin: { await events.add("login") },
                authenticatedWork: { await events.add("bootstrap"); throw QAError(name: "qa_bootstrap_failed") },
                remoteLogout: { await events.add("logout"); throw QAError(name: "qa_logout_failed") },
                localCleanup: { await events.add("cleanup") }
            )
        }
        #expect(await events.items == ["login", "bootstrap", "logout", "cleanup"])
    }
}

struct SessionServiceTests {
    @Test func loginRegistersIOSDeviceStoresScopedSessionAndSupportsOfflineRestore() async throws {
        let h = try Harness()
        let outcome = try await h.login()

        #expect(outcome.profile.email == "qa@example.test")
        #expect(outcome.scope == CanonicalJSON.accountScope(serverURL: qaServer, userPublicId: "qa-user-1"))
        #expect(h.preferences.values.serverURL == qaServer)
        #expect(h.preferences.values.accountScope == outcome.scope)
        #expect(h.tokens.refreshToken(serverIdentity: qaServer) == "qa-refresh-1")

        let loginRequest = try #require(h.transport.requests.first { $0.url?.path == "/api/v1/auth/login" })
        let body = try JSONValue.parse(try #require(loginRequest.httpBody))
        #expect(body["email"]?.stringValue == "qa@example.test")
        #expect(body["device"]?["platform"]?.stringValue == "ios")
        #expect(body["device"]?["device_id"]?.stringValue == h.preferences.values.deviceId)
        let meRequest = try #require(h.transport.requests.first { $0.url?.path == "/api/v1/me" })
        #expect(meRequest.value(forHTTPHeaderField: "Authorization") == "Bearer qa-access-1")

        #expect(await h.store.recentSessions(outcome.scope).count == 1)
        #expect(await h.store.syncCursor(outcome.scope) == "qa-cursor-0")
        #expect(await h.store.localProfileRevision(outcome.scope) == 2)
        let offline = try #require(await h.session.restoreLocalSession())
        #expect(offline.role == "offline_cache")
        #expect(offline.id == "qa-user-1")
    }

    @Test func failedPostLoginSetupLogsOutAndLeavesNoLocalSession() async throws {
        let h = try Harness()
        h.transport.on("POST", "/api/v1/auth/login", json: tokenJSON("1"))
        h.transport.on("GET", "/api/v1/me", json: #"{"data":{"unexpected":true}}"#)
        h.transport.on("POST", "/api/v1/auth/logout", json: #"{"data":{}}"#)

        await #expect(throws: AppFailure.self) {
            _ = try await h.session.login(rawURL: qaServer, explicitLocalHTTP: false, email: "qa@example.test", password: "x", deviceName: "QA", osVersion: "iOS")
        }
        #expect(h.transport.count("POST", "/api/v1/auth/logout") == 1)
        #expect(h.tokens.refreshToken() == nil)
        #expect(h.preferences.values.accountScope == nil)
        #expect(await h.session.restoreLocalSession() == nil)
    }

    @Test func nonHealthTrackerServerIsRejectedBeforeCredentialsAreSent() async throws {
        let transport = FakeTransport()
        let preferences = PreferenceStore(defaults: UserDefaults(suiteName: "qa.\(UUID().uuidString)")!)
        let tokens = TokenStore(storage: InMemorySecureStorage())
        let api = APIClient(preferences: preferences, tokens: tokens, transport: transport)
        let session = SessionService(api: api, preferences: preferences, tokens: tokens, store: try LocalStore.make(inMemory: true), appVersion: "qa")
        transport.on("GET", "/api/v1/health", json: #"{"data":{"status":"ok","app":"something-else"}}"#)

        await #expect(throws: AppFailure(.serverIncompatible, "El servidor no se identifica como Health Tracker.", retryable: false)) {
            _ = try await session.login(rawURL: qaServer, explicitLocalHTTP: false, email: "qa@example.test", password: "x", deviceName: "QA", osVersion: "iOS")
        }
        #expect(transport.count("POST", "/api/v1/auth/login") == 0)
    }

    @Test func expiredAccessTokenIsRefreshedOnceAndRequestRetried() async throws {
        let h = try Harness()
        _ = try await h.login()
        h.transport.on("GET", "/api/v1/me", status: 401, json: #"{"error":{"code":"token_expired","message":"expired"}}"#)
        h.transport.on("POST", "/api/v1/auth/refresh", json: tokenJSON("2"))
        h.transport.on("GET", "/api/v1/me", json: qaProfile)

        let profile = try await h.api.me()
        #expect(profile.id == "qa-user-1")
        #expect(h.transport.count("POST", "/api/v1/auth/refresh") == 1)
        #expect(h.tokens.accessToken(serverIdentity: qaServer) == "qa-access-2")
        #expect(h.tokens.refreshToken(serverIdentity: qaServer) == "qa-refresh-2")
        let retried = try #require(h.transport.requests.last)
        #expect(retried.value(forHTTPHeaderField: "Authorization") == "Bearer qa-access-2")
    }

    @Test func revokedSessionClearsTokensWithoutRefreshing() async throws {
        let h = try Harness()
        _ = try await h.login()
        h.transport.on("GET", "/api/v1/me", status: 401, json: #"{"error":{"code":"session_revoked","message":"revoked"}}"#)

        await #expect(throws: AppFailure.self) { _ = try await h.api.me() }
        #expect(h.transport.count("POST", "/api/v1/auth/refresh") == 0)
        #expect(h.tokens.refreshToken() == nil)
    }

    @Test func definitiveRefreshFailureClearsSessionButTemporaryFailureKeepsIt() async throws {
        let h = try Harness()
        _ = try await h.login()
        h.transport.on("GET", "/api/v1/me", status: 401, json: #"{"error":{"code":"token_expired","message":"expired"}}"#)
        h.transport.on("POST", "/api/v1/auth/refresh", status: 503, json: #"{"error":{"code":"unavailable","message":"later"}}"#)
        await #expect(throws: AppFailure.self) { _ = try await h.api.me() }
        #expect(h.tokens.refreshToken(serverIdentity: qaServer) == "qa-refresh-1")

        h.transport.on("GET", "/api/v1/me", status: 401, json: #"{"error":{"code":"token_expired","message":"expired"}}"#)
        h.transport.on("POST", "/api/v1/auth/refresh", status: 401, json: #"{"error":{"code":"invalid_refresh_token","message":"no"}}"#)
        do {
            _ = try await h.api.me()
            Issue.record("Expected refresh failure")
        } catch let failure as AppFailure {
            #expect(failure.code == .refreshFailed)
        }
        #expect(h.tokens.refreshToken() == nil)
    }

    @Test func restoreOnlineRejectsAProfileFromAnotherAccount() async throws {
        let h = try Harness()
        let outcome = try await h.login()
        h.transport.on("GET", "/api/v1/me", json: qaProfile.replacingOccurrences(of: "qa-user-1", with: "qa-user-2"))

        do {
            _ = try await h.session.restoreOnlineSession(scope: outcome.scope)
            Issue.record("Expected scope mismatch")
        } catch let failure as AppFailure {
            #expect(failure.code == .refreshFailed)
        }
    }

    @Test func logoutClearsLocalSessionEvenWhenServerIsUnreachable() async throws {
        let h = try Harness()
        let outcome = try await h.login()
        try await h.session.logout(scope: outcome.scope, revokeDevice: false)
        #expect(h.tokens.refreshToken() == nil)
        #expect(h.preferences.values.accountScope == nil)
        #expect(h.preferences.values.serverURL == qaServer)
        #expect(await h.session.restoreLocalSession() == nil)
    }

    @Test func oversizedResponsesAreRejected() async throws {
        let h = try Harness()
        let huge = String(repeating: "a", count: APIClient.maxResponseBytes + 1)
        h.transport.on("GET", "/api/v1/health", json: huge)
        _ = try await h.api.health(baseURL: qaServer) // consumes the default scripted response
        do {
            _ = try await h.api.health(baseURL: qaServer)
            Issue.record("Expected size failure")
        } catch let failure as AppFailure {
            #expect(failure.code == .schemaIncompatible)
        }
    }
}
