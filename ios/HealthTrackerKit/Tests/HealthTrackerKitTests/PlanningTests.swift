import Foundation
import Testing
@testable import HealthTrackerKit

struct PlanningStoreTests {
    let scope = "qa-scope"

    private func seeded() async throws -> (LocalStore, PlanningRepository) {
        let h = try Harness()
        try await h.store.applyPlanSummaries(scope, try QAFixtures.decode(MobilePlanListDTO.self, #"{"items":[\#(TrainingFixtures.plan(withWorkouts: false))]}"#))
        try await h.store.applyPlan(scope, try QAFixtures.decode(MobilePlanDTO.self, TrainingFixtures.plan()))
        let ids = IdSequence()
        return (h.store, PlanningRepository(api: h.api, store: h.store, newId: { ids.next() }))
    }

    private func queue(_ store: LocalStore, _ scope: String) async throws -> [(String, String, JSONValue)] {
        var items: [(String, String, JSONValue)] = []
        while let head = await store.headOfQueue(scope) {
            items.append((head.actionType, head.entityId, try JSONValue.parse(head.payloadJSON)))
            try await store.completePending(head.key)
        }
        return items
    }

    @Test func offlinePlanEditsBeforeTheFirstSyncAreFoldedIntoTheCreate() async throws {
        let (store, repo) = try await seeded()
        let id = try await repo.createPlan(scope: scope, name: "  Nueva QA  ")
        try await repo.editPlan(scope: scope, publicId: id, name: "Nueva QA 2", description: "Desc")
        #expect(await store.plan(scope, publicId: id)?.syncStatus == "pending")
        let items = try await queue(store, scope)
        #expect(items.map(\.0) == ["planning_plan_create"])
        #expect(items[0].2["name"] == .string("Nueva QA 2") && items[0].2["description"] == .string("Desc"))
        await #expect(throws: AppFailure.self) { try await repo.createPlan(scope: scope, name: "  ") }
    }

    @Test func syncedPlanEditsQueueOnePatchThatIsCoalesced() async throws {
        let (store, repo) = try await seeded()
        try await repo.editPlan(scope: scope, publicId: "qa-plan-1", name: "Rutina A", description: nil)
        try await repo.editPlan(scope: scope, publicId: "qa-plan-1", name: "Rutina B", description: "x")
        #expect(await store.plan(scope, publicId: "qa-plan-1")?.revision == 2)
        let items = try await queue(store, scope)
        #expect(items.map(\.0) == ["planning_plan_patch"])
        #expect(items[0].2["base_revision"] == .number("1") && items[0].2["name"] == .string("Rutina B"))
        try await repo.editPlan(scope: scope, publicId: "qa-plan-1", name: "Rutina B", description: "x", status: "archived")
        #expect(await store.plans(scope).isEmpty)
        #expect(try await queue(store, scope).first?.2["status"] == .string("archived"))
    }

    @Test func workoutCreateAndSaveBeforeSyncShareOneOperation() async throws {
        let (store, repo) = try await seeded()
        let workout = try await repo.createWorkout(scope: scope, planId: "qa-plan-1", name: "Torso QA")
        let exercise = PlanExercise(id: "ex-1", exerciseId: "cat-1", name: "Press QA", notes: nil, exerciseOrder: 9,
                                    sets: [PlanSet(id: "s-1", setNumber: 7, reps: 8, weightKg: "40", loadValue: "40", restSeconds: 90)])
        #expect(try await repo.saveWorkout(scope: scope, workoutId: workout, name: "Torso QA", notes: nil, exercises: [exercise]))
        #expect(try await !repo.saveWorkout(scope: scope, workoutId: workout, name: "Torso QA", notes: nil, exercises: [exercise]))
        let saved = try #require(await store.planWorkout(scope, publicId: workout))
        #expect(saved.exercises[0].exerciseOrder == 1 && saved.exercises[0].sets[0].setNumber == 1)
        #expect(await store.planWorkouts(scope, planPublicId: "qa-plan-1").map(\.position) == [1, 2])
        let items = try await queue(store, scope)
        #expect(items.map(\.0) == ["planning_workout_create"])
        let body = items[0].2
        #expect(body["public_id"] == .string(workout) && body["base_revision"] == .number("1"))
        guard case let .array(exercises) = try #require(body["exercises"]) else { Issue.record("exercises"); return }
        #expect(exercises.first?["exercise_id"] == .string("cat-1"))
        guard case let .array(sets) = try #require(exercises.first?["sets"]) else { Issue.record("sets"); return }
        #expect(sets.first?["weight_kg"] == .string("40"))
    }

    @Test func editingASyncedWorkoutQueuesAPatchAndReorderingQueuesWorkoutOrder() async throws {
        let (store, repo) = try await seeded()
        var exercises = try #require(await store.planWorkout(scope, publicId: "qa-workout-1")).exercises
        exercises[0].sets.append(PlanSet(id: "s-new", setNumber: 2, reps: 6))
        try await repo.saveWorkout(scope: scope, workoutId: "qa-workout-1", name: "Pierna QA", notes: "Nota", exercises: exercises)
        let second = try await repo.createWorkout(scope: scope, planId: "qa-plan-1", name: "Extra QA")
        try await repo.moveWorkout(scope: scope, planId: "qa-plan-1", workoutId: second, delta: -1)
        #expect(await store.planWorkouts(scope, planPublicId: "qa-plan-1").map(\.publicId) == [second, "qa-workout-1"])
        let items = try await queue(store, scope)
        #expect(items.map(\.0) == ["planning_workout_patch", "planning_workout_create", "planning_plan_patch"])
        #expect(items[0].2["base_revision"] == .number("1") && items[0].2["notes"] == .string("Nota"))
        #expect(items[2].2["workout_order"] == .array([.string(second), .string("qa-workout-1")]))
    }

    @Test func schedulingIsIdempotentAndUnsentSchedulesCanBeRescheduledOrDroppedOffline() async throws {
        let (store, repo) = try await seeded()
        let id = try await repo.schedule(scope: scope, workoutId: "qa-workout-1", date: "2026-10-20", timezone: "UTC")
        #expect(try await repo.schedule(scope: scope, workoutId: "qa-workout-1", date: "2026-10-20", timezone: "UTC") == id)
        #expect(await store.plannedWorkout(scope, id: id)?.status == "locally_pending")
        try await repo.reschedule(scope: scope, scheduledId: id, date: "2026-10-21", timezone: "UTC")
        #expect(await store.plannedWorkout(scope, id: id)?.scheduledForDate == "2026-10-21")
        var head = try #require(await store.headOfQueue(scope))
        #expect(try JSONValue.parse(head.payloadJSON)["request"]?["scheduled_for_date"] == .string("2026-10-21"))
        try await repo.cancelSchedule(scope: scope, scheduledId: id)
        #expect(await store.plannedWorkout(scope, id: id) == nil)
        #expect(await store.headOfQueue(scope) == nil)

        // A server schedule: reschedule twice coalesces, cancel discards the unsent patch.
        let page = try QAFixtures.decode(PullResponse.self, envelope: QAFixtures.pull([
            QAFixtures.change("planned_workout", id: "srv-1", payload: QAFixtures.planned(id: "srv-1", date: "2026-10-22", revision: 3)),
        ], next: "c"))
        try await store.applyPullPage(scope, page, deviceId: "d")
        try await repo.reschedule(scope: scope, scheduledId: "srv-1", date: "2026-10-23", timezone: "UTC")
        try await repo.reschedule(scope: scope, scheduledId: "srv-1", date: "2026-10-24", timezone: "UTC")
        head = try #require(await store.headOfQueue(scope))
        #expect(head.actionType == "planning_schedule_patch")
        #expect(try JSONValue.parse(head.payloadJSON)["scheduled_for_date"] == .string("2026-10-24"))
        try await repo.cancelSchedule(scope: scope, scheduledId: "srv-1")
        let items = try await queue(store, scope)
        #expect(items.map(\.0) == ["planning_cancel_schedule"])
        #expect(items[0].2["base_revision"] == .number("3"))
        #expect(await store.plannedWorkout(scope, id: "srv-1")?.status == "cancelled")
    }

    @Test func remoteAgendaDoesNotOverwriteQueuedSchedules() async throws {
        let (store, repo) = try await seeded()
        let id = try await repo.schedule(scope: scope, workoutId: "qa-workout-1", date: "2026-10-20", timezone: "UTC")
        let remote = try QAFixtures.decode([PlannedWorkoutDTO].self, "[\(QAFixtures.planned(id: id, date: "2026-11-01")),\(QAFixtures.planned(id: "srv-9", date: "2026-11-02"))]")
        try await store.applySchedule(scope, remote)
        #expect(await store.plannedWorkout(scope, id: id)?.scheduledForDate == "2026-10-20")
        #expect(await store.plannedWorkout(scope, id: "srv-9")?.scheduledForDate == "2026-11-02")
    }

    @Test func catalogPagesAreCachedAndSearchableOffline() async throws {
        let store = try LocalStore.make(inMemory: true)
        let page = try QAFixtures.decode(ExerciseCatalogResponseDTO.self, #"{"items":[{"public_id":"c1","name":"Sentadilla QA","aliases":["Squat"],"archived":false,"selectable":true},{"public_id":"c2","name":"Remo QA","archived":true,"selectable":false}],"next_cursor":"n","has_more":true}"#)
        try await store.applyCatalogPage(scope, query: "", page)
        #expect(await store.catalog(scope, query: "squat").map(\.publicId) == ["c1"])
        #expect(await store.catalog(scope, query: "").map(\.publicId) == ["c1"])
        #expect(await store.catalogState(scope, query: "")?.nextCursor == "n")
        try await store.clearAccountData(scope)
        #expect(await store.catalog(scope, query: "").isEmpty)
    }
}

struct PlanningHandlerTests {
    private func engine(_ h: Harness) -> SyncEngine {
        var handlers = CompanionHandlers.all
        handlers.merge(PlanningHandlers.all) { first, _ in first }
        return SyncEngine(api: h.api, store: h.store, preferences: h.preferences, handlers: handlers, jitter: { _ in 0 })
    }

    private func scriptPull(_ h: Harness) {
        h.transport.on("GET", "/api/v1/sync/pull", json: QAFixtures.pull([], next: "c1"))
        h.transport.on("GET", "/api/v1/sync/status", json: QAFixtures.status(deviceId: h.preferences.values.deviceId))
    }

    @Test func queuedPlanningSyncsAndMarksEntitiesSynced() async throws {
        let h = try Harness()
        let scope = try await h.login().scope
        let ids = IdSequence()
        let repo = PlanningRepository(api: h.api, store: h.store, newId: { ids.next() })
        let plan = try await repo.createPlan(scope: scope, name: "Plan QA")
        let workout = try await repo.createWorkout(scope: scope, planId: plan, name: "Día QA")
        let schedule = try await repo.schedule(scope: scope, workoutId: workout, date: "2026-10-20", timezone: "UTC")
        h.transport.on("POST", "/api/v1/mobile/plans", status: 201, json: #"{"data":{"public_id":"\#(plan)","status":"active","revision":1}}"#)
        h.transport.on("POST", "/api/v1/mobile/plans/\(plan)/workouts", status: 201, json: #"{"data":{"public_id":"\#(workout)","plan_id":"\#(plan)","position":1,"revision":1,"plan_revision":2}}"#)
        h.transport.on("POST", "/api/v1/mobile/workouts/\(workout)/schedule", status: 201, json: #"{"data":{"public_id":"\#(schedule)","status":"planned","revision":1,"scheduled_for_date":"2026-10-20","timezone":"UTC"}}"#)
        scriptPull(h)
        try await engine(h).synchronize(scope: scope)
        #expect(await h.store.headOfQueue(scope) == nil)
        #expect(await h.store.plan(scope, publicId: plan)?.syncStatus == "synced")
        #expect(await h.store.planWorkout(scope, publicId: workout)?.syncStatus == "synced")
        #expect(await h.store.plannedWorkout(scope, id: schedule)?.status == "planned")
        let scheduleRequest = try #require(h.transport.requests.first { $0.url?.path.hasSuffix("/schedule") == true })
        #expect(try JSONValue.parse(try #require(scheduleRequest.httpBody))["public_id"] == .string(schedule))
    }

    @Test func revisionConflictRecordsBothVersionsAndRetryRebases() async throws {
        let h = try Harness()
        let scope = try await h.login().scope
        try await h.store.applyPlanSummaries(scope, try QAFixtures.decode(MobilePlanListDTO.self, #"{"items":[\#(TrainingFixtures.plan(withWorkouts: false))]}"#))
        let ids = IdSequence()
        let repo = PlanningRepository(api: h.api, store: h.store, newId: { ids.next() })
        try await repo.editPlan(scope: scope, publicId: "qa-plan-1", name: "Local QA", description: nil)
        h.transport.on("PATCH", "/api/v1/mobile/plans/qa-plan-1", status: 409, json: #"{"error":{"code":"revision_conflict","message":"x"}}"#)
        h.transport.on("GET", "/api/v1/mobile/plans/qa-plan-1", json: #"{"data":\#(TrainingFixtures.plan(name: "Remota QA", revision: 5, withWorkouts: false))}"#)
        await #expect(throws: AppFailure.self) { try await engine(h).synchronize(scope: scope) }
        let conflict = try #require(await h.store.planningConflict(scope, entityId: "qa-plan-1"))
        #expect(conflict.localName == "Local QA" && conflict.remoteName == "Remota QA" && conflict.serverRevision == 5)
        #expect(await h.store.plan(scope, publicId: "qa-plan-1")?.syncStatus == "conflict")
        #expect(await h.store.snapshot(scope).conflictCount == 2)

        h.transport.on("GET", "/api/v1/mobile/plans/qa-plan-1", json: #"{"data":\#(TrainingFixtures.plan(name: "Remota QA", revision: 5, withWorkouts: false))}"#)
        try await repo.retry(scope: scope, entityId: "qa-plan-1")
        let head = try #require(await h.store.headOfQueue(scope))
        #expect(head.status == "pending" && head.idempotencyKey != "00000000-0000-4000-8000-000000000001")
        #expect(try JSONValue.parse(head.payloadJSON)["base_revision"] == .number("5"))
        #expect(await h.store.planningConflict(scope, entityId: "qa-plan-1") == nil)
    }

    @Test func keepRemoteReplacesTheLocalCopyAndDuplicateKeepsIt() async throws {
        let h = try Harness()
        let scope = try await h.login().scope
        try await h.store.applyPlanSummaries(scope, try QAFixtures.decode(MobilePlanListDTO.self, #"{"items":[\#(TrainingFixtures.plan(withWorkouts: false))]}"#))
        try await h.store.applyPlan(scope, try QAFixtures.decode(MobilePlanDTO.self, TrainingFixtures.plan()))
        let ids = IdSequence()
        let repo = PlanningRepository(api: h.api, store: h.store, newId: { ids.next() })
        try await repo.editPlan(scope: scope, publicId: "qa-plan-1", name: "Local QA", description: nil)
        h.transport.on("PATCH", "/api/v1/mobile/plans/qa-plan-1", status: 409, json: #"{"error":{"code":"revision_conflict","message":"x"}}"#)
        h.transport.on("GET", "/api/v1/mobile/plans/qa-plan-1", json: #"{"data":\#(TrainingFixtures.plan(name: "Remota QA", revision: 5, withWorkouts: false))}"#)
        await #expect(throws: AppFailure.self) { try await engine(h).synchronize(scope: scope) }

        h.transport.on("GET", "/api/v1/mobile/plans/qa-plan-1", json: #"{"data":\#(TrainingFixtures.plan(name: "Remota QA", revision: 5))}"#)
        let copy = try await repo.duplicateConflict(scope: scope, entityId: "qa-plan-1")
        #expect(await h.store.plan(scope, publicId: "qa-plan-1")?.name == "Remota QA")
        #expect(await h.store.plan(scope, publicId: "qa-plan-1")?.syncStatus == "synced")
        #expect(await h.store.plan(scope, publicId: copy)?.name == "Local QA (copia local)")
        #expect(await h.store.planWorkouts(scope, planPublicId: copy).first?.exercises.first?.name == "Sentadilla QA")
        #expect(await h.store.planningConflicts(scope).isEmpty)
        var types: [String] = []
        while let head = await h.store.headOfQueue(scope) {
            types.append(head.actionType)
            try await h.store.completePending(head.key)
        }
        #expect(types == ["planning_plan_create", "planning_workout_create"])
    }

    @Test func retryableFailureLeavesTheScheduleLocallyPending() async throws {
        let h = try Harness()
        let scope = try await h.login().scope
        try await h.store.applyPlan(scope, try QAFixtures.decode(MobilePlanDTO.self, TrainingFixtures.plan()))
        let repo = PlanningRepository(api: h.api, store: h.store)
        let id = try await repo.schedule(scope: scope, workoutId: "qa-workout-1", date: "2026-10-20", timezone: "UTC")
        h.transport.on("POST", "/api/v1/mobile/workouts/qa-workout-1/schedule", status: 503, json: #"{"error":{"code":"server_error","message":"x"}}"#)
        await #expect(throws: AppFailure.self) { try await engine(h).synchronize(scope: scope) }
        #expect(await h.store.plannedWorkout(scope, id: id)?.status == "locally_pending")
        #expect(await h.store.headOfQueue(scope)?.status == "pending")
    }

    @Test func cancelHandlerSendsDeleteWithBodyAndRemovesTheSchedule() async throws {
        let h = try Harness()
        let scope = try await h.login().scope
        let repo = PlanningRepository(api: h.api, store: h.store)
        try await repo.cancelSchedule(scope: scope, scheduledId: "qa-planned-1")
        h.transport.on("DELETE", "/api/v1/mobile/scheduled-workouts/qa-planned-1", json: #"{"data":{"deleted":true}}"#)
        scriptPull(h)
        try await engine(h).synchronize(scope: scope)
        let request = try #require(h.transport.requests.first { $0.httpMethod == "DELETE" })
        #expect(try JSONValue.parse(try #require(request.httpBody))["base_revision"] == .number("1"))
        #expect(await h.store.plannedWorkout(scope, id: "qa-planned-1") == nil)
    }
}
