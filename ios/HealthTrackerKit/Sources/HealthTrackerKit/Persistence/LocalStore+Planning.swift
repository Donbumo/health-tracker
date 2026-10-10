import Foundation
import SwiftData

public struct CatalogExercise: Sendable, Equatable, Identifiable {
    public var id: String { publicId }
    public let publicId: String
    public let name: String
    public let aliases: [String]
    public let selectable: Bool
    public let archived: Bool
    public let preferredLoadMode: String?
    public let preferredUnit: String?
}

public struct PlanningConflict: Sendable, Equatable, Identifiable {
    public var id: String { entityId }
    public let entityId: String
    public let entityType: String
    public let localRevision: Int
    public let serverRevision: Int?
    public let changedFields: String
    public let localName: String?
    public let remoteName: String?
}

/// Which local planning entity an action refers to (android `markPlanningConflict` lookup order).
public enum PlanningEntity: Sendable, Equatable {
    case schedule(title: String, date: String, revision: Int)
    case workout(name: String, revision: Int)
    case plan(name: String, revision: Int)
}

// MARK: Offline planning (android `CompanionRepository.createPlanOffline…rescheduleWorkoutOffline`)

extension LocalStore {
    // MARK: Plans

    public func createPlanOffline(_ scope: String, id: String, key: String, name: String, description: String?, now: Date = Date()) throws {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw AppFailure(.validationError, "La rutina necesita un nombre.", retryable: false) }
        let normalizedDescription = Self.normalized(description)
        try write {
            let plan = PlanModel(scope: scope, publicId: id)
            plan.name = trimmed
            plan.planDescription = normalizedDescription
            plan.revision = 1
            plan.syncStatus = "pending"
            plan.createdAt = iso(now)
            plan.updatedAt = iso(now)
            modelContext.insert(plan)
            var payload: [(String, JSONValue)] = [("public_id", .string(id)), ("name", .string(trimmed))]
            if let normalizedDescription { payload.append(("description", .string(normalizedDescription))) }
            try insertPending(scope, actionType: "planning_plan_create", entityId: id, idempotencyKey: key, payloadJSON: JSONValue.object(payload).encoded(), now: now)
        }
    }

    /// Renames, describes, archives (`status = archived`) or restores (`active`) a plan. Unsent work is coalesced.
    public func editPlanOffline(_ scope: String, publicId: String, name: String, description: String?, status: String? = nil, key: String, now: Date = Date()) throws {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw AppFailure(.validationError, "La rutina necesita un nombre.", retryable: false) }
        let normalizedDescription = Self.normalized(description)
        try write {
            guard let plan = try planModel(scope, publicId) else {
                throw AppFailure(.localStorageError, "La rutina no está disponible localmente.", retryable: false)
            }
            let pendingCreate = try pendingModel(scope, entityId: publicId, type: "planning_plan_create")
            let existingPatch = try pendingModel(scope, entityId: publicId, type: "planning_plan_patch")
            let baseRevision = existingPatch.flatMap { Self.request($0)["base_revision"]?.intValue } ?? plan.revision
            var payload: [(String, JSONValue)] = [
                ("base_revision", .number(String(baseRevision))), ("name", .string(trimmed)),
                ("description", normalizedDescription.map(JSONValue.string) ?? .null),
            ]
            if let status { payload.append(("status", .string(status))) }
            let foldedIntoCreate = pendingCreate != nil && status == nil
            plan.name = trimmed
            plan.planDescription = normalizedDescription
            if let status {
                plan.status = status
                plan.archivedAt = status == "archived" ? iso(now) : nil
            }
            if !foldedIntoCreate && existingPatch == nil { plan.revision += 1 }
            plan.syncStatus = "pending"
            plan.updatedAt = iso(now)
            if foldedIntoCreate, let pendingCreate {
                try replacePayload(pendingCreate, .object([
                    ("public_id", .string(publicId)), ("name", .string(trimmed)),
                    ("description", normalizedDescription.map(JSONValue.string) ?? .null),
                ]))
            } else if let existingPatch {
                try replacePayload(existingPatch, .object(payload))
            } else {
                try insertPending(scope, actionType: "planning_plan_patch", entityId: publicId, idempotencyKey: key, payloadJSON: JSONValue.object(payload).encoded(), now: now)
            }
        }
    }

    public func reorderWorkoutsOffline(_ scope: String, planId: String, orderedIds: [String], key: String, now: Date = Date()) throws {
        try write {
            guard let plan = try planModel(scope, planId) else {
                throw AppFailure(.localStorageError, "La rutina no está disponible localmente.", retryable: false)
            }
            let workouts = try fetch(#Predicate<PlanWorkoutModel> { $0.accountScope == scope && $0.planPublicId == planId })
            guard Set(orderedIds) == Set(workouts.map(\.publicId)), orderedIds.count == workouts.count else {
                throw AppFailure(.validationError, "El orden de entrenamientos no es válido.", retryable: false)
            }
            for (index, id) in orderedIds.enumerated() {
                guard let workout = workouts.first(where: { $0.publicId == id }) else { continue }
                workout.position = index + 1
                workout.revision += 1
                workout.syncStatus = "pending"
                workout.updatedAt = iso(now)
            }
            let payload: JSONValue = .object([
                ("base_revision", .number(String(plan.revision))),
                ("workout_order", .array(orderedIds.map(JSONValue.string))),
            ])
            plan.revision += 1
            plan.syncStatus = "pending"
            plan.updatedAt = iso(now)
            try insertPending(scope, actionType: "planning_plan_patch", entityId: planId, idempotencyKey: key, payloadJSON: payload.encoded(), now: now)
        }
    }

    // MARK: Workouts

    public func createWorkoutOffline(_ scope: String, planId: String, workoutId: String, key: String, name: String, now: Date = Date()) throws {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw AppFailure(.validationError, "El entrenamiento necesita un nombre.", retryable: false) }
        try write {
            guard let plan = try planModel(scope, planId) else {
                throw AppFailure(.localStorageError, "La rutina no está disponible localmente.", retryable: false)
            }
            let count = try modelContext.fetchCount(FetchDescriptor<PlanWorkoutModel>(predicate: #Predicate { $0.accountScope == scope && $0.planPublicId == planId }))
            modelContext.insert(PlanWorkoutModel(scope: scope, planPublicId: planId, publicId: workoutId, name: trimmed, notes: nil, position: count + 1, now: iso(now)))
            let payload: JSONValue = .object([
                ("public_id", .string(workoutId)), ("base_revision", .number(String(plan.revision))),
                ("name", .string(trimmed)), ("exercises", .array([])),
            ])
            plan.revision += 1
            plan.workoutCount = count + 1
            plan.syncStatus = "pending"
            plan.updatedAt = iso(now)
            try insertPending(scope, actionType: "planning_workout_create", entityId: planId, idempotencyKey: key, payloadJSON: payload.encoded(), now: now)
        }
    }

    /// Saves the full prescription of a workout. Exercise order and set numbers follow array order.
    /// Returns false when nothing changed (no operation is queued).
    @discardableResult
    public func saveWorkoutOffline(_ scope: String, workoutId: String, name: String, notes: String?, exercises: [PlanExercise], key: String, now: Date = Date()) throws -> Bool {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw AppFailure(.validationError, "El entrenamiento necesita un nombre.", retryable: false) }
        let normalizedNotes = Self.normalized(notes)
        let ordered = exercises.enumerated().map { index, exercise in
            var copy = exercise
            copy.exerciseOrder = index + 1
            copy.sets = exercise.sets.enumerated().map { setIndex, set in
                var setCopy = set
                setCopy.setNumber = setIndex + 1
                return setCopy
            }
            return copy
        }
        return try write {
            let workoutKey = scopedKey(scope, workoutId)
            guard let workout = try fetch(#Predicate<PlanWorkoutModel> { $0.key == workoutKey }).first else {
                throw AppFailure(.localStorageError, "El entrenamiento no está disponible localmente.", retryable: false)
            }
            guard let plan = try planModel(scope, workout.planPublicId) else {
                throw AppFailure(.localStorageError, "La rutina no está disponible localmente.", retryable: false)
            }
            if workout.name == trimmed, workout.notes == normalizedNotes, planWorkout(scope, publicId: workoutId)?.exercises == ordered { return false }
            let pendingCreate = try fetch(#Predicate<PendingActionModel> { $0.accountScope == scope && $0.actionType == "planning_workout_create" })
                .first { Self.request($0)["public_id"]?.stringValue == workoutId }
            let existingPatch = try pendingModel(scope, entityId: workoutId, type: "planning_workout_patch")
            let baseRevision = existingPatch.flatMap { Self.request($0)["base_revision"]?.intValue } ?? workout.revision
            let payload = Self.workoutPatchPayload(baseRevision: baseRevision, name: trimmed, notes: normalizedNotes, exercises: ordered)
            try modelContext.delete(model: PlanExerciseModel.self, where: #Predicate { $0.accountScope == scope && $0.workoutPublicId == workoutId })
            try modelContext.delete(model: PlanSetModel.self, where: #Predicate { $0.accountScope == scope && $0.workoutPublicId == workoutId })
            for exercise in ordered {
                modelContext.insert(PlanExerciseModel(scope: scope, workoutPublicId: workoutId, value: exercise))
                exercise.sets.forEach { modelContext.insert(PlanSetModel(scope: scope, workoutPublicId: workoutId, exerciseRowId: exercise.id, value: $0)) }
            }
            let fresh = pendingCreate == nil && existingPatch == nil
            workout.name = trimmed
            workout.notes = normalizedNotes
            if fresh { workout.revision += 1; plan.revision += 1 }
            workout.syncStatus = "pending"
            workout.updatedAt = iso(now)
            plan.syncStatus = "pending"
            plan.updatedAt = iso(now)
            if let pendingCreate {
                guard case var .object(members) = payload else { return true }
                members.removeAll { $0.0 == "base_revision" }
                members.append(("base_revision", Self.request(pendingCreate)["base_revision"] ?? .number("1")))
                members.append(("public_id", .string(workoutId)))
                try replacePayload(pendingCreate, .object(members))
            } else if let existingPatch {
                try replacePayload(existingPatch, payload)
            } else {
                try insertPending(scope, actionType: "planning_workout_patch", entityId: workoutId, idempotencyKey: key, payloadJSON: payload.encoded(), now: now)
            }
            return true
        }
    }

    // MARK: Schedules

    /// Schedules a workout locally; the same workout, day and zone already queued returns the existing id.
    public func scheduleWorkoutOffline(_ scope: String, workoutId: String, date: String, timezone: String, id: String, key: String, now: Date = Date()) throws -> String {
        guard PlanningRules.parse(date) != nil else { throw AppFailure(.validationError, "La fecha no es válida.", retryable: false) }
        return try write {
            let workoutKey = scopedKey(scope, workoutId)
            guard let workout = try fetch(#Predicate<PlanWorkoutModel> { $0.key == workoutKey }).first else {
                throw AppFailure(.localStorageError, "El entrenamiento no está disponible localmente.", retryable: false)
            }
            let queued = try fetch(#Predicate<PendingActionModel> { $0.accountScope == scope && $0.actionType == "planning_schedule" })
            if let existing = queued.first(where: { pending in
                guard let root = try? JSONValue.parse(pending.payloadJSON) else { return false }
                let request = root["request"]
                return root["workout_id"]?.stringValue == workoutId && request?["scheduled_for_date"]?.stringValue == date && request?["timezone"]?.stringValue == timezone
            }) { return existing.entityId }
            modelContext.insert(PlannedWorkoutModel(scope: scope, id: id, planId: workout.planPublicId, workoutId: workoutId, title: workout.name,
                                                    date: date, timezone: timezone, now: iso(now)))
            let payload: JSONValue = .object([
                ("workout_id", .string(workoutId)),
                ("request", .object([("public_id", .string(id)), ("scheduled_for_date", .string(date)), ("timezone", .string(timezone))])),
            ])
            try insertPending(scope, actionType: "planning_schedule", entityId: id, idempotencyKey: key, payloadJSON: payload.encoded(), now: now)
            return id
        }
    }

    /// Cancels a schedule. One never sent is simply removed; a sent one queues `planning_cancel_schedule`.
    public func cancelScheduleOffline(_ scope: String, scheduledId: String, key: String, now: Date = Date()) throws {
        try write {
            let plannedKey = scopedKey(scope, scheduledId)
            guard let planned = try fetch(#Predicate<PlannedWorkoutModel> { $0.key == plannedKey }).first else {
                throw AppFailure(.localStorageError, "La programación no está disponible localmente.", retryable: false)
            }
            if let create = try pendingModel(scope, entityId: scheduledId, type: "planning_schedule"), Self.untouched(create) {
                modelContext.delete(create)
                modelContext.delete(planned)
                return
            }
            if try pendingModel(scope, entityId: scheduledId, type: "planning_cancel_schedule") != nil { return }
            let patch = try pendingModel(scope, entityId: scheduledId, type: "planning_schedule_patch")
            let patchBase = patch.flatMap { Self.request($0)["base_revision"]?.intValue }
            let canDiscard = patch.map(Self.untouched) ?? false
            let base = patchBase.map { canDiscard ? $0 : $0 + 1 } ?? planned.revision
            if canDiscard, let patch { modelContext.delete(patch) }
            planned.status = "cancelled"
            planned.deleted = false
            planned.updatedAt = iso(now)
            try insertPending(scope, actionType: "planning_cancel_schedule", entityId: scheduledId, idempotencyKey: key,
                              payloadJSON: JSONValue.object([("base_revision", .number(String(base)))]).encoded(), now: now)
        }
    }

    public func rescheduleWorkoutOffline(_ scope: String, scheduledId: String, date: String, timezone: String, key: String, now: Date = Date()) throws {
        guard PlanningRules.parse(date) != nil else { throw AppFailure(.validationError, "La fecha no es válida.", retryable: false) }
        try write {
            let plannedKey = scopedKey(scope, scheduledId)
            guard let planned = try fetch(#Predicate<PlannedWorkoutModel> { $0.key == plannedKey }).first else {
                throw AppFailure(.localStorageError, "La programación no está disponible localmente.", retryable: false)
            }
            guard !["completed", "cancelled"].contains(planned.status) else {
                throw AppFailure(.revisionConflict, "La programación ya está finalizada.", retryable: false)
            }
            if planned.scheduledForDate == date && planned.timezone == timezone { return }
            if let create = try pendingModel(scope, entityId: scheduledId, type: "planning_schedule"), Self.untouched(create),
               let root = try? JSONValue.parse(create.payloadJSON), let workoutId = root["workout_id"]?.stringValue {
                planned.scheduledForDate = date
                planned.timezone = timezone
                planned.status = "locally_pending"
                planned.updatedAt = iso(now)
                try replacePayload(create, .object([
                    ("workout_id", .string(workoutId)),
                    ("request", .object([("public_id", .string(scheduledId)), ("scheduled_for_date", .string(date)), ("timezone", .string(timezone))])),
                ]))
                return
            }
            let patch = try pendingModel(scope, entityId: scheduledId, type: "planning_schedule_patch")
            let patchBase = patch.flatMap { Self.request($0)["base_revision"]?.intValue }
            let canCoalesce = patch.map(Self.untouched) ?? false
            let base = patchBase.map { canCoalesce ? $0 : $0 + 1 } ?? planned.revision
            let payload: JSONValue = .object([
                ("base_revision", .number(String(base))), ("scheduled_for_date", .string(date)), ("timezone", .string(timezone)),
            ])
            planned.scheduledForDate = date
            planned.timezone = timezone
            planned.status = "locally_pending"
            planned.updatedAt = iso(now)
            if let patch, canCoalesce {
                try replacePayload(patch, payload)
            } else {
                try insertPending(scope, actionType: "planning_schedule_patch", entityId: scheduledId, idempotencyKey: key, payloadJSON: payload.encoded(), now: now)
            }
        }
    }

    /// Applies a remote agenda window, skipping schedules with local edits still queued.
    public func applySchedule(_ scope: String, _ remote: [PlannedWorkoutDTO]) throws {
        try write {
            let types = ["planning_schedule", "planning_schedule_patch", "planning_cancel_schedule"]
            let protectedIds = Set(try fetch(#Predicate<PendingActionModel> { $0.accountScope == scope && types.contains($0.actionType) }).map(\.entityId))
            for value in remote where !protectedIds.contains(value.id) {
                let key = scopedKey(scope, value.id)
                if let local = try fetch(#Predicate<PlannedWorkoutModel> { $0.key == key }).first {
                    if ["locally_pending", "syncing", "conflict"].contains(local.status) { continue }
                    local.update(from: value)
                } else {
                    modelContext.insert(PlannedWorkoutModel(scope: scope, dto: value))
                }
            }
        }
    }

    // MARK: Catalog

    public func applyCatalogPage(_ scope: String, query: String, _ page: ExerciseCatalogResponseDTO, now: Date = Date()) throws {
        try write {
            for item in page.items {
                let key = scopedKey(scope, item.publicId)
                try modelContext.delete(model: ExerciseCatalogModel.self, where: #Predicate { $0.key == key })
                modelContext.insert(ExerciseCatalogModel(scope: scope, dto: item, now: iso(now)))
            }
            let stateKey = scopedKey(scope, "catalog#\(query)")
            try modelContext.delete(model: CatalogQueryStateModel.self, where: #Predicate { $0.key == stateKey })
            modelContext.insert(CatalogQueryStateModel(scope: scope, query: query, nextCursor: page.nextCursor, hasMore: page.hasMore, updatedAt: iso(now)))
        }
    }

    public func catalogState(_ scope: String, query: String) -> HistoryQueryState? {
        let key = scopedKey(scope, "catalog#\(query)")
        return (try? fetch(#Predicate<CatalogQueryStateModel> { $0.key == key }).first).map { HistoryQueryState(nextCursor: $0.nextCursor, hasMore: $0.hasMore) }
    }

    /// Cached catalog entries matching a name or alias, offline included.
    public func catalog(_ scope: String, query: String) -> [CatalogExercise] {
        let needle = query.trimmingCharacters(in: .whitespaces).lowercased()
        let rows = (try? fetch(#Predicate<ExerciseCatalogModel> { $0.accountScope == scope }, sort: [SortDescriptor(\.normalizedName)])) ?? []
        return rows.filter { !$0.archived && (needle.isEmpty || $0.normalizedName.contains(needle) || $0.aliases.lowercased().contains(needle)) }.map {
            CatalogExercise(publicId: $0.publicId, name: $0.name, aliases: $0.aliases.split(separator: "|").map(String.init), selectable: $0.selectable,
                            archived: $0.archived, preferredLoadMode: $0.preferredLoadMode, preferredUnit: $0.preferredUnit)
        }
    }

    // MARK: Conflicts

    public func planningConflicts(_ scope: String) -> [PlanningConflict] {
        ((try? fetch(#Predicate<PlanningConflictModel> { $0.accountScope == scope }, sort: [SortDescriptor(\.createdAt)])) ?? []).map {
            PlanningConflict(entityId: $0.entityId, entityType: $0.entityType, localRevision: $0.localRevision, serverRevision: $0.serverRevision,
                             changedFields: $0.changedFields, localName: $0.localName, remoteName: $0.remoteName)
        }
    }

    public func planningConflict(_ scope: String, entityId: String) -> PlanningConflict? {
        planningConflicts(scope).first { $0.entityId == entityId }
    }

    /// The conflicted queue entry for an entity, if any.
    public func conflictedAction(_ scope: String, entityId: String) -> PendingAction? {
        guard let model = try? fetch(#Predicate<PendingActionModel> { $0.accountScope == scope && $0.entityId == entityId && $0.status == "conflict" }).first else { return nil }
        return PendingAction(key: model.key, sequence: model.sequence, actionType: model.actionType, entityId: model.entityId,
                             idempotencyKey: model.idempotencyKey, payloadJSON: model.payloadJSON, status: model.status,
                             attemptCount: model.attemptCount, notBefore: model.notBefore, lastErrorCode: model.lastErrorCode)
    }

    /// "Usar servidor" for a plan or workout: drop local work and take the remote plan (nil = deleted remotely).
    public func acceptRemotePlan(_ scope: String, entityId: String, remote: MobilePlanDTO?) throws {
        try write {
            try dropLocalPlanningWork(scope, entityId: entityId)
            guard let remote else {
                try deletePlanChildren(scope, planPublicId: entityId)
                let key = scopedKey(scope, entityId)
                try modelContext.delete(model: PlanModel.self, where: #Predicate { $0.key == key })
                return
            }
            try dropLocalPlanningWork(scope, entityId: remote.publicId)
            let key = scopedKey(scope, remote.publicId)
            try fetch(#Predicate<PlanModel> { $0.key == key }).first?.syncStatus = "synced"
        }
        if let remote { try applyPlan(scope, remote) }
    }

    /// "Usar servidor" for a schedule or package conflict (nil = deleted remotely).
    public func acceptRemoteSchedule(_ scope: String, entityId: String, remote: PlannedWorkoutDTO?) throws {
        try write {
            try dropLocalPlanningWork(scope, entityId: entityId)
            let key = scopedKey(scope, entityId)
            if let remote {
                if let local = try fetch(#Predicate<PlannedWorkoutModel> { $0.key == key }).first { local.update(from: remote) }
                else { modelContext.insert(PlannedWorkoutModel(scope: scope, dto: remote)) }
            } else {
                try modelContext.delete(model: PlannedWorkoutModel.self, where: #Predicate { $0.key == key })
            }
        }
    }

    /// "Reintentar copia local": rebase the conflicted operation on the remote revision with a new idempotency key.
    public func rebaseConflict(_ scope: String, entityId: String, remoteRevision: Int, newKey: String) throws {
        try write {
            guard let pending = try fetch(#Predicate<PendingActionModel> { $0.accountScope == scope && $0.entityId == entityId && $0.status == "conflict" }).first,
                  case var .object(members) = (try? JSONValue.parse(pending.payloadJSON)) ?? .null else { return }
            members.removeAll { $0.0 == "base_revision" }
            members.append(("base_revision", .number(String(remoteRevision))))
            let payload = JSONValue.object(members)
            pending.idempotencyKey = newKey
            pending.key = scopedKey(scope, newKey)
            pending.payloadJSON = payload.encoded()
            pending.payloadHash = CanonicalJSON.sha256(payload)
            pending.status = "pending"
            pending.attemptCount = 0
            pending.notBefore = .distantPast
            pending.lastErrorCode = nil
            let conflictKey = scopedKey(scope, entityId)
            try modelContext.delete(model: PlanningConflictModel.self, where: #Predicate { $0.key == conflictKey })
            let entityKey = scopedKey(scope, entityId)
            if let workout = try fetch(#Predicate<PlanWorkoutModel> { $0.key == entityKey }).first {
                workout.syncStatus = "pending"
                try planModel(scope, workout.planPublicId)?.syncStatus = "pending"
            }
            try planModel(scope, entityId)?.syncStatus = "pending"
            try fetch(#Predicate<PlannedWorkoutModel> { $0.key == entityKey }).first?.status = "locally_pending"
        }
    }

    // MARK: Queue handler support

    public func planningEntity(_ scope: String, entityId: String) -> PlanningEntity? {
        let key = scopedKey(scope, entityId)
        if let schedule = try? fetch(#Predicate<PlannedWorkoutModel> { $0.key == key }).first {
            return .schedule(title: schedule.title, date: schedule.scheduledForDate, revision: schedule.revision)
        }
        if let workout = try? fetch(#Predicate<PlanWorkoutModel> { $0.key == key }).first { return .workout(name: workout.name, revision: workout.revision) }
        if let plan = try? fetch(#Predicate<PlanModel> { $0.key == key }).first { return .plan(name: plan.name, revision: plan.revision) }
        return nil
    }

    /// Visible sync state for the entity behind a planning action (android `markPlanningSyncStatus`).
    public func markPlanningSyncStatus(_ scope: String, action: PendingAction, status: String) throws {
        try write {
            let entityKey = scopedKey(scope, action.entityId)
            switch action.actionType {
            case "planning_plan_create", "planning_plan_patch":
                try planModel(scope, action.entityId)?.syncStatus = status
            case "planning_workout_create":
                try planModel(scope, action.entityId)?.syncStatus = status
                if let workoutId = (try? JSONValue.parse(action.payloadJSON))?["public_id"]?.stringValue {
                    let workoutKey = scopedKey(scope, workoutId)
                    try fetch(#Predicate<PlanWorkoutModel> { $0.key == workoutKey }).first?.syncStatus = status
                }
            case "planning_workout_patch":
                if let workout = try fetch(#Predicate<PlanWorkoutModel> { $0.key == entityKey }).first {
                    workout.syncStatus = status
                    try planModel(scope, workout.planPublicId)?.syncStatus = status
                }
            case "planning_schedule", "planning_schedule_patch", "planning_cancel_schedule":
                let cancel = action.actionType == "planning_cancel_schedule"
                let visible = switch status {
                case "syncing": "syncing"
                case "conflict": "conflict"
                case "synced": cancel ? "cancelled" : "planned"
                default: cancel ? "cancelled" : "locally_pending"
                }
                try fetch(#Predicate<PlannedWorkoutModel> { $0.key == entityKey }).first?.status = visible
            default:
                break
            }
        }
    }

    public func recordPlanningConflict(_ scope: String, entityId: String, conflictType: String, remoteName: String?, remoteRevision: Int?, now: Date = Date()) throws {
        guard let entity = planningEntity(scope, entityId: entityId) else { return }
        let conflict: PlanningConflictModel
        switch entity {
        case let .schedule(title, date, revision):
            conflict = PlanningConflictModel(scope: scope, entityId: entityId, entityType: "schedule", localRevision: revision, serverRevision: remoteRevision,
                                             changedFields: "\(conflictType):scheduled_for_date", localName: "\(title) · \(date)", remoteName: remoteName, createdAt: iso(now))
        case let .workout(name, revision):
            conflict = PlanningConflictModel(scope: scope, entityId: entityId, entityType: "workout", localRevision: revision, serverRevision: remoteRevision,
                                             changedFields: conflictType, localName: name, remoteName: remoteName, createdAt: iso(now))
        case let .plan(name, revision):
            conflict = PlanningConflictModel(scope: scope, entityId: entityId, entityType: "plan", localRevision: revision, serverRevision: remoteRevision,
                                             changedFields: conflictType, localName: name, remoteName: remoteName, createdAt: iso(now))
        }
        try write {
            let key = conflict.key
            try modelContext.delete(model: PlanningConflictModel.self, where: #Predicate { $0.key == key })
            modelContext.insert(conflict)
        }
    }

    public func applyScheduleResult(_ scope: String, id: String, date: String, timezone: String, status: String, revision: Int, now: Date = Date()) throws {
        try write {
            let key = scopedKey(scope, id)
            guard let planned = try fetch(#Predicate<PlannedWorkoutModel> { $0.key == key }).first else { return }
            planned.scheduledForDate = date
            planned.timezone = timezone
            planned.status = status
            planned.revision = revision
            planned.updatedAt = iso(now)
        }
    }

    public func deletePlanned(_ scope: String, id: String) throws {
        try write {
            let key = scopedKey(scope, id)
            try modelContext.delete(model: PlannedWorkoutModel.self, where: #Predicate { $0.key == key })
        }
    }

    // MARK: Helpers

    private func planModel(_ scope: String, _ publicId: String) throws -> PlanModel? {
        let key = scopedKey(scope, publicId)
        return try fetch(#Predicate<PlanModel> { $0.key == key }).first
    }

    private func pendingModel(_ scope: String, entityId: String, type: String) throws -> PendingActionModel? {
        try fetch(#Predicate<PendingActionModel> { $0.accountScope == scope && $0.entityId == entityId && $0.actionType == type },
                  sort: [SortDescriptor(\.sequence)]).first
    }

    private func dropLocalPlanningWork(_ scope: String, entityId: String) throws {
        try modelContext.delete(model: PendingActionModel.self, where: #Predicate { $0.accountScope == scope && $0.entityId == entityId })
        let key = scopedKey(scope, entityId)
        try modelContext.delete(model: PlanningConflictModel.self, where: #Predicate { $0.key == key })
    }

    private func replacePayload(_ pending: PendingActionModel, _ payload: JSONValue) throws {
        pending.payloadJSON = payload.encoded()
        pending.payloadHash = CanonicalJSON.sha256(payload)
    }

    /// Never attempted: safe to rewrite or drop without the server noticing.
    private static func untouched(_ pending: PendingActionModel) -> Bool {
        pending.attemptCount == 0 && pending.lastErrorCode == nil && pending.status == "pending"
    }

    /// The request body of a queued action (schedules wrap it under `request`).
    static func request(_ pending: PendingActionModel) -> JSONValue {
        guard let root = try? JSONValue.parse(pending.payloadJSON) else { return .null }
        return root["request"] ?? root
    }

    static func normalized(_ value: String?) -> String? {
        guard let trimmed = value?.trimmingCharacters(in: .whitespacesAndNewlines), !trimmed.isEmpty else { return nil }
        return trimmed
    }

    /// Android `workoutPatchPayload`.
    static func workoutPatchPayload(baseRevision: Int, name: String, notes: String?, exercises: [PlanExercise]) -> JSONValue {
        func text(_ key: String, _ value: String?) -> [(String, JSONValue)] { value.map { [(key, .string($0))] } ?? [] }
        func number(_ key: String, _ value: Int?) -> [(String, JSONValue)] { value.map { [(key, .number(String($0)))] } ?? [] }
        return .object([
            ("base_revision", .number(String(baseRevision))),
            ("name", .string(name)),
            ("notes", notes.map(JSONValue.string) ?? .null),
            ("exercises", .array(exercises.map { exercise in
                var members: [(String, JSONValue)] = [("id", .string(exercise.id))]
                members += text("exercise_id", exercise.exerciseId)
                members.append(("name", .string(exercise.name)))
                members += text("notes", exercise.notes)
                members.append(("sets", .array(exercise.sets.map { set in
                    var values: [(String, JSONValue)] = [("id", .string(set.id))]
                    values += number("reps", set.reps)
                    values += number("reps_min", set.repsMin)
                    values += number("reps_max", set.repsMax)
                    values += text("weight_kg", set.weightKg)
                    values += text("load_value", set.loadValue)
                    values.append(("load_unit", .string(set.loadUnit)))
                    values.append(("load_mode", .string(set.loadMode)))
                    if let details = set.loadDetailsJSON.flatMap({ try? JSONValue.parse($0) }) { values.append(("load_details", details)) }
                    values += text("rir", set.rir)
                    values += text("rpe", set.rpe)
                    values += number("rest_seconds", set.restSeconds)
                    values += number("duration_seconds", set.durationSeconds)
                    values += text("distance_m", set.distanceMeters)
                    values += text("notes", set.notes)
                    return .object(values)
                })))
                return .object(members)
            })),
        ])
    }
}
