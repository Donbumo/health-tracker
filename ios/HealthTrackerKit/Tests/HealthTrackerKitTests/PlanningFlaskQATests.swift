import Foundation
import Testing
@testable import HealthTrackerKit

/// Opt-in only to an explicitly disposable, loopback Flask QA service. The integration workflow
/// enables this suite on macOS and iOS Simulator; it never discovers a production URL or credentials.
@Suite(.enabled(if: ProcessInfo.processInfo.environment["HT_PLANNING_FLASK_QA_URL"] != nil), .timeLimit(.minutes(2)))
struct PlanningFlaskQAIntegrationTests {
    private func login() async throws -> (APIClient, LocalStore, PreferenceStore, TokenStore, String) {
        let server = try #require(ProcessInfo.processInfo.environment["HT_PLANNING_FLASK_QA_URL"])
        #expect(server == "http://127.0.0.1:8026")
        guard server == "http://127.0.0.1:8026" else { throw URLError(.unsupportedURL) }
        let preferences = PreferenceStore(defaults: UserDefaults(suiteName: "fictional-flask-qa.\(UUID())")!)
        let tokens = TokenStore(storage: InMemorySecureStorage())
        let store = try LocalStore.make(inMemory: true)
        let api = APIClient(preferences: preferences, tokens: tokens)
        let service = SessionService(api: api, preferences: preferences, tokens: tokens, store: store, appVersion: "stage5-qa")
        let outcome = try await service.login(rawURL: server, explicitLocalHTTP: true, email: "ios-ci-qa",
                                               password: "fictional-ios-ci-qa-password", deviceName: "Fictional queue QA", osVersion: "CI QA")
        return (api, store, preferences, tokens, outcome.scope)
    }

    @Test(arguments: ["POST", "PATCH"])
    func flaskConvergesToEditsMadeDuringAnActualRequest(method: String) async throws {
        let (api, store, preferences, tokens, scope) = try await login()
        let id = UUID().uuidString.lowercased()
        try await store.createPlanOffline(scope, id: id, key: UUID().uuidString, name: "Before QA", description: nil)
        if method == "PATCH" {
            try await SyncEngine(api: api, store: store, preferences: preferences, handlers: PlanningHandlers.all).synchronize(scope: scope)
            try await store.editPlanOffline(scope, publicId: id, name: "Patch Before QA", description: nil, key: UUID().uuidString)
        }
        let path = method == "POST" ? "/api/v1/mobile/plans" : "/api/v1/mobile/plans/\(id)"
        let gate = PlanningRequestGate(inner: URLSessionTransport(), method: method, path: path)
        let gatedAPI = APIClient(preferences: preferences, tokens: tokens, transport: gate)
        let engine = SyncEngine(api: gatedAPI, store: store, preferences: preferences, handlers: PlanningHandlers.all)
        let syncing = Task { try await engine.synchronize(scope: scope) }
        let sent = await gate.waitForRequest()
        try await store.editPlanOffline(scope, publicId: id, name: "After QA", description: nil, key: UUID().uuidString)
        try await store.editPlanOffline(scope, publicId: id, name: "After QA 2", description: "Fictional", key: UUID().uuidString)
        await gate.resume()
        try await syncing.value
        let remote = try await api.plan(id)
        let local = try #require(await store.plan(scope, publicId: id))
        #expect(remote.name == "After QA 2" && local.name == remote.name)
        #expect(remote.revision == (method == "POST" ? 2 : 3) && local.revision == remote.revision)
        #expect(local.syncStatus == "synced")
        #expect(await store.snapshot(scope).pendingCount == 0)
        // Replay the first request after both ACKs: the idempotent response must not undo the edit.
        let body = try JSONValue.parse(try #require(sent.httpBody))
        let key = try #require(sent.value(forHTTPHeaderField: "Idempotency-Key"))
        if method == "POST" { try await api.createPlan(body, key: key) }
        else { try await api.patchPlan(id, body, key: key) }
        let replayed = try await api.plan(id)
        #expect(replayed.name == remote.name && replayed.revision == remote.revision)
        let requests = await gate.requests.filter { $0.httpMethod == "POST" || $0.httpMethod == "PATCH" }
        #expect(requests.count == 2)
    }

    @Test func flaskCommitWithLostAckRetriesTheSameCreationAndKeepsTheEdit() async throws {
        let (api, store, preferences, tokens, scope) = try await login()
        let id = UUID().uuidString.lowercased()
        try await store.createPlanOffline(scope, id: id, key: UUID().uuidString, name: "Before QA", description: nil)
        let gate = PlanningRequestGate(inner: URLSessionTransport(), method: "POST", path: "/api/v1/mobile/plans", loseFirstAcknowledgement: true)
        let gatedAPI = APIClient(preferences: preferences, tokens: tokens, transport: gate)
        let clock = Clock()
        let engine = SyncEngine(api: gatedAPI, store: store, preferences: preferences, handlers: PlanningHandlers.all,
                                now: { clock.now }, jitter: { _ in 0 })
        let syncing = Task { try await engine.synchronize(scope: scope) }
        let original = await gate.waitForRequest() // the actual Flask transaction has already committed
        try await store.editPlanOffline(scope, publicId: id, name: "After QA", description: nil, key: UUID().uuidString)
        await gate.resume()
        await #expect(throws: AppFailure.self) { try await syncing.value }
        #expect(try await api.plan(id).name == "Before QA")
        #expect(await store.snapshot(scope).pendingCount == 2)
        clock.advance(31)
        try await engine.synchronize(scope: scope)
        let creations = await gate.requests.filter { $0.httpMethod == "POST" && $0.url?.path == "/api/v1/mobile/plans" }
        #expect(creations.count == 2 && creations[0].httpBody == creations[1].httpBody)
        #expect(creations[0].value(forHTTPHeaderField: "Idempotency-Key") == original.value(forHTTPHeaderField: "Idempotency-Key"))
        #expect(creations[1].value(forHTTPHeaderField: "Idempotency-Key") == original.value(forHTTPHeaderField: "Idempotency-Key"))
        let remote = try await api.plan(id)
        #expect(remote.name == "After QA" && remote.revision == 2)
        #expect(await store.plan(scope, publicId: id)?.name == remote.name)
        #expect(await store.snapshot(scope).pendingCount == 0)
    }
}
