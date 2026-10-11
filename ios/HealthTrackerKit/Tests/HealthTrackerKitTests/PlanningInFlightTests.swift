import Foundation
import SwiftData
import Testing
@testable import HealthTrackerKit

/// A deterministic suspension inside HTTPTransport.send; no timing sleeps or mocked LocalStore.
actor PlanningRequestGate: HTTPTransport {
    let inner: any HTTPTransport
    let method: String
    let path: String
    let loseFirstAcknowledgement: Bool
    private(set) var requests: [URLRequest] = []
    var held: URLRequest?
    private var reached: CheckedContinuation<URLRequest, Never>?
    private var release: CheckedContinuation<Void, Never>?
    private var used = false

    init(inner: any HTTPTransport, method: String, path: String, loseFirstAcknowledgement: Bool = false) {
        self.inner = inner; self.method = method; self.path = path
        self.loseFirstAcknowledgement = loseFirstAcknowledgement
    }

    func waitForRequest() async -> URLRequest {
        if let held { return held }
        return await withCheckedContinuation { reached = $0 }
    }

    func resume() { release?.resume(); release = nil }

    func send(_ request: URLRequest) async throws -> HTTPResult {
        requests.append(request)
        if !used, request.httpMethod == method, request.url?.path == path {
            used = true
            if loseFirstAcknowledgement { _ = try await inner.send(request) }
            held = request
            await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
                release = continuation
                reached?.resume(returning: request)
                reached = nil
            }
            if loseFirstAcknowledgement { throw URLError(.networkConnectionLost) }
        }
        return try await inner.send(request)
    }
}

@Suite(.timeLimit(.minutes(1)))
struct PlanningInFlightIntegrationTests {
    let scope = "fictional-queue-qa"

    private func seed(_ store: LocalStore, scope: String? = nil) async throws {
        try await store.applyPlan(scope ?? self.scope, QAFixtures.decode(MobilePlanDTO.self, TrainingFixtures.plan()))
    }

    private func claim(_ store: LocalStore, scope: String? = nil) async throws -> PendingAction {
        try #require(try await store.claimNextPending(scope ?? self.scope))
    }

    private func body(_ action: PendingAction) throws -> JSONValue { try JSONValue.parse(action.payloadJSON) }

    @Test func createClaimFreezesPayloadAndOldAckKeepsTwoLaterEdits() async throws {
        let store = try LocalStore.make(inMemory: true)
        try await store.createPlanOffline(scope, id: "p", key: "create", name: "Before QA", description: nil)
        let sent = try await claim(store)
        #expect(sent.status == "sending" && sent.attemptCount == 1)
        #expect(try await store.claimNextPending(scope) == nil)
        try await store.editPlanOffline(scope, publicId: "p", name: "After QA", description: nil, key: "edit")
        try await store.editPlanOffline(scope, publicId: "p", name: "After QA 2", description: "QA", key: "edit-2")
        #expect(await store.headOfQueue(scope)?.payloadJSON == sent.payloadJSON)
        #expect(await store.snapshot(scope).pendingCount == 2)
        try await store.completePending(sent, scope: scope)
        try await store.completePending(sent, scope: scope) // duplicate/old ACK cannot touch the tail
        let next = try #require(await store.headOfQueue(scope))
        #expect(next.idempotencyKey == "edit" && next.sequence > sent.sequence)
        #expect(try body(next)["base_revision"] == .number("1"))
        #expect(try body(next)["name"] == .string("After QA 2"))
        #expect(await store.plan(scope, publicId: "p")?.syncStatus == "pending")
        #expect(await store.plan(scope, publicId: "p")?.revision == 2)
        try await store.completePending(try await claim(store), scope: scope)
        #expect(await store.plan(scope, publicId: "p")?.syncStatus == "synced")
    }

    @Test func patchClaimCreatesANewRevisionAndAckNeverErasesNewName() async throws {
        let store = try LocalStore.make(inMemory: true)
        try await seed(store)
        try await store.editPlanOffline(scope, publicId: "qa-plan-1", name: "Before QA", description: nil, key: "patch")
        let sent = try await claim(store)
        try await store.editPlanOffline(scope, publicId: "qa-plan-1", name: "After QA", description: nil, key: "later")
        try await store.markPlanningSyncStatus(scope, action: sent, status: "synced")
        #expect(await store.plan(scope, publicId: "qa-plan-1")?.syncStatus == "pending")
        try await store.completePending(sent, scope: scope)
        let next = try #require(await store.headOfQueue(scope))
        #expect(try body(sent)["base_revision"] == .number("1"))
        #expect(try body(next)["base_revision"] == .number("2"))
        #expect(await store.plan(scope, publicId: "qa-plan-1")?.name == "After QA")
        #expect(await store.plan(scope, publicId: "qa-plan-1")?.revision == 3)
    }

    @Test func remoteRefreshCannotReplaceAClaimedLocalPlan() async throws {
        let store = try LocalStore.make(inMemory: true)
        try await seed(store)
        try await store.editPlanOffline(scope, publicId: "qa-plan-1", name: "Before QA", description: nil, key: "patch")
        let sent = try await claim(store)
        try await store.markPlanningSyncStatus(scope, action: sent, status: "syncing")
        let remote = try QAFixtures.decode(MobilePlanDTO.self, TrainingFixtures.plan(name: "Remote QA", revision: 1))
        #expect(try await !store.applyPlan(scope, remote))
        #expect(await store.plan(scope, publicId: "qa-plan-1")?.name == "Before QA")
    }

    @Test func retryAndReconnectionKeepTheClaimedRequestByteForByte() async throws {
        let store = try LocalStore.make(inMemory: true)
        try await store.createPlanOffline(scope, id: "p", key: "create", name: "Before QA", description: nil)
        let sent = try await claim(store)
        let later = Date().addingTimeInterval(60)
        try await store.reschedulePending(sent.key, errorCode: "networkError", notBefore: later)
        try await store.editPlanOffline(scope, publicId: "p", name: "After QA", description: nil, key: "later")
        #expect(try await store.claimNextPending(scope, now: later.addingTimeInterval(-1)) == nil)
        let retry = try #require(try await store.claimNextPending(scope, now: later))
        #expect(retry.payloadJSON == sent.payloadJSON && retry.idempotencyKey == sent.idempotencyKey)
        #expect(retry.attemptCount == 2)
        try await store.completePending(retry, scope: scope)
        #expect(await store.headOfQueue(scope)?.idempotencyKey == "later")
    }

    @Test func relaunchRecoversAClaimAndTheServerCommittedBeforeTheCrash() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("fictional-queue-qa-\(UUID())")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("queue.store")
        var first: LocalStore? = try LocalStore.make(url: url)
        try await first!.createPlanOffline(scope, id: "p", key: "create", name: "Before QA", description: nil)
        let sent = try await claim(first!)
        try await first!.editPlanOffline(scope, publicId: "p", name: "After QA", description: nil, key: "later")
        first = nil // durable disk rows, including the claim, survive opening a new ModelContainer
        let reopened = try LocalStore.make(url: url)
        let replay = try await claim(reopened)
        #expect(replay.payloadJSON == sent.payloadJSON && replay.idempotencyKey == sent.idempotencyKey)
        #expect(replay.attemptCount == 2)
        var server = QAPlanningLedger()
        try server.apply(sent) // server committed but the original process never persisted its ACK
        try server.apply(replay)
        #expect(server.creates == 1)
        try await reopened.completePending(replay, scope: scope)
        let edit = try await claim(reopened)
        try server.apply(edit)
        try await reopened.completePending(edit, scope: scope)
        #expect(server.names["p"] == "After QA")
        #expect(await reopened.plan(scope, publicId: "p")?.name == server.names["p"])
        #expect(await reopened.snapshot(scope).pendingCount == 0)
    }

    @Test func conflictReplacementPreservesLaterEditsAndRejectsOldAck() async throws {
        let store = try LocalStore.make(inMemory: true)
        try await seed(store)
        try await store.editPlanOffline(scope, publicId: "qa-plan-1", name: "Before QA", description: nil, key: "patch")
        let sent = try await claim(store)
        try await store.editPlanOffline(scope, publicId: "qa-plan-1", name: "After QA", description: nil, key: "later")
        try await store.markPendingConflict(sent.key, errorCode: "revisionConflict")
        #expect(try await store.claimNextPending(scope) == nil)
        try await store.rebaseConflict(scope, entityId: "qa-plan-1", remoteRevision: 5, newKey: "resolved")
        try await store.completePending(sent, scope: scope)
        let rebased = try await claim(store)
        #expect(rebased.idempotencyKey == "resolved")
        #expect(try body(rebased)["base_revision"] == .number("5"))
        try await store.completePending(rebased, scope: scope)
        let tail = try await claim(store)
        #expect(try body(tail)["base_revision"] == .number("6"))
        #expect(try body(tail)["name"] == .string("After QA"))
        #expect(await store.plan(scope, publicId: "qa-plan-1")?.revision == 7)
    }

    @Test func acceptingARemotePlanConflictKeepsUnrelatedWorkoutEdits() async throws {
        let store = try LocalStore.make(inMemory: true)
        try await seed(store)
        try await store.editPlanOffline(scope, publicId: "qa-plan-1", name: "Before QA", description: nil, key: "plan-patch")
        let sent = try await claim(store)
        try await store.saveWorkoutOffline(scope, workoutId: "qa-workout-1", name: "After QA", notes: nil, exercises: [], key: "workout-patch")
        try await store.markPendingConflict(sent.key, errorCode: "revisionConflict")
        try await store.acceptRemotePlan(scope, entityId: "qa-plan-1", remote: QAFixtures.decode(MobilePlanDTO.self, TrainingFixtures.plan(name: "Remote QA", revision: 5)))
        #expect(await store.plan(scope, publicId: "qa-plan-1")?.name == "Remote QA")
        #expect(await store.plan(scope, publicId: "qa-plan-1")?.syncStatus == "pending")
        #expect(await store.planWorkout(scope, publicId: "qa-workout-1")?.name == "After QA")
        #expect(await store.plan(scope, publicId: "qa-plan-1")?.revision == 6)
        #expect(await store.planWorkout(scope, publicId: "qa-workout-1")?.syncStatus == "pending")
        #expect(await store.headOfQueue(scope)?.idempotencyKey == "workout-patch")
        try await store.completePending(sent, scope: scope)
        #expect(await store.snapshot(scope).pendingCount == 1)
    }

    @Test func workoutCreateAndPatchClaimsPreservePrescriptionAndExerciseOrder() async throws {
        let store = try LocalStore.make(inMemory: true)
        try await seed(store)
        try await store.createWorkoutOffline(scope, planId: "qa-plan-1", workoutId: "w", key: "create", name: "Before QA")
        let create = try await claim(store)
        let exercises = [
            PlanExercise(id: "b", exerciseId: "cat-b", name: "Remo QA", notes: nil, exerciseOrder: 1, sets: []),
            PlanExercise(id: "a", exerciseId: "cat-a", name: "Press QA", notes: nil, exerciseOrder: 2, sets: []),
        ]
        try await store.saveWorkoutOffline(scope, workoutId: "w", name: "After QA", notes: nil, exercises: exercises, key: "edit")
        #expect(await store.headOfQueue(scope)?.payloadJSON == create.payloadJSON)
        try await store.completePending(create, scope: scope)
        #expect(await store.planWorkout(scope, publicId: "w")?.syncStatus == "pending")
        #expect(await store.plan(scope, publicId: "qa-plan-1")?.syncStatus == "pending")
        let patch = try await claim(store)
        try await store.saveWorkoutOffline(scope, workoutId: "w", name: "After QA 2", notes: nil, exercises: Array(exercises.reversed()), key: "reorder")
        try await store.completePending(patch, scope: scope)
        let reorder = try await claim(store)
        #expect(try body(reorder)["base_revision"] == .number("2"))
        #expect(await store.planWorkout(scope, publicId: "w")?.exercises.map(\.id) == ["a", "b"])
        try await store.completePending(reorder, scope: scope)
        #expect(await store.plan(scope, publicId: "qa-plan-1")?.syncStatus == "synced")
    }

    @Test func reorderThenRenameKeepsOrderAndDoesNotCrossRevisionDependencies() async throws {
        let store = try LocalStore.make(inMemory: true)
        try await seed(store)
        try await store.reorderWorkoutsOffline(scope, planId: "qa-plan-1", orderedIds: ["qa-workout-1"], key: "order")
        try await store.editPlanOffline(scope, publicId: "qa-plan-1", name: "After QA", description: nil, key: "rename")
        let sent = try await claim(store)
        #expect(try body(sent)["workout_order"] == .array([.string("qa-workout-1")]))
        #expect(try body(sent)["name"] == .string("After QA"))
        try await store.createWorkoutOffline(scope, planId: "qa-plan-1", workoutId: "w", key: "w-create", name: "Día QA")
        try await store.editPlanOffline(scope, publicId: "qa-plan-1", name: "Later QA", description: nil, key: "later")
        try await store.completePending(sent, scope: scope)
        #expect(await store.plan(scope, publicId: "qa-plan-1")?.syncStatus == "pending")
        #expect(await store.planWorkout(scope, publicId: "qa-workout-1")?.syncStatus == "synced")
        let workout = try await claim(store)
        #expect(try body(workout)["base_revision"] == .number("2"))
        try await store.completePending(workout, scope: scope)
        #expect(try body(try await claim(store))["base_revision"] == .number("3"))
    }

    @Test func scheduleAndRescheduleAcksKeepLaterDatesAndCancellation() async throws {
        let store = try LocalStore.make(inMemory: true)
        try await seed(store)
        try await store.scheduleWorkoutOffline(scope, workoutId: "qa-workout-1", date: "2026-10-20", timezone: "UTC", id: "s", key: "schedule")
        let sent = try await claim(store)
        try await store.rescheduleWorkoutOffline(scope, scheduledId: "s", date: "2026-10-21", timezone: "UTC", key: "patch")
        try await store.applyScheduleResult(scope, action: sent, date: "2026-10-20", timezone: "UTC", status: "planned", revision: 1)
        try await store.completePending(sent, scope: scope)
        #expect(await store.plannedWorkout(scope, id: "s")?.scheduledForDate == "2026-10-21")
        #expect(await store.plannedWorkout(scope, id: "s")?.status == "locally_pending")
        let patch = try await claim(store)
        try await store.rescheduleWorkoutOffline(scope, scheduledId: "s", date: "2026-10-22", timezone: "UTC", key: "patch-2")
        try await store.cancelScheduleOffline(scope, scheduledId: "s", key: "cancel")
        try await store.applyScheduleResult(scope, action: patch, date: "2026-10-21", timezone: "UTC", status: "planned", revision: 2)
        try await store.completePending(patch, scope: scope)
        #expect(await store.plannedWorkout(scope, id: "s")?.status == "cancelled")
        let cancel = try await claim(store)
        #expect(cancel.actionType == "planning_cancel_schedule")
        #expect(try body(cancel)["base_revision"] == .number("2"))
        try await store.deletePlanned(scope, action: cancel)
        try await store.completePending(cancel, scope: scope)
        #expect(await store.plannedWorkout(scope, id: "s") == nil)
    }

    @Test func threeRescheduleClaimsHaveSequentialRevisions() async throws {
        let store = try LocalStore.make(inMemory: true)
        try await store.applyBootstrap(scope, QAFixtures.decode(BootstrapResponse.self, envelope: QAFixtures.bootstrap()))
        for (index, date) in ["2026-10-21", "2026-10-22", "2026-10-23"].enumerated() {
            try await store.rescheduleWorkoutOffline(scope, scheduledId: "qa-planned-1", date: date, timezone: "UTC", key: "patch-\(index)")
            let sent = try await claim(store)
            #expect(try body(sent)["base_revision"] == .number(String(index + 1)))
            try await store.applyScheduleResult(scope, action: sent, date: date, timezone: "UTC", status: "planned", revision: index + 2)
            try await store.completePending(sent, scope: scope)
        }
        #expect(await store.plannedWorkout(scope, id: "qa-planned-1")?.revision == 4)
    }

    @Test func remoteDeletionKeepsAQueuedScheduleEditAsAVisibleConflict() async throws {
        let store = try LocalStore.make(inMemory: true)
        try await store.applyBootstrap(scope, QAFixtures.decode(BootstrapResponse.self, envelope: QAFixtures.bootstrap()))
        try await store.rescheduleWorkoutOffline(scope, scheduledId: "qa-planned-1", date: "2026-10-21", timezone: "UTC", key: "patch")
        let sent = try await claim(store)
        let page = try QAFixtures.decode(PullResponse.self, envelope: QAFixtures.pull([
            QAFixtures.change("planned_workout", id: "qa-planned-1", operation: "delete", revision: 3, payload: nil),
        ], next: "after-delete"))
        try await store.applyPullPage(scope, page, deviceId: "qa-device")
        #expect(await store.plannedWorkout(scope, id: "qa-planned-1")?.scheduledForDate == "2026-10-21")
        #expect(await store.plannedWorkout(scope, id: "qa-planned-1")?.status == "conflict")
        #expect(await store.headOfQueue(scope)?.payloadJSON == sent.payloadJSON)
        #expect(await store.planningConflict(scope, entityId: "qa-planned-1")?.changedFields == "remote_deleted")
    }

    @Test func multipleEntitiesAndIdenticalKeysAreIsolatedAcrossUsersAndServers() async throws {
        let store = try LocalStore.make(inMemory: true)
        let scopes = [CanonicalJSON.accountScope(serverURL: "https://qa-a.invalid", userPublicId: "qa-1"),
                      CanonicalJSON.accountScope(serverURL: "https://qa-a.invalid", userPublicId: "qa-2"),
                      CanonicalJSON.accountScope(serverURL: "https://qa-b.invalid", userPublicId: "qa-1")]
        for s in scopes { try await store.createPlanOffline(s, id: "p", key: "create", name: "Before QA", description: nil) }
        let sent = try await claim(store, scope: scopes[0])
        try await store.editPlanOffline(scopes[0], publicId: "p", name: "After QA", description: nil, key: "later")
        try await store.createPlanOffline(scopes[0], id: "p2", key: "second", name: "Second QA", description: nil)
        try await store.completePending(sent, scope: scopes[1]) // an ACK from another scope has no authority
        #expect(await store.snapshot(scopes[1]).pendingCount == 1)
        try await store.completePending(sent, scope: scopes[0])
        #expect(await store.snapshot(scopes[0]).pendingCount == 2)
        #expect(await store.plan(scopes[1], publicId: "p")?.name == "Before QA")
        #expect(await store.plan(scopes[2], publicId: "p")?.name == "Before QA")
        try await store.completePending(try await claim(store, scope: scopes[0]), scope: scopes[0])
        #expect(await store.headOfQueue(scopes[0])?.entityId == "p2")
    }

    @Test(arguments: ["POST", "PATCH"])
    func actualEngineSuspendsInHTTPAndConvergesAfterTwoEdits(method: String) async throws {
        let h = try Harness()
        let account = try await h.login().scope
        let path = method == "POST" ? "/api/v1/mobile/plans" : "/api/v1/mobile/plans/qa-plan-1"
        let id = method == "POST" ? "p" : "qa-plan-1"
        if method == "POST" {
            try await h.store.createPlanOffline(account, id: id, key: "first", name: "Before QA", description: nil)
        } else {
            try await seed(h.store, scope: account)
            try await h.store.editPlanOffline(account, publicId: id, name: "Before QA", description: nil, key: "first")
        }
        h.transport.on(method, path, status: method == "POST" ? 201 : 200, json: #"{"data":{"revision":1}}"#)
        h.transport.on("PATCH", "/api/v1/mobile/plans/\(id)", json: #"{"data":{"revision":2}}"#)
        h.transport.on("GET", "/api/v1/sync/pull", json: QAFixtures.pull([], next: "c1"))
        h.transport.on("GET", "/api/v1/sync/status", json: QAFixtures.status(deviceId: h.preferences.values.deviceId))
        let gate = PlanningRequestGate(inner: h.transport, method: method, path: path)
        let api = APIClient(preferences: h.preferences, tokens: h.tokens, transport: gate)
        let engine = SyncEngine(api: api, store: h.store, preferences: h.preferences, handlers: PlanningHandlers.all)
        let syncing = Task { try await engine.synchronize(scope: account) }
        let original = await gate.waitForRequest()
        #expect(try JSONValue.parse(try #require(original.httpBody))["name"] == .string("Before QA"))
        try await h.store.editPlanOffline(account, publicId: id, name: "After QA", description: nil, key: "later")
        try await h.store.editPlanOffline(account, publicId: id, name: "After QA 2", description: nil, key: "later-2")
        await gate.resume()
        try await syncing.value
        let mutations = h.transport.requests.filter { $0.httpMethod == "POST" && $0.url?.path == path || $0.httpMethod == "PATCH" && $0.url?.path == "/api/v1/mobile/plans/\(id)" }
        #expect(mutations.count == 2)
        #expect(try JSONValue.parse(try #require(mutations.last?.httpBody))["name"] == .string("After QA 2"))
        #expect(await h.store.plan(account, publicId: id)?.name == "After QA 2")
        #expect(await h.store.plan(account, publicId: id)?.syncStatus == "synced")
        #expect(await h.store.snapshot(account).pendingCount == 0)
    }

    @Test(arguments: [503, 409])
    func HTTPFailureDuringAnEditPreservesTheFrozenHeadAndItsTail(status: Int) async throws {
        let h = try Harness()
        let account = try await h.login().scope
        try await seed(h.store, scope: account)
        try await h.store.editPlanOffline(account, publicId: "qa-plan-1", name: "Before QA", description: nil, key: "first")
        let path = "/api/v1/mobile/plans/qa-plan-1"
        let error = status == 503 ? "server_error" : "revision_conflict"
        h.transport.on("PATCH", path, status: status, json: #"{"error":{"code":"\#(error)","message":"Fictional QA"}}"#)
        if status == 409 {
            h.transport.on("GET", path, json: #"{"data":\#(TrainingFixtures.plan(name: "Remote QA", revision: 5, withWorkouts: false))}"#)
        }
        let gate = PlanningRequestGate(inner: h.transport, method: "PATCH", path: path)
        let api = APIClient(preferences: h.preferences, tokens: h.tokens, transport: gate)
        let clock = Clock()
        let engine = SyncEngine(api: api, store: h.store, preferences: h.preferences, handlers: PlanningHandlers.all,
                                now: { clock.now }, jitter: { _ in 0 })
        let run = Task { try await engine.synchronize(scope: account) }
        let request = await gate.waitForRequest()
        try await h.store.editPlanOffline(account, publicId: "qa-plan-1", name: "After QA", description: nil, key: "later")
        await gate.resume()
        await #expect(throws: AppFailure.self) { try await run.value }
        #expect(await h.store.snapshot(account).pendingCount == 2)
        #expect(await h.store.plan(account, publicId: "qa-plan-1")?.name == "After QA")
        if status == 409 {
            #expect(await h.store.headOfQueue(account)?.status == "conflict")
            try await h.store.rebaseConflict(account, entityId: "qa-plan-1", remoteRevision: 5, newKey: "resolved")
        } else {
            #expect(await h.store.headOfQueue(account)?.status == "pending")
            clock.advance(31)
        }
        h.transport.on("PATCH", path, json: #"{"data":{"revision":2}}"#)
        h.transport.on("PATCH", path, json: #"{"data":{"revision":3}}"#)
        h.transport.on("GET", "/api/v1/sync/pull", json: QAFixtures.pull([], next: "done"))
        h.transport.on("GET", "/api/v1/sync/status", json: QAFixtures.status(deviceId: h.preferences.values.deviceId))
        try await engine.synchronize(scope: account)
        let sent = h.transport.requests.filter { $0.httpMethod == "PATCH" && $0.url?.path == path }
        #expect(sent.count == 3)
        if status == 503 {
            #expect(sent[1].httpBody == request.httpBody)
            #expect(sent[1].value(forHTTPHeaderField: "Idempotency-Key") == request.value(forHTTPHeaderField: "Idempotency-Key"))
        } else {
            #expect(try JSONValue.parse(try #require(sent[1].httpBody))["base_revision"] == .number("5"))
            #expect(try JSONValue.parse(try #require(sent[2].httpBody))["base_revision"] == .number("6"))
        }
        #expect(try JSONValue.parse(try #require(sent[2].httpBody))["name"] == .string("After QA"))
        #expect(await h.store.snapshot(account).pendingCount == 0)
        #expect(await h.store.plan(account, publicId: "qa-plan-1")?.syncStatus == "synced")
    }
}

/// Fictional idempotent server ledger for the disk recovery test. Strict revision checks expose
/// duplicated creations, changed retries or an incorrectly based follow-up, rather than accepting them.
private struct QAPlanningLedger {
    var names: [String: String] = [:]
    var revisions: [String: Int] = [:]
    var requests: [String: String] = [:]
    var creates = 0

    mutating func apply(_ action: PendingAction) throws {
        if let original = requests[action.idempotencyKey] {
            #expect(original == action.payloadJSON)
            return
        }
        let body = try JSONValue.parse(action.payloadJSON)
        if action.actionType == "planning_plan_create" {
            #expect(names[action.entityId] == nil)
            revisions[action.entityId] = 1
            creates += 1
        } else {
            #expect(body["base_revision"]?.intValue == revisions[action.entityId])
            revisions[action.entityId, default: 0] += 1
        }
        names[action.entityId] = body["name"]?.stringValue
        requests[action.idempotencyKey] = action.payloadJSON
    }
}
