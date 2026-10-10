import Foundation
import Testing
@testable import HealthTrackerKit

/// Ported from android `BootstrapResponseTest` and `SyncTriggerPolicyTest`, plus store/engine coverage.
struct SyncContractTests {
    @Test func historicalWebSessionWithNullClientEventIdDecodesFromBootstrapEnvelope() throws {
        let url = try #require(Bundle.module.url(forResource: "sync_bootstrap_historical_session", withExtension: "json", subdirectory: "Fixtures"))
        let bootstrap = try JSONDecoder().decode(APIEnvelope<BootstrapResponse>.self, from: Data(contentsOf: url)).data
        #expect(bootstrap.schemaVersion == "1.0")
        #expect(bootstrap.device.deviceId == "44444444-4444-4444-8444-444444444444")
        #expect(bootstrap.device.sessionId == "55555555-5555-4555-8555-555555555555")
        #expect(bootstrap.limits == SyncLimits(pushOperations: 50, pullLimit: 200, jsonBytes: 1_048_576))
        #expect(bootstrap.capabilities["companion_delivery"] == true)
        #expect(bootstrap.schemas["completed_workout"] == "1.0")
        #expect(bootstrap.companion.versions["protocol"] == "1.0")
        #expect(bootstrap.companion.deliveries.isEmpty)
        #expect(bootstrap.companion.profile == nil)
        #expect(bootstrap.completedWorkouts.single?.clientEventId == nil)
        // That historical server predates mobile planning: the iOS client must refuse it.
        #expect(throws: AppFailure.self) { try SyncContract.verify(bootstrap) }
    }

    @Test func completeBootstrapAndNegotiationVerify() throws {
        try SyncContract.verify(try QAFixtures.decode(BootstrapResponse.self, envelope: QAFixtures.bootstrap()))
        try SyncContract.verify(try QAFixtures.decode(NegotiationResponse.self, envelope: QAFixtures.negotiation()))
    }

    @Test func incompatibleSchemasCapabilitiesAndFeaturesAreRejected() throws {
        let schemas = QAFixtures.bootstrap().replacingOccurrences(of: #""sync":"1.0""#, with: #""sync":"2.0""#)
        #expect(throws: AppFailure.self) { try SyncContract.verify(try QAFixtures.decode(BootstrapResponse.self, envelope: schemas)) }
        let caps = QAFixtures.bootstrap(capabilities: QAFixtures.allCapabilities.replacingOccurrences(of: #""exercise_catalog":true"#, with: #""exercise_catalog":false"#))
        #expect(throws: AppFailure.self) { try SyncContract.verify(try QAFixtures.decode(BootstrapResponse.self, envelope: caps)) }
        let features = QAFixtures.negotiation(features: #"["offline","rpe"]"#)
        #expect(throws: AppFailure.self) { try SyncContract.verify(try QAFixtures.decode(NegotiationResponse.self, envelope: features)) }
    }

    @Test func negotiationOmitsAbsentBaseRevisionInsteadOfSendingNull() throws {
        let first = try JSONValue.parse(try APIClient.encode(NegotiationRequest.companion(baseRevision: nil)))
        #expect(first["base_revision"] == nil)
        #expect(first["features"] != nil)
        let renegotiation = try JSONValue.parse(try APIClient.encode(NegotiationRequest.companion(baseRevision: 3)))
        #expect(renegotiation["base_revision"] == .number("3"))
    }

    @Test func traditionalVolumeOnlyCountsComparableLoadModes() throws {
        let direct = try QAFixtures.decode(CompletedWorkoutDTO.self, QAFixtures.completed(weight: "40.5", reps: 8))
        #expect(direct.exercises[0].sets[0].traditionalVolume == Decimal(string: "324"))
        let assisted = try QAFixtures.decode(CompletedWorkoutDTO.self, QAFixtures.completed(loadMode: "bodyweight_assisted"))
        #expect(assisted.exercises[0].sets[0].traditionalVolume == nil)
    }

    @Test func ambientTriggersAreCoalescedWithinMinimumInterval() {
        #expect(shouldEnqueueSync(.foreground, lastAmbientAt: nil, now: 1, minimumInterval: 5))
        #expect(!shouldEnqueueSync(.connectivityRecovered, lastAmbientAt: 1, now: 4, minimumInterval: 5))
        #expect(shouldEnqueueSync(.connectivityRecovered, lastAmbientAt: 1, now: 6, minimumInterval: 5))
    }

    @Test func durableOperationTriggersAreNeverDroppedByAmbientThrottle() {
        #expect(shouldEnqueueSync(.pendingOperation, lastAmbientAt: 1, now: 1.001, minimumInterval: 5))
        #expect(shouldEnqueueSync(.downloadAck, lastAmbientAt: 1, now: 1.001, minimumInterval: 5))
    }
}

struct LocalStoreTests {
    let scope = "qa-scope"

    @Test func bootstrapStoresPlannedDeliveriesRecentAndCursor() async throws {
        let store = try LocalStore.make(inMemory: true)
        try await store.applyBootstrap(scope, try QAFixtures.decode(BootstrapResponse.self, envelope: QAFixtures.bootstrap()))
        #expect(await store.plannedWorkouts(scope).map(\.title) == ["Pierna QA"])
        #expect(await store.deliveryCount(scope) == 1)
        let recent = try #require(await store.recentSessions(scope).first)
        #expect(recent.totalLoadKg == "640")
        #expect(recent.setCount == 2 && recent.exerciseCount == 1)
        #expect(recent.summary == "Sentadilla QA")
        #expect(await store.syncCursor(scope) == "qa-cursor-0")
    }

    @Test func pullPageAppliesUpsertsDeletesAndAdvancesCursorAtomically() async throws {
        let store = try LocalStore.make(inMemory: true)
        try await store.applyBootstrap(scope, try QAFixtures.decode(BootstrapResponse.self, envelope: QAFixtures.bootstrap()))
        let page = try QAFixtures.decode(PullResponse.self, envelope: QAFixtures.pull([
            QAFixtures.change("planned_workout", id: "qa-planned-1", revision: 2, payload: QAFixtures.planned(title: "Pierna QA editada", revision: 2)),
            QAFixtures.change("planned_workout", id: "qa-planned-2", payload: QAFixtures.planned(id: "qa-planned-2", date: "2026-10-10", title: "Torso QA")),
            QAFixtures.change("completed_workout", id: "qa-completed-2", payload: QAFixtures.completed(id: "qa-completed-2")),
            QAFixtures.change("training_plan", id: "qa-plan", payload: #"{"ignored":true}"#),
        ], next: "qa-cursor-1"))
        try await store.applyPullPage(scope, page, deviceId: "qa-device")
        #expect(await store.plannedWorkouts(scope).map(\.title) == ["Pierna QA editada", "Torso QA"])
        #expect(await store.recentSessions(scope).count == 2)
        #expect(await store.syncCursor(scope) == "qa-cursor-1")

        let deletion = try QAFixtures.decode(PullResponse.self, envelope: QAFixtures.pull([
            QAFixtures.change("planned_workout", id: "qa-planned-2", operation: "delete", payload: nil),
        ], next: "qa-cursor-2"))
        try await store.applyPullPage(scope, deletion, deviceId: "qa-device")
        #expect(await store.plannedWorkouts(scope).map(\.id) == ["qa-planned-1"])
    }

    @Test func malformedPayloadRollsBackThePageAndKeepsTheCursor() async throws {
        let store = try LocalStore.make(inMemory: true)
        try await store.applyBootstrap(scope, try QAFixtures.decode(BootstrapResponse.self, envelope: QAFixtures.bootstrap()))
        let page = try QAFixtures.decode(PullResponse.self, envelope: QAFixtures.pull([
            QAFixtures.change("planned_workout", id: "qa-planned-3", payload: QAFixtures.planned(id: "qa-planned-3", title: "No debe quedar")),
            QAFixtures.change("companion_delivery", id: "bad", payload: #"{"id":"bad"}"#),
        ], next: "qa-cursor-bad"))
        await #expect(throws: AppFailure.self) { try await store.applyPullPage(scope, page, deviceId: "qa-device") }
        #expect(await store.syncCursor(scope) == "qa-cursor-0")
        #expect(!(await store.plannedWorkouts(scope).map(\.id).contains("qa-planned-3")))
    }

    @Test func queuedScheduleEditTurnsRemoteChangeIntoConflict() async throws {
        let store = try LocalStore.make(inMemory: true)
        try await store.applyBootstrap(scope, try QAFixtures.decode(BootstrapResponse.self, envelope: QAFixtures.bootstrap(
            planned: [QAFixtures.planned(status: "locally_pending")]
        )))
        try await store.enqueue(scope, actionType: "planning_schedule_patch", entityId: "qa-planned-1", idempotencyKey: "qa-key-1", payloadJSON: #"{"scheduled_for_date":"2026-10-11"}"#)
        let page = try QAFixtures.decode(PullResponse.self, envelope: QAFixtures.pull([
            QAFixtures.change("planned_workout", id: "qa-planned-1", revision: 3, payload: QAFixtures.planned(date: "2026-10-12", revision: 3)),
        ], next: "qa-cursor-1"))
        try await store.applyPullPage(scope, page, deviceId: "qa-device")
        let planned = try #require(await store.plannedWorkouts(scope).first)
        #expect(planned.status == "conflict")
        #expect(planned.scheduledForDate == "2026-10-09")
        #expect(await store.snapshot(scope).conflictCount == 1)
    }

    @Test func idempotentEnqueueAcceptsReplaysAndRejectsDifferentPayloads() async throws {
        let store = try LocalStore.make(inMemory: true)
        try await store.enqueue(scope, actionType: "qa_action", entityId: "e1", idempotencyKey: "k1", payloadJSON: #"{"a":1,"b":2}"#)
        try await store.enqueue(scope, actionType: "qa_action", entityId: "e1", idempotencyKey: "k1", payloadJSON: #"{"b":2,"a":1}"#)
        #expect(await store.snapshot(scope).pendingCount == 1)
        await #expect(throws: AppFailure.self) {
            try await store.enqueue(scope, actionType: "qa_action", entityId: "e1", idempotencyKey: "k1", payloadJSON: #"{"a":2}"#)
        }
    }

    @Test func clearingOneAccountLeavesOtherScopesUntouched() async throws {
        let store = try LocalStore.make(inMemory: true)
        let bootstrap = try QAFixtures.decode(BootstrapResponse.self, envelope: QAFixtures.bootstrap())
        try await store.applyBootstrap("scope-a", bootstrap)
        try await store.applyBootstrap("scope-b", bootstrap)
        try await store.enqueue("scope-a", actionType: "qa_action", entityId: "e", idempotencyKey: "k", payloadJSON: "{}")
        try await store.clearAccountData("scope-a")
        #expect(await store.plannedWorkouts("scope-a").isEmpty)
        #expect(await store.snapshot("scope-a") == SyncSnapshot(pendingCount: 0, conflictCount: 0, hasSyncState: false))
        #expect(await store.plannedWorkouts("scope-b").count == 1)
        #expect(await store.syncCursor("scope-b") == "qa-cursor-0")
    }
}

/// Records handled actions and fails on demand.
actor RecordingHandler: PendingActionHandler {
    var handled: [String] = []
    var failures: [String: AppFailure] = [:]

    func fail(_ entityId: String, with failure: AppFailure) { failures[entityId] = failure }

    nonisolated func handle(_ action: PendingAction, scope: String, api: APIClient, store: LocalStore) async throws {
        try await record(action.entityId)
    }

    private func record(_ entityId: String) throws {
        if let failure = failures[entityId] { throw failure }
        handled.append(entityId)
    }
}

final class Clock: @unchecked Sendable {
    private let lock = NSLock()
    private var current = Date(timeIntervalSince1970: 1_800_000_000)
    var now: Date { lock.withLock { current } }
    func advance(_ seconds: TimeInterval) { lock.withLock { current += seconds } }
}

struct SyncEngineTests {
    let scope = "qa-scope"

    private func makeEngine(_ h: Harness, clock: Clock = Clock()) -> SyncEngine {
        SyncEngine(api: h.api, store: h.store, preferences: h.preferences, now: { clock.now }, jitter: { _ in 0 })
    }

    private func scriptPull(_ h: Harness, pages: Int = 1, deviceId: String) {
        for index in 0..<pages {
            h.transport.on("GET", "/api/v1/sync/pull", json: QAFixtures.pull([], next: "qa-cursor-\(index + 1)", hasMore: index < pages - 1))
        }
        h.transport.on("GET", "/api/v1/sync/status", json: QAFixtures.status(deviceId: deviceId))
    }

    @Test func fullSyncDrainsQueueInOrderBootstrapsAndPullsAllPages() async throws {
        let h = try Harness()
        let outcome = try await h.login()
        let deviceId = h.preferences.values.deviceId
        let engine = makeEngine(h)
        let handler = RecordingHandler()
        await engine.register(handler, for: "qa_action")
        for index in 1...3 {
            try await h.store.enqueue(outcome.scope, actionType: "qa_action", entityId: "e\(index)", idempotencyKey: "k\(index)", payloadJSON: "{}")
        }
        scriptPull(h, pages: 3, deviceId: deviceId)

        try await engine.synchronize(scope: outcome.scope)

        #expect(await handler.handled == ["e1", "e2", "e3"])
        #expect(await h.store.snapshot(outcome.scope).pendingCount == 0)
        #expect(await h.store.syncCursor(outcome.scope) == "qa-cursor-3")
        #expect(h.transport.count("GET", "/api/v1/sync/pull") == 3)
        #expect(await engine.status == .idle)
        #expect(h.preferences.values.lastSyncAt != nil)
        let pullURL = try #require(h.transport.requests.first { $0.url?.path == "/api/v1/sync/pull" }?.url?.absoluteString)
        #expect(pullURL.contains("cursor=qa-cursor-0&limit=100"))
    }

    @Test func retryableFailureBacksOffAndBlocksLaterActions() async throws {
        let h = try Harness()
        let outcome = try await h.login()
        let clock = Clock()
        let engine = makeEngine(h, clock: clock)
        let handler = RecordingHandler()
        await handler.fail("e1", with: AppFailure(.serverError, "QA", retryable: true))
        await engine.register(handler, for: "qa_action")
        try await h.store.enqueue(outcome.scope, actionType: "qa_action", entityId: "e1", idempotencyKey: "k1", payloadJSON: "{}")
        try await h.store.enqueue(outcome.scope, actionType: "qa_action", entityId: "e2", idempotencyKey: "k2", payloadJSON: "{}")

        await #expect(throws: AppFailure.self) { try await engine.synchronize(scope: outcome.scope) }
        let head = try #require(await h.store.headOfQueue(outcome.scope))
        #expect(head.entityId == "e1" && head.attemptCount == 1 && head.lastErrorCode == "serverError")
        #expect(head.notBefore == clock.now.addingTimeInterval(30))
        #expect(await handler.handled.isEmpty)
        #expect(await engine.status == .pending)

        // Still backed off: nothing is attempted, the pull proceeds.
        scriptPull(h, deviceId: h.preferences.values.deviceId)
        try await engine.synchronize(scope: outcome.scope)
        #expect(await handler.handled.isEmpty)
        #expect(await engine.status == .pending)
    }

    @Test func nonRetryableFailureParksActionAsConflict() async throws {
        let h = try Harness()
        let outcome = try await h.login()
        let engine = makeEngine(h)
        let handler = RecordingHandler()
        await handler.fail("e1", with: AppFailure(.revisionConflict, "QA", retryable: false))
        await engine.register(handler, for: "qa_action")
        try await h.store.enqueue(outcome.scope, actionType: "qa_action", entityId: "e1", idempotencyKey: "k1", payloadJSON: "{}")
        try await h.store.enqueue(outcome.scope, actionType: "unknown_action", entityId: "e2", idempotencyKey: "k2", payloadJSON: "{}")

        await #expect(throws: AppFailure.self) { try await engine.synchronize(scope: outcome.scope) }
        #expect(await h.store.headOfQueue(outcome.scope)?.status == "conflict")
        #expect(await h.store.snapshot(outcome.scope).conflictCount == 1)
        #expect(await engine.status == .conflict)
    }

    @Test func unknownActionTypeIsParkedInsteadOfLoopingForever() async throws {
        let h = try Harness()
        let outcome = try await h.login()
        let engine = makeEngine(h)
        try await h.store.enqueue(outcome.scope, actionType: "future_action", entityId: "e1", idempotencyKey: "k1", payloadJSON: "{}")
        await #expect(throws: AppFailure.self) { try await engine.synchronize(scope: outcome.scope) }
        #expect(await h.store.headOfQueue(outcome.scope)?.lastErrorCode == "unsupported_action")
    }

    @Test func serverStateForAnotherDeviceIsRejected() async throws {
        let h = try Harness()
        let outcome = try await h.login()
        let engine = makeEngine(h)
        scriptPull(h, deviceId: "someone-else")
        await #expect(throws: AppFailure(.schemaIncompatible, "El estado de sync no corresponde a este dispositivo.", retryable: false)) {
            try await engine.synchronize(scope: outcome.scope)
        }
        #expect(await engine.status == .error)
    }

    @Test func missingCursorTriggersVerifiedBootstrap() async throws {
        let h = try Harness()
        let outcome = try await h.login()
        try await h.store.clearAccountData(outcome.scope)
        let engine = makeEngine(h)
        h.transport.on("GET", "/api/v1/sync/bootstrap", json: QAFixtures.bootstrap(cursor: "qa-cursor-fresh"))
        scriptPull(h, deviceId: h.preferences.values.deviceId)
        try await engine.synchronize(scope: outcome.scope)
        #expect(h.transport.count("GET", "/api/v1/sync/bootstrap") == 2)
        let pull = try #require(h.transport.requests.last { $0.url?.path == "/api/v1/sync/pull" }?.url?.absoluteString)
        #expect(pull.contains("cursor=qa-cursor-fresh"))
    }

    @Test func concurrentTriggersShareOneRun() async throws {
        let h = try Harness()
        let outcome = try await h.login()
        let engine = makeEngine(h)
        scriptPull(h, deviceId: h.preferences.values.deviceId)
        async let first: Void = engine.synchronize(scope: outcome.scope)
        async let second: Void = engine.synchronize(scope: outcome.scope)
        _ = try await (first, second)
        #expect(h.transport.count("GET", "/api/v1/sync/status") == 1)
    }

    @Test func backoffDoublesUpToSixHours() async throws {
        let h = try Harness()
        let engine = makeEngine(h)
        #expect(await engine.backoffMillis(attempt: 1) == 30_000)
        #expect(await engine.backoffMillis(attempt: 2) == 60_000)
        #expect(await engine.backoffMillis(attempt: 8) == 3_840_000)
        #expect(await engine.backoffMillis(attempt: 30) == 3_840_000)
    }
}

private extension Array {
    var single: Element? { count == 1 ? first : nil }
}
