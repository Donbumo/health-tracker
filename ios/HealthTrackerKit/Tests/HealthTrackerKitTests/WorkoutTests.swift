import Foundation
import Testing
@testable import HealthTrackerKit

/// Fictional QA companion payloads.
enum WorkoutFixtures {
    static let plannedId = "qa-planned-1"
    static let deliveryId = "qa-delivery-9"

    /// Package `data` with a correct `package_hash`.
    static func package(revision: Int = 1, expiresAt: String? = "2099-01-01T00:00:00Z", tamper: Bool = false) throws -> (json: String, hash: String) {
        let body = #"{"schema_version":"1.0","package_id":"qa-package-\#(revision)","planned_workout_id":"\#(plannedId)","plan_id":"qa-plan","plan_version_id":"qa-plan-v1","title":"Pierna QA","scheduled_for_date":"2026-10-09","timezone":"UTC","revision":\#(revision),"generated_at":"2026-10-09T00:00:00Z","expires_at":\#(expiresAt.map { "\"\($0)\"" } ?? "null"),"exercises":[{"exercise_order":1,"name":"Sentadilla QA","notes":null,"sets":[{"set_number":1,"reps":8,"weight_kg":"60.00","rest_seconds":90},{"set_number":2,"reps_min":6,"reps_max":8,"weight_kg":"60.00"}]},{"exercise_order":2,"name":"Zancada QA","sets":[{"set_number":1,"reps":10}]}],"supported_metrics":["reps"],"unsupported_fields":[],"server_capabilities":{},"device_capabilities":{},"compatibility_warnings":[]}"#
        let value = try JSONValue.parse(body)
        let hash = CanonicalJSON.sha256(value)
        guard case var .object(members) = value else { fatalError() }
        members.append(("package_hash", .string(tamper ? String(repeating: "0", count: 64) : hash)))
        return (JSONValue.object(members).encoded(), hash)
    }

    static func delivery(status: String = "available", revision: Int = 1, hash: String, deviceId: String = "qa-device") -> String {
        #"{"schema_version":"1.0","id":"\#(deliveryId)","device_id":"\#(deviceId)","profile_id":"qa-profile","planned_workout_id":"\#(plannedId)","package_schema_version":"1.0","package_hash":"\#(hash)","status":"\#(status)","revision":\#(revision),"last_client_sequence":0,"created_at":"2026-10-09T00:00:00Z","updated_at":"2026-10-09T00:00:00Z"}"#
    }

    static func completion(hash: String, eventId: String) -> String {
        #"{"data":{"delivery":\#(delivery(status: "completed", revision: 4, hash: hash)),"completed_workout":{"schema_version":"1.0","id":"qa-session-server","client_event_id":"\#(eventId)","planned_workout_id":"\#(plannedId)","started_at":"2026-10-09T12:00:00Z","completed_at":"2026-10-09T12:40:00Z","timezone":"UTC","duration_seconds":2400,"exercises":[{"exercise_order":1,"planned_exercise_order":1,"name":"Sentadilla QA","sets":[{"set_number":1,"planned_set_number":1,"weight_kg":62.5,"reps":8,"rir":2}]}]},"duplicate":false}}"#
    }
}

/// Deterministic ids for queue assertions.
final class IdSequence: @unchecked Sendable {
    private let lock = NSLock()
    private var value = 0
    func next() -> String { lock.withLock { value += 1; return "00000000-0000-4000-8000-\(String(format: "%012d", value))" } }
}

struct WorkoutFlowTests {
    struct Setup {
        let h: Harness
        let scope: String
        let deviceId: String
        let repo: WorkoutRepository
        let hash: String
    }

    private func setup(ackStatus: Int = 200) async throws -> Setup {
        let h = try Harness()
        let scope = try await h.login().scope
        let (packageJSON, hash) = try WorkoutFixtures.package()
        h.transport.on("POST", "/api/v1/companion/deliveries", json: #"{"data":\#(WorkoutFixtures.delivery(hash: hash))}"#)
        h.transport.on("GET", "/api/v1/companion/deliveries/\(WorkoutFixtures.deliveryId)/package", json: #"{"data":\#(packageJSON)}"#)
        if ackStatus == 200 {
            h.transport.on("POST", "/api/v1/companion/deliveries/\(WorkoutFixtures.deliveryId)/ack", json: #"{"data":\#(WorkoutFixtures.delivery(status: "acknowledged", revision: 2, hash: hash))}"#)
        } else {
            h.transport.on("POST", "/api/v1/companion/deliveries/\(WorkoutFixtures.deliveryId)/ack", status: ackStatus, json: #"{"error":{"code":"server_error","message":"x"}}"#)
        }
        let ids = IdSequence()
        let repo = WorkoutRepository(api: h.api, store: h.store, newId: { ids.next() })
        return Setup(h: h, scope: scope, deviceId: h.preferences.values.deviceId, repo: repo, hash: hash)
    }

    @Test func downloadVerifiesStoresAndAcknowledgesThenReusesTheDownload() async throws {
        let s = try await setup()
        let deliveryId = try await s.repo.downloadWorkout(scope: s.scope, plannedId: WorkoutFixtures.plannedId)
        #expect(deliveryId == WorkoutFixtures.deliveryId)
        #expect(await s.h.store.delivery(s.scope, id: deliveryId)?.status == "acknowledged")
        let package = try #require(await s.h.store.packageForPlanned(s.scope, plannedId: WorkoutFixtures.plannedId))
        #expect(package.packageHash == s.hash)
        let exercises = await s.h.store.packageExercises(s.scope, packageId: package.packageId)
        #expect(exercises.map(\.name) == ["Sentadilla QA", "Zancada QA"])
        #expect(exercises[0].sets.map(\.setNumber) == [1, 2])
        #expect(exercises[0].sets[1].repsMin == 6)
        // Second download of the same revision makes no request.
        #expect(try await s.repo.downloadWorkout(scope: s.scope, plannedId: WorkoutFixtures.plannedId) == deliveryId)
        #expect(s.h.transport.count("POST", "/api/v1/companion/deliveries") == 1)
        let ack = try #require(s.h.transport.requests.last { $0.url?.path.hasSuffix("/ack") == true })
        let body = try JSONValue.parse(try #require(ack.httpBody))
        #expect(body["package_hash"] == .string(s.hash))
        #expect(body["reason_code"] == nil)
    }

    @Test func retryableAckFailureKeepsThePackageAndQueuesTheAck() async throws {
        let s = try await setup(ackStatus: 503)
        let deliveryId = try await s.repo.downloadWorkout(scope: s.scope, plannedId: WorkoutFixtures.plannedId)
        #expect(await s.h.store.delivery(s.scope, id: deliveryId)?.status == "acknowledged_pending")
        #expect(await s.h.store.headOfQueue(s.scope)?.actionType == "companion_ack")
    }

    @Test func tamperedPackageIsRejectedBeforeStoring() async throws {
        let h = try Harness()
        let scope = try await h.login().scope
        let (packageJSON, hash) = try WorkoutFixtures.package(tamper: true)
        h.transport.on("POST", "/api/v1/companion/deliveries", json: #"{"data":\#(WorkoutFixtures.delivery(hash: hash))}"#)
        h.transport.on("GET", "/api/v1/companion/deliveries/\(WorkoutFixtures.deliveryId)/package", json: #"{"data":\#(packageJSON)}"#)
        let repo = WorkoutRepository(api: h.api, store: h.store)
        await #expect(throws: AppFailure.self) { try await repo.downloadWorkout(scope: scope, plannedId: WorkoutFixtures.plannedId) }
        #expect(await h.store.packages(scope).isEmpty)
    }

    @Test func fullCaptureQueuesStartProgressAndCompletionInOrder() async throws {
        let s = try await setup()
        let deliveryId = try await s.repo.downloadWorkout(scope: s.scope, plannedId: WorkoutFixtures.plannedId)
        let draft = try await s.repo.startWorkout(scope: s.scope, deliveryId: deliveryId, deviceId: s.deviceId)
        #expect(draft.status == "active")
        #expect(await s.h.store.delivery(s.scope, id: deliveryId)?.status == "started_pending")
        var sets = await s.h.store.draftSets(s.scope, deliveryId: deliveryId)
        #expect(sets.count == 3)
        #expect(sets[0].weightKg == "60.00" && sets[1].reps == 6)
        // Starting again recovers the same draft.
        #expect(try await s.repo.startWorkout(scope: s.scope, deliveryId: deliveryId, deviceId: s.deviceId).clientEventId == draft.clientEventId)

        let preview = try LoadCalculator.calculate(mode: .barPlusPerSide, displayUnit: "kg",
                                                   components: ["bar": ComponentInput(20, "kg"), "per_side": ComponentInput(Decimal(string: "21.25")!, "kg")])
        sets[0].weightKg = preview.weightKg
        sets[0].loadDetailsJSON = preview.details.encoded()
        sets[0].rir = "2"
        try await s.repo.saveSet(scope: s.scope, sets[0])
        #expect(await s.h.store.draft(s.scope, deliveryId: deliveryId)?.status == "saved")
        #expect(try await s.repo.checkpointSet(scope: s.scope, sets[0]))
        #expect(try await !s.repo.checkpointSet(scope: s.scope, sets[0])) // already checkpointed: saved only
        try await s.repo.duplicateSet(scope: s.scope, sets[0])
        #expect(await s.h.store.draftSets(s.scope, deliveryId: deliveryId).filter { $0.exerciseOrder == 1 }.map(\.setNumber) == [1, 2, 3])
        #expect(try await s.repo.pauseOrResume(scope: s.scope, deliveryId: deliveryId, pause: true))
        #expect(try await !s.repo.pauseOrResume(scope: s.scope, deliveryId: deliveryId, pause: true))
        #expect(try await s.repo.pauseOrResume(scope: s.scope, deliveryId: deliveryId, pause: false))
        try await s.repo.updateSummary(scope: s.scope, deliveryId: deliveryId, heartRate: 130, calories: "250.5", notes: "Nota QA")
        await #expect(throws: AppFailure.self) { try await s.repo.updateSummary(scope: s.scope, deliveryId: deliveryId, heartRate: 300, calories: nil, notes: nil) }

        #expect(try await s.repo.completeWorkout(scope: s.scope, deliveryId: deliveryId))
        #expect(try await !s.repo.completeWorkout(scope: s.scope, deliveryId: deliveryId))
        #expect(await s.h.store.draft(s.scope, deliveryId: deliveryId)?.status == "completion_pending")
        #expect(await s.h.store.plannedWorkout(s.scope, id: WorkoutFixtures.plannedId)?.status == "completed")
        let local = await s.h.store.history(s.scope, cacheKey: HistoryFilters().cacheKey).first
        #expect(local?.syncStatus == "pending" && local?.name == "Pierna QA" && local?.setCount == 1)
        // A locked draft rejects further edits silently.
        try await s.repo.saveSet(scope: s.scope, sets[1])
        #expect(await s.h.store.draftSets(s.scope, deliveryId: deliveryId)[1].completed == false)

        // Queue order and payloads.
        var types: [String] = []
        var payloads: [JSONValue] = []
        while let head = await s.h.store.headOfQueue(s.scope) {
            types.append(head.actionType)
            payloads.append(try JSONValue.parse(head.payloadJSON))
            try await s.h.store.completePending(head.key)
        }
        #expect(types == ["companion_start", "companion_progress", "companion_progress", "companion_progress", "companion_complete"])
        #expect(payloads[0]["base_revision"] == .number("2"))
        #expect(payloads[1]["event_type"] == .string("set_completed"))
        #expect(payloads[1]["payload"]?["weight_kg"] == .number("62.50"))
        #expect(payloads[1]["client_sequence"] == .number("1"))
        #expect(payloads[2]["event_type"] == .string("paused") && payloads[3]["client_sequence"] == .number("3"))
        let result = try #require(payloads[4]["result"])
        #expect(payloads[4]["base_revision"] == .number("3"))
        #expect(result["calories_burned"] == .number("250.5") && result["average_heart_rate_bpm"] == .number("130"))
        let completedSet = try #require(result["exercises"].flatMap { if case let .array(items) = $0 { items.first } else { nil } }?["sets"])
        guard case let .array(completedSets) = completedSet else { Issue.record("sets"); return }
        #expect(completedSets.count == 1)
        #expect(completedSets[0]["weight_kg"] == .number("62.50"))
        #expect(completedSets[0]["load_details"]?.sortedKeys() == preview.details.sortedKeys())
        #expect(completedSets[0]["rir"] == .number("2"))
    }

    @Test func completeRequiresACompletedSetAndAbortLocksTheDraft() async throws {
        let s = try await setup()
        let deliveryId = try await s.repo.downloadWorkout(scope: s.scope, plannedId: WorkoutFixtures.plannedId)
        _ = try await s.repo.startWorkout(scope: s.scope, deliveryId: deliveryId, deviceId: s.deviceId)
        await #expect(throws: AppFailure.self) { try await s.repo.completeWorkout(scope: s.scope, deliveryId: deliveryId) }
        #expect(try await s.repo.abortWorkout(scope: s.scope, deliveryId: deliveryId))
        #expect(try await !s.repo.abortWorkout(scope: s.scope, deliveryId: deliveryId))
        #expect(await s.h.store.draft(s.scope, deliveryId: deliveryId)?.status == "aborted_pending")
        await #expect(throws: AppFailure.self) { try await s.repo.completeWorkout(scope: s.scope, deliveryId: deliveryId) }
    }

    @Test func invalidMetricsAreRejected() async throws {
        let set = DraftSet(deliveryId: "d", exerciseOrder: 1, setNumber: 1, plannedSetNumber: 1, reps: 0, weightKg: "10")
        #expect(throws: AppFailure.self) { try DraftRules.validate(set, requireCompletedMetrics: true) }
        try DraftRules.validate(set, requireCompletedMetrics: false)
        var bad = set
        bad.reps = 5
        bad.rpe = "0.5"
        #expect(throws: AppFailure.self) { try DraftRules.validate(bad, requireCompletedMetrics: true) }
        bad.rpe = nil
        bad.weightKg = "2000.5"
        #expect(throws: AppFailure.self) { try DraftRules.validate(bad, requireCompletedMetrics: true) }
    }

    @Test func tamperedOrForeignDraftsAreIsolatedAndOnlyThenDiscardable() async throws {
        let s = try await setup()
        let deliveryId = try await s.repo.downloadWorkout(scope: s.scope, plannedId: WorkoutFixtures.plannedId)
        _ = try await s.repo.startWorkout(scope: s.scope, deliveryId: deliveryId, deviceId: s.deviceId)
        await #expect(throws: AppFailure.self) { try await s.repo.discardCorruptDraft(scope: s.scope, deliveryId: deliveryId) }
        // Another device id must never resume this draft.
        let foreign = try await s.h.store.validateDraft(s.scope, deliveryId: deliveryId, currentScope: s.scope, deviceId: "other-device")
        #expect(foreign?.status == "corrupt" && foreign?.corruptReasonCode == "draft_device_mismatch")
        #expect(DisplayText.draftIsolationReason(foreign?.corruptReasonCode) == "El borrador pertenece a otro dispositivo")
        // Valid again on the right device: restored.
        #expect(try await s.h.store.validateDraft(s.scope, deliveryId: deliveryId, currentScope: s.scope, deviceId: s.deviceId)?.status == "active")
        // A content change that bypasses the store breaks the integrity hash.
        try await s.h.store.tamperDraftSetForTesting(s.scope, deliveryId: deliveryId)
        let tampered = try await s.h.store.validateDraft(s.scope, deliveryId: deliveryId, currentScope: s.scope, deviceId: s.deviceId)
        #expect(tampered?.corruptReasonCode == "draft_payload_hash_mismatch")
        await #expect(throws: AppFailure.self) { try await s.repo.startWorkout(scope: s.scope, deliveryId: deliveryId, deviceId: s.deviceId) }
        try await s.repo.discardCorruptDraft(scope: s.scope, deliveryId: deliveryId)
        #expect(await s.h.store.draft(s.scope, deliveryId: deliveryId) == nil)
        #expect(await s.h.store.headOfQueue(s.scope) == nil)
    }

    @Test func newerRevisionNeverReplacesAnActiveDraftPackage() async throws {
        let s = try await setup()
        let deliveryId = try await s.repo.downloadWorkout(scope: s.scope, plannedId: WorkoutFixtures.plannedId)
        _ = try await s.repo.startWorkout(scope: s.scope, deliveryId: deliveryId, deviceId: s.deviceId)
        let page = try QAFixtures.decode(PullResponse.self, envelope: QAFixtures.pull([
            QAFixtures.change("planned_workout", id: WorkoutFixtures.plannedId, revision: 2, payload: QAFixtures.planned(title: "Pierna QA v2", revision: 2)),
        ], next: "c2"))
        try await s.h.store.applyPullPage(s.scope, page, deviceId: s.deviceId)
        await #expect(throws: AppFailure.self) { try await s.repo.downloadWorkout(scope: s.scope, plannedId: WorkoutFixtures.plannedId) }
        #expect(await s.h.store.plannedWorkout(s.scope, id: WorkoutFixtures.plannedId)?.status == "conflict")
        #expect(await s.h.store.snapshot(s.scope).conflictCount == 1)
        #expect(await s.h.store.packageForDelivery(s.scope, deliveryId: deliveryId)?.revision == 1)
    }
}

struct CompanionHandlerTests {
    @Test func queueDrainSendsStartProgressAndCompletionAndReplacesLocalHistory() async throws {
        let h = try Harness()
        let scope = try await h.login().scope
        let (packageJSON, hash) = try WorkoutFixtures.package()
        let id = WorkoutFixtures.deliveryId
        h.transport.on("POST", "/api/v1/companion/deliveries", json: #"{"data":\#(WorkoutFixtures.delivery(hash: hash))}"#)
        h.transport.on("GET", "/api/v1/companion/deliveries/\(id)/package", json: #"{"data":\#(packageJSON)}"#)
        h.transport.on("POST", "/api/v1/companion/deliveries/\(id)/ack", json: #"{"data":\#(WorkoutFixtures.delivery(status: "acknowledged", revision: 2, hash: hash))}"#)
        let repo = WorkoutRepository(api: h.api, store: h.store)
        _ = try await repo.downloadWorkout(scope: scope, plannedId: WorkoutFixtures.plannedId)
        let draft = try await repo.startWorkout(scope: scope, deliveryId: id, deviceId: h.preferences.values.deviceId)
        var set = await h.store.draftSets(scope, deliveryId: id)[0]
        set.weightKg = "62.50"
        _ = try await repo.checkpointSet(scope: scope, set)
        _ = try await repo.completeWorkout(scope: scope, deliveryId: id)

        h.transport.on("POST", "/api/v1/companion/deliveries/\(id)/start", json: #"{"data":\#(WorkoutFixtures.delivery(status: "started", revision: 3, hash: hash))}"#)
        h.transport.on("POST", "/api/v1/companion/deliveries/\(id)/progress", json: #"{"data":{"accepted":true}}"#)
        h.transport.on("POST", "/api/v1/companion/deliveries/\(id)/complete", json: WorkoutFixtures.completion(hash: hash, eventId: draft.clientEventId))
        h.transport.on("GET", "/api/v1/sync/pull", json: QAFixtures.pull([], next: "c1"))
        h.transport.on("GET", "/api/v1/sync/status", json: QAFixtures.status(deviceId: h.preferences.values.deviceId))
        let engine = SyncEngine(api: h.api, store: h.store, preferences: h.preferences, jitter: { _ in 0 })
        await CompanionHandlers.register(on: engine)
        try await engine.synchronize(scope: scope)

        #expect(await h.store.headOfQueue(scope) == nil)
        #expect(await h.store.draft(scope, deliveryId: id) == nil)
        #expect(await h.store.delivery(scope, id: id)?.status == "completed")
        let history = await h.store.history(scope, cacheKey: HistoryFilters().cacheKey)
        #expect(history.map(\.id) == ["qa-session-server"])
        #expect(history.first?.syncStatus == "synced")
        #expect(await h.store.historyDetail(scope, publicId: "qa-session-server")?.exercises.first?.sets.first?.rir == "2")
        let keys = h.transport.requests.compactMap { $0.value(forHTTPHeaderField: "Idempotency-Key") }
        #expect(Set(keys).count == keys.count)
    }

    @Test func conflictedStartIsReconciledWhenTheServerAlreadyStartedThisDelivery() async throws {
        let h = try Harness()
        let scope = try await h.login().scope
        let deviceId = h.preferences.values.deviceId
        let (packageJSON, hash) = try WorkoutFixtures.package()
        let id = WorkoutFixtures.deliveryId
        h.transport.on("POST", "/api/v1/companion/deliveries", json: #"{"data":\#(WorkoutFixtures.delivery(hash: hash))}"#)
        h.transport.on("GET", "/api/v1/companion/deliveries/\(id)/package", json: #"{"data":\#(packageJSON)}"#)
        h.transport.on("POST", "/api/v1/companion/deliveries/\(id)/ack", json: #"{"data":\#(WorkoutFixtures.delivery(status: "acknowledged", revision: 2, hash: hash))}"#)
        let repo = WorkoutRepository(api: h.api, store: h.store)
        _ = try await repo.downloadWorkout(scope: scope, plannedId: WorkoutFixtures.plannedId)
        _ = try await repo.startWorkout(scope: scope, deliveryId: id, deviceId: deviceId)

        h.transport.on("POST", "/api/v1/companion/deliveries/\(id)/start", status: 409, json: #"{"error":{"code":"delivery_state_conflict","message":"x"}}"#)
        h.transport.on("GET", "/api/v1/companion/deliveries", json: #"{"data":[\#(WorkoutFixtures.delivery(status: "started", revision: 3, hash: hash, deviceId: deviceId))]}"#)
        h.transport.on("GET", "/api/v1/sync/pull", json: QAFixtures.pull([], next: "c1"))
        h.transport.on("GET", "/api/v1/sync/status", json: QAFixtures.status(deviceId: deviceId))
        let engine = SyncEngine(api: h.api, store: h.store, preferences: h.preferences, jitter: { _ in 0 })
        await CompanionHandlers.register(on: engine)
        try await engine.synchronize(scope: scope)
        #expect(await h.store.headOfQueue(scope) == nil)
        #expect(await h.store.delivery(scope, id: id)?.status == "started")
    }

    @Test func incompatibleConflictedStartBlocksTheQueue() async throws {
        let h = try Harness()
        let scope = try await h.login().scope
        let (packageJSON, hash) = try WorkoutFixtures.package()
        let id = WorkoutFixtures.deliveryId
        h.transport.on("POST", "/api/v1/companion/deliveries", json: #"{"data":\#(WorkoutFixtures.delivery(hash: hash))}"#)
        h.transport.on("GET", "/api/v1/companion/deliveries/\(id)/package", json: #"{"data":\#(packageJSON)}"#)
        h.transport.on("POST", "/api/v1/companion/deliveries/\(id)/ack", json: #"{"data":\#(WorkoutFixtures.delivery(status: "acknowledged", revision: 2, hash: hash))}"#)
        let repo = WorkoutRepository(api: h.api, store: h.store)
        _ = try await repo.downloadWorkout(scope: scope, plannedId: WorkoutFixtures.plannedId)
        _ = try await repo.startWorkout(scope: scope, deliveryId: id, deviceId: h.preferences.values.deviceId)
        h.transport.on("POST", "/api/v1/companion/deliveries/\(id)/start", status: 409, json: #"{"error":{"code":"delivery_state_conflict","message":"x"}}"#)
        h.transport.on("GET", "/api/v1/companion/deliveries", json: #"{"data":[\#(WorkoutFixtures.delivery(status: "started", revision: 3, hash: hash, deviceId: "another-device"))]}"#)
        let engine = SyncEngine(api: h.api, store: h.store, preferences: h.preferences, jitter: { _ in 0 })
        await CompanionHandlers.register(on: engine)
        await #expect(throws: AppFailure.self) { try await engine.synchronize(scope: scope) }
        #expect(await h.store.headOfQueue(scope)?.status == "conflict")
    }
}

struct DebouncedAutosaveTests {
    final class Saved: @unchecked Sendable {
        private let lock = NSLock()
        private var items: [String] = []
        func add(_ value: String) { lock.withLock { items.append(value) } }
        var values: [String] { lock.withLock { items } }
    }

    @Test func rapidTypingPersistsOnlyLatestValueAfterDebounce() async throws {
        let saved = Saved()
        let autosave = DebouncedAutosave<String>(delay: .milliseconds(150)) { saved.add($0) }
        await autosave.submit(key: "qa-set", value: "1")
        try await Task.sleep(for: .milliseconds(50))
        await autosave.submit(key: "qa-set", value: "12")
        try await Task.sleep(for: .milliseconds(60))
        #expect(saved.values.isEmpty)
        try await Task.sleep(for: .milliseconds(400))
        #expect(saved.values == ["12"])
        #expect(await !autosave.hasPending)
    }

    @Test func lifecycleFlushPersistsLatestValueImmediately() async throws {
        let saved = Saved()
        let autosave = DebouncedAutosave<String>(delay: .seconds(10)) { saved.add($0) }
        await autosave.submit(key: "a", value: "offline-draft")
        await autosave.submit(key: "b", value: "summary")
        try await autosave.flush()
        #expect(saved.values == ["offline-draft", "summary"])
        #expect(await !autosave.hasPending)
    }

    @Test func discardDropsAPendingValue() async throws {
        let saved = Saved()
        let autosave = DebouncedAutosave<String>(delay: .seconds(10)) { saved.add($0) }
        await autosave.submit(key: "a", value: "x")
        await autosave.discard(key: "a")
        try await autosave.flush()
        #expect(saved.values.isEmpty)
    }
}

extension LocalStore {
    /// Test-only: changes a draft set without recomputing the integrity hash.
    func tamperDraftSetForTesting(_ scope: String, deliveryId: String) throws {
        try write {
            try fetch(#Predicate<DraftSetModel> { $0.accountScope == scope && $0.deliveryId == deliveryId }).first?.reps = 99
        }
    }
}
