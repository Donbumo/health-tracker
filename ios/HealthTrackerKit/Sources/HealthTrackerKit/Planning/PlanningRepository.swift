import Foundation

/// Offline plan editing, agenda and conflict resolution (android `CompanionRepository` planning).
public struct PlanningRepository: Sendable {
    private let api: APIClient
    private let store: LocalStore
    private let training: TrainingRepository
    private let now: @Sendable () -> Date
    private let newId: @Sendable () -> String

    public init(api: APIClient, store: LocalStore, now: @escaping @Sendable () -> Date = Date.init,
                newId: @escaping @Sendable () -> String = { UUID().uuidString.lowercased() }) {
        self.api = api
        self.store = store
        self.training = TrainingRepository(api: api, store: store, now: now)
        self.now = now
        self.newId = newId
    }

    // MARK: Plans and workouts

    public func createPlan(scope: String, name: String, description: String? = nil) async throws -> String {
        let id = newId()
        try await store.createPlanOffline(scope, id: id, key: newId(), name: name, description: description, now: now())
        return id
    }

    public func editPlan(scope: String, publicId: String, name: String, description: String?, status: String? = nil) async throws {
        try await store.editPlanOffline(scope, publicId: publicId, name: name, description: description, status: status, key: newId(), now: now())
    }

    public func createWorkout(scope: String, planId: String, name: String) async throws -> String {
        let id = newId()
        try await store.createWorkoutOffline(scope, planId: planId, workoutId: id, key: newId(), name: name, now: now())
        return id
    }

    @discardableResult
    public func saveWorkout(scope: String, workoutId: String, name: String, notes: String?, exercises: [PlanExercise]) async throws -> Bool {
        try await store.saveWorkoutOffline(scope, workoutId: workoutId, name: name, notes: notes, exercises: exercises, key: newId(), now: now())
    }

    public func moveWorkout(scope: String, planId: String, workoutId: String, delta: Int) async throws {
        let ids = await store.planWorkouts(scope, planPublicId: planId).map(\.publicId)
        guard let ordered = PlanningRules.reorderedIds(ids, id: workoutId, delta: delta) else { return }
        try await store.reorderWorkoutsOffline(scope, planId: planId, orderedIds: ordered, key: newId(), now: now())
    }

    /// Copies a plan with all its workouts, exercises and sets as new local entities.
    public func duplicatePlan(scope: String, sourcePlanId: String, name: String) async throws -> String {
        guard let source = await store.plan(scope, publicId: sourcePlanId) else {
            throw AppFailure(.localStorageError, "La rutina no está disponible localmente.", retryable: false)
        }
        let target = try await createPlan(scope: scope, name: name, description: source.description)
        for workout in await store.planWorkouts(scope, planPublicId: sourcePlanId) {
            let copy = try await createWorkout(scope: scope, planId: target, name: workout.name)
            try await saveWorkout(scope: scope, workoutId: copy, name: workout.name, notes: workout.notes, exercises: renewed(workout.exercises))
        }
        return target
    }

    public func duplicateWorkout(scope: String, sourceWorkoutId: String) async throws -> String {
        guard let source = await store.planWorkout(scope, publicId: sourceWorkoutId) else {
            throw AppFailure(.localStorageError, "El entrenamiento no está disponible localmente.", retryable: false)
        }
        let name = "\(source.name) (copia)"
        let copy = try await createWorkout(scope: scope, planId: source.planPublicId, name: name)
        try await saveWorkout(scope: scope, workoutId: copy, name: name, notes: source.notes, exercises: renewed(source.exercises))
        return copy
    }

    /// New prescription ids so a copy never collides with its source.
    public func renewed(_ exercises: [PlanExercise]) -> [PlanExercise] {
        exercises.map { exercise in
            var copy = exercise
            copy.id = newId()
            copy.sets = exercise.sets.map { set in
                var setCopy = set
                setCopy.id = newId()
                return setCopy
            }
            return copy
        }
    }

    // MARK: Schedules

    public func schedule(scope: String, workoutId: String, date: String, timezone: String) async throws -> String {
        try await store.scheduleWorkoutOffline(scope, workoutId: workoutId, date: date, timezone: timezone, id: newId(), key: newId(), now: now())
    }

    public func cancelSchedule(scope: String, scheduledId: String) async throws {
        try await store.cancelScheduleOffline(scope, scheduledId: scheduledId, key: newId(), now: now())
    }

    public func reschedule(scope: String, scheduledId: String, date: String, timezone: String) async throws {
        try await store.rescheduleWorkoutOffline(scope, scheduledId: scheduledId, date: date, timezone: timezone, key: newId(), now: now())
    }

    /// Refreshes the agenda window around today (±180 days, like Android).
    public func refreshSchedule(scope: String, today: String) async throws {
        let from = PlanningRules.shiftedAnchor(today, month: false, delta: -26)
        let to = PlanningRules.shiftedAnchor(today, month: false, delta: 26)
        try await store.applySchedule(scope, try await api.plannedWorkouts(from: from, to: to))
    }

    // MARK: Catalog

    public func refreshCatalog(scope: String, query: String, reset: Bool = true) async throws {
        let key = query.trimmingCharacters(in: .whitespaces).lowercased()
        let state = reset ? nil : await store.catalogState(scope, query: key)
        if !reset, state?.hasMore == false { return }
        let page = try await api.exerciseCatalog(search: key, cursor: state?.nextCursor)
        try await store.applyCatalogPage(scope, query: key, page, now: now())
    }

    // MARK: Conflicts

    public func keepRemote(scope: String, entityId: String) async throws {
        guard let conflict = await store.planningConflict(scope, entityId: entityId) else { return }
        switch conflict.entityType {
        case "schedule", "package":
            try await store.acceptRemoteSchedule(scope, entityId: entityId, remote: try await remoteOrNil { try await api.plannedWorkout(entityId) })
        default:
            if conflict.changedFields == "remote_deleted" {
                try await store.acceptRemotePlan(scope, entityId: entityId, remote: nil)
                return
            }
            let planId = await store.planWorkout(scope, publicId: entityId)?.planPublicId ?? entityId
            try await store.acceptRemotePlan(scope, entityId: entityId, remote: try await remoteOrNil { try await api.plan(planId) })
        }
    }

    public func retry(scope: String, entityId: String) async throws {
        guard let pending = await store.conflictedAction(scope, entityId: entityId) else { return }
        let revision: Int
        switch pending.actionType {
        case "planning_plan_patch", "planning_workout_create": revision = try await api.plan(entityId).revision
        case "planning_workout_patch": revision = try await api.planWorkout(entityId).revision
        case "planning_schedule_patch", "planning_cancel_schedule": revision = try await api.plannedWorkout(entityId).revision
        default:
            throw AppFailure(.submissionConflict, "Esta operación no puede reintentarse sin elegir la versión remota.", retryable: false)
        }
        try await store.rebaseConflict(scope, entityId: entityId, remoteRevision: revision, newKey: newId())
    }

    /// Keeps the local copy as a new plan or workout, then accepts the server version of the original.
    public func duplicateConflict(scope: String, entityId: String) async throws -> String {
        guard let conflict = await store.planningConflict(scope, entityId: entityId) else {
            throw AppFailure(.localStorageError, "El conflicto ya no está disponible.", retryable: false)
        }
        let copy: String
        switch conflict.entityType {
        case "plan":
            guard let source = await store.plan(scope, publicId: entityId) else {
                throw AppFailure(.localStorageError, "La copia local de la rutina no está disponible.", retryable: false)
            }
            copy = try await duplicatePlan(scope: scope, sourcePlanId: entityId, name: "\(source.name) (copia local)")
        case "workout":
            copy = try await duplicateWorkout(scope: scope, sourceWorkoutId: entityId)
        default:
            throw AppFailure(.validationError, "Este conflicto no admite duplicación.", retryable: false)
        }
        try await keepRemote(scope: scope, entityId: entityId)
        return copy
    }

    private func remoteOrNil<T>(_ load: () async throws -> T) async throws -> T? {
        do { return try await load() } catch let failure as AppFailure where failure.serverCode == "not_found" { return nil }
    }

    // MARK: Plans list

    public func refreshPlans(scope: String, includeArchived: Bool) async throws {
        try await training.refreshPlans(scope: scope)
        if includeArchived { try await training.refreshPlans(scope: scope, status: "archived") }
    }
}
