import Foundation
import SwiftData

// MARK: Sendable snapshots

public struct HistorySession: Sendable, Equatable, Identifiable {
    public let id: String
    public let clientEventId: String
    public let plannedWorkoutId: String?
    public let name: String
    public let performedAt: String
    public let startedAt: String?
    public let completedAt: String
    public let durationSeconds: Int?
    public let exerciseCount: Int
    public let setCount: Int
    public let volumeKg: String?
    public let volumePartial: Bool
    public let source: String
    public let syncStatus: String
    public let notes: String?
    public let detailCached: Bool
}

public struct HistorySet: Sendable, Equatable, Identifiable {
    public var id: Int { setNumber }
    public let setNumber: Int
    public let weightKg: String?
    public let displayValue: String?
    public let displayUnit: String?
    public let loadMode: String
    public let reps: Int
    public let rir: String?
    public let rpe: String?
    public let restSeconds: Int?
    public let durationSeconds: String?
    public let distanceMeters: String?
    public let notes: String?
}

public struct HistoryExercise: Sendable, Equatable, Identifiable {
    public var id: Int { exerciseOrder }
    public let exerciseOrder: Int
    public let exercisePublicId: String?
    public let name: String
    public let notes: String?
    public let sets: [HistorySet]
}

public struct HistoryDetail: Sendable, Equatable {
    public let session: HistorySession
    public let exercises: [HistoryExercise]
}

public struct HistoryQueryState: Sendable, Equatable {
    public let nextCursor: String?
    public let hasMore: Bool
}

public struct ProgressSummary: Sendable, Equatable {
    public let range: String
    public let sessions: Int
    public let trainingDays: Int
    public let distinctExercises: Int
    public let completedSets: Int
    public let totalReps: Int
    public let volumeKg: String?
    public let volumePartial: Bool
    public let durationSeconds: Int
    public let hasComparison: Bool
}

public struct ProgressExercise: Sendable, Equatable, Identifiable {
    public var id: String { publicId }
    public let publicId: String
    public let name: String
    public let lastPerformedAt: String?
    public let sessionCount: Int
    public let setCount: Int
    public let bestLoadKg: String?
    public let bestReps: Int?
    public let bestRepsWeightKg: String?
    public let volumeKg: String?
    public let volumePartial: Bool
    public let loadComparable: Bool
    public let trend: String
}

public struct ProgressPoint: Sendable, Equatable, Identifiable {
    public var id: String { sessionPublicId }
    public let sessionPublicId: String
    public let date: String
    public let performedAt: String
    public let bestLoadKg: String?
    public let bestReps: Int?
    public let volumeKg: String?
    public let setCount: Int
    public let averageRir: String?
    public let averageRpe: String?
    public let loadComparable: Bool
}

public struct PersonalRecord: Sendable, Equatable, Identifiable {
    public var id: String { "\(exercisePublicId)#\(type)" }
    public let exercisePublicId: String
    public let type: String
    public let value: String
    public let unit: String
    public let date: String
    public let sessionPublicId: String
}

public struct TrainingPlan: Sendable, Equatable, Identifiable {
    public var id: String { publicId }
    public let publicId: String
    public let name: String
    public let description: String?
    public let status: String
    public let revision: Int
    public let workoutCount: Int
    public let syncStatus: String
    public let archivedAt: String?
}

public struct PlanSet: Sendable, Equatable, Identifiable {
    public let id: String
    public let setNumber: Int
    public let reps: Int?
    public let repsMin: Int?
    public let repsMax: Int?
    public let weightKg: String?
    public let loadValue: String?
    public let loadUnit: String
    public let loadMode: String
    public let loadDetailsJSON: String?
    public let rir: String?
    public let rpe: String?
    public let restSeconds: Int?
    public let durationSeconds: Int?
    public let distanceMeters: String?
    public let notes: String?
}

public struct PlanExercise: Sendable, Equatable, Identifiable {
    public let id: String
    public let exerciseId: String?
    public let name: String
    public let notes: String?
    public let exerciseOrder: Int
    public let sets: [PlanSet]
}

public struct PlanWorkout: Sendable, Equatable, Identifiable {
    public var id: String { publicId }
    public let publicId: String
    public let planPublicId: String
    public let name: String
    public let notes: String?
    public let position: Int
    public let estimatedDurationSeconds: Int?
    public let revision: Int
    public let syncStatus: String
    public let exercises: [PlanExercise]
}

/// Android `protectLocalPlanningState`: a locally edited plan is never overwritten while planning work is queued.
public func protectLocalPlanningState(_ syncStatus: String?, hasQueuedPlanningWork: Bool) -> Bool {
    hasQueuedPlanningWork && ["pending", "conflict"].contains(syncStatus ?? "")
}

// MARK: Writes and reads

extension LocalStore {
    func clearTrainingData(_ scope: String) throws {
        try modelContext.delete(model: HistorySessionModel.self, where: #Predicate { $0.accountScope == scope })
        try modelContext.delete(model: HistoryExerciseModel.self, where: #Predicate { $0.accountScope == scope })
        try modelContext.delete(model: HistorySetModel.self, where: #Predicate { $0.accountScope == scope })
        try modelContext.delete(model: HistoryPageModel.self, where: #Predicate { $0.accountScope == scope })
        try modelContext.delete(model: HistoryQueryStateModel.self, where: #Predicate { $0.accountScope == scope })
        try modelContext.delete(model: ProgressSummaryModel.self, where: #Predicate { $0.accountScope == scope })
        try modelContext.delete(model: ProgressExerciseModel.self, where: #Predicate { $0.accountScope == scope })
        try modelContext.delete(model: ProgressPointModel.self, where: #Predicate { $0.accountScope == scope })
        try modelContext.delete(model: PersonalRecordModel.self, where: #Predicate { $0.accountScope == scope })
        try modelContext.delete(model: PlanModel.self, where: #Predicate { $0.accountScope == scope })
        try modelContext.delete(model: PlanWorkoutModel.self, where: #Predicate { $0.accountScope == scope })
        try modelContext.delete(model: PlanExerciseModel.self, where: #Predicate { $0.accountScope == scope })
        try modelContext.delete(model: PlanSetModel.self, where: #Predicate { $0.accountScope == scope })
    }

    // MARK: History

    /// Applies one history page for a filter set. `reset` replaces the listing; otherwise the page is appended.
    public func applyHistoryPage(_ scope: String, cacheKey: String, page: MobileHistoryPageDTO, reset: Bool, now: Date = Date()) throws {
        try write {
            if reset {
                try modelContext.delete(model: HistoryPageModel.self, where: #Predicate { $0.accountScope == scope && $0.cacheKey == cacheKey })
            }
            let last = try fetch(
                #Predicate<HistoryPageModel> { $0.accountScope == scope && $0.cacheKey == cacheKey },
                sort: [SortDescriptor(\.position, order: .reverse)], limit: 1
            ).first
            let start = reset ? 0 : (last?.position ?? -1) + 1
            for (index, item) in page.items.enumerated() {
                let session = try historySessionModel(scope, item.publicId)
                session.name = item.name
                session.performedAt = item.performedAt
                session.completedAt = item.completedAt
                session.durationSeconds = item.durationSeconds
                session.exerciseCount = item.exerciseCount
                session.setCount = item.setCount
                session.volumeKg = item.volumeKg
                session.volumePartial = item.volumePartial
                session.source = item.source
                session.syncStatus = item.syncStatus
                session.updatedAt = iso(now)
                let pageKey = scopedKey(scope, "\(cacheKey)#\(item.publicId)")
                try modelContext.delete(model: HistoryPageModel.self, where: #Predicate { $0.key == pageKey })
                modelContext.insert(HistoryPageModel(scope: scope, cacheKey: cacheKey, sessionPublicId: item.publicId, position: start + index))
            }
            let stateKey = scopedKey(scope, cacheKey)
            try modelContext.delete(model: HistoryQueryStateModel.self, where: #Predicate { $0.key == stateKey })
            modelContext.insert(HistoryQueryStateModel(scope: scope, cacheKey: cacheKey, nextCursor: page.nextCursor, hasMore: page.hasMore, updatedAt: iso(now)))
        }
    }

    /// Replaces the full session (exercises and sets) with the server detail, keeping the local client event id.
    public func applyHistoryDetail(_ scope: String, _ detail: MobileHistoryDetailDTO, now: Date = Date()) throws {
        try write {
            let session = try historySessionModel(scope, detail.publicId)
            session.plannedWorkoutId = detail.plannedWorkoutId
            session.trainingPlanId = detail.trainingPlanId
            session.trainingPlanVersionId = detail.trainingPlanVersionId
            session.name = detail.name
            session.performedAt = detail.performedAt
            session.startedAt = detail.startedAt
            session.completedAt = detail.completedAt
            session.timezone = detail.timezone
            session.durationSeconds = detail.durationSeconds
            session.exerciseCount = detail.exerciseCount
            session.setCount = detail.setCount
            session.volumeKg = detail.volumeKg
            session.volumePartial = detail.volumePartial
            session.source = detail.source
            session.syncStatus = detail.syncStatus
            session.notes = detail.notes
            session.detailCached = true
            session.updatedAt = iso(now)
            let id = detail.publicId
            try modelContext.delete(model: HistoryExerciseModel.self, where: #Predicate { $0.accountScope == scope && $0.sessionPublicId == id })
            try modelContext.delete(model: HistorySetModel.self, where: #Predicate { $0.accountScope == scope && $0.sessionPublicId == id })
            for exercise in detail.exercises {
                modelContext.insert(HistoryExerciseModel(
                    scope: scope, sessionPublicId: id, exerciseOrder: exercise.exerciseOrder,
                    exercisePublicId: exercise.exercisePublicId, name: exercise.name, notes: exercise.notes
                ))
                for set in exercise.sets {
                    let row = HistorySetModel(scope: scope, sessionPublicId: id, exerciseOrder: exercise.exerciseOrder,
                                              setNumber: set.setNumber, loadMode: set.loadMode, reps: set.reps)
                    row.weightKg = set.weightKg
                    row.displayValue = set.displayLoad?.value
                    row.displayUnit = set.displayLoad?.unit
                    row.rir = set.rir
                    row.rpe = set.rpe
                    row.restSeconds = set.restSeconds
                    row.durationSeconds = set.durationSeconds
                    row.distanceMeters = set.distanceMeters
                    row.notes = set.notes
                    modelContext.insert(row)
                }
            }
        }
    }

    private func historySessionModel(_ scope: String, _ publicId: String) throws -> HistorySessionModel {
        let key = scopedKey(scope, publicId)
        if let existing = try fetch(#Predicate<HistorySessionModel> { $0.key == key }).first { return existing }
        let created = HistorySessionModel(scope: scope, publicId: publicId, clientEventId: publicId)
        modelContext.insert(created)
        return created
    }

    public func historyQueryState(_ scope: String, cacheKey: String) -> HistoryQueryState? {
        let key = scopedKey(scope, cacheKey)
        return (try? fetch(#Predicate<HistoryQueryStateModel> { $0.key == key }).first).map {
            HistoryQueryState(nextCursor: $0.nextCursor, hasMore: $0.hasMore)
        }
    }

    /// Sessions of one filtered listing in server order.
    public func history(_ scope: String, cacheKey: String) -> [HistorySession] {
        let pages = (try? fetch(
            #Predicate<HistoryPageModel> { $0.accountScope == scope && $0.cacheKey == cacheKey },
            sort: [SortDescriptor(\.position)]
        )) ?? []
        let ids = pages.map(\.sessionPublicId)
        let rows = (try? fetch(#Predicate<HistorySessionModel> { $0.accountScope == scope && ids.contains($0.publicId) })) ?? []
        let byId = Dictionary(rows.map { ($0.publicId, $0) }, uniquingKeysWith: { first, _ in first })
        return ids.compactMap { byId[$0].map(Self.snapshot) }
    }

    public func historyDetail(_ scope: String, publicId: String) -> HistoryDetail? {
        let key = scopedKey(scope, publicId)
        guard let session = try? fetch(#Predicate<HistorySessionModel> { $0.key == key }).first else { return nil }
        let exercises = (try? fetch(
            #Predicate<HistoryExerciseModel> { $0.accountScope == scope && $0.sessionPublicId == publicId },
            sort: [SortDescriptor(\.exerciseOrder)]
        )) ?? []
        let sets = (try? fetch(
            #Predicate<HistorySetModel> { $0.accountScope == scope && $0.sessionPublicId == publicId },
            sort: [SortDescriptor(\.exerciseOrder), SortDescriptor(\.setNumber)]
        )) ?? []
        return HistoryDetail(session: Self.snapshot(session), exercises: exercises.map { exercise in
            HistoryExercise(
                exerciseOrder: exercise.exerciseOrder, exercisePublicId: exercise.exercisePublicId, name: exercise.name, notes: exercise.notes,
                sets: sets.filter { $0.exerciseOrder == exercise.exerciseOrder }.map {
                    HistorySet(setNumber: $0.setNumber, weightKg: $0.weightKg, displayValue: $0.displayValue, displayUnit: $0.displayUnit,
                               loadMode: $0.loadMode, reps: $0.reps, rir: $0.rir, rpe: $0.rpe, restSeconds: $0.restSeconds,
                               durationSeconds: $0.durationSeconds, distanceMeters: $0.distanceMeters, notes: $0.notes)
                }
            )
        })
    }

    private static func snapshot(_ row: HistorySessionModel) -> HistorySession {
        HistorySession(id: row.publicId, clientEventId: row.clientEventId, plannedWorkoutId: row.plannedWorkoutId, name: row.name,
                       performedAt: row.performedAt, startedAt: row.startedAt, completedAt: row.completedAt,
                       durationSeconds: row.durationSeconds, exerciseCount: row.exerciseCount, setCount: row.setCount,
                       volumeKg: row.volumeKg, volumePartial: row.volumePartial, source: row.source,
                       syncStatus: row.syncStatus, notes: row.notes, detailCached: row.detailCached)
    }

    // MARK: Progress

    public func applyProgress(_ scope: String, summary: ProgressSummaryDTO, exercises: ProgressExerciseListDTO, now: Date = Date()) throws {
        try write {
            let range = summary.range
            let summaryKey = scopedKey(scope, range)
            try modelContext.delete(model: ProgressSummaryModel.self, where: #Predicate { $0.key == summaryKey })
            modelContext.insert(ProgressSummaryModel(scope: scope, dto: summary, now: iso(now)))
            try modelContext.delete(model: ProgressExerciseModel.self, where: #Predicate { $0.accountScope == scope && $0.range == range })
            for item in exercises.items {
                modelContext.insert(ProgressExerciseModel(scope: scope, range: range, dto: item, now: iso(now)))
            }
        }
    }

    public func applyProgressExercise(_ scope: String, _ detail: ProgressExerciseDetailDTO, now: Date = Date()) throws {
        try write {
            let range = detail.range
            let id = detail.exercise.publicId
            let key = scopedKey(scope, "\(range)#\(id)")
            try modelContext.delete(model: ProgressExerciseModel.self, where: #Predicate { $0.key == key })
            modelContext.insert(ProgressExerciseModel(scope: scope, range: range, dto: detail.exercise, now: iso(now)))
            try modelContext.delete(model: ProgressPointModel.self, where: #Predicate { $0.accountScope == scope && $0.range == range && $0.exercisePublicId == id })
            try modelContext.delete(model: PersonalRecordModel.self, where: #Predicate { $0.accountScope == scope && $0.range == range && $0.exercisePublicId == id })
            detail.points.forEach { modelContext.insert(ProgressPointModel(scope: scope, range: range, exercisePublicId: id, dto: $0)) }
            detail.personalRecords.forEach { modelContext.insert(PersonalRecordModel(scope: scope, range: range, exercisePublicId: id, dto: $0)) }
        }
    }

    public func progressSummary(_ scope: String, range: String) -> ProgressSummary? {
        let key = scopedKey(scope, range)
        return (try? fetch(#Predicate<ProgressSummaryModel> { $0.key == key }).first).map {
            ProgressSummary(range: $0.range, sessions: $0.sessions, trainingDays: $0.trainingDays, distinctExercises: $0.distinctExercises,
                            completedSets: $0.completedSets, totalReps: $0.totalReps, volumeKg: $0.volumeKg,
                            volumePartial: $0.volumePartial, durationSeconds: $0.durationSeconds, hasComparison: $0.hasComparison)
        }
    }

    /// Most recently performed first, then by name (Android `observeProgressExercises`).
    public func progressExercises(_ scope: String, range: String) -> [ProgressExercise] {
        let rows = (try? fetch(#Predicate<ProgressExerciseModel> { $0.accountScope == scope && $0.range == range })) ?? []
        return rows.sorted {
            ($0.lastPerformedAt ?? "", $1.name) > ($1.lastPerformedAt ?? "", $0.name)
        }.map(Self.snapshot)
    }

    public func progressExercise(_ scope: String, range: String, publicId: String) -> ProgressExercise? {
        let key = scopedKey(scope, "\(range)#\(publicId)")
        return (try? fetch(#Predicate<ProgressExerciseModel> { $0.key == key }).first).map(Self.snapshot)
    }

    public func progressPoints(_ scope: String, range: String, publicId: String) -> [ProgressPoint] {
        let rows = (try? fetch(
            #Predicate<ProgressPointModel> { $0.accountScope == scope && $0.range == range && $0.exercisePublicId == publicId },
            sort: [SortDescriptor(\.performedAt)]
        )) ?? []
        return rows.map {
            ProgressPoint(sessionPublicId: $0.sessionPublicId, date: $0.date, performedAt: $0.performedAt, bestLoadKg: $0.bestLoadKg,
                          bestReps: $0.bestReps, volumeKg: $0.volumeKg, setCount: $0.setCount, averageRir: $0.averageRir,
                          averageRpe: $0.averageRpe, loadComparable: $0.loadComparable)
        }
    }

    public func personalRecords(_ scope: String, range: String, publicId: String) -> [PersonalRecord] {
        let rows = (try? fetch(
            #Predicate<PersonalRecordModel> { $0.accountScope == scope && $0.range == range && $0.exercisePublicId == publicId },
            sort: [SortDescriptor(\.type)]
        )) ?? []
        return rows.map(Self.snapshot)
    }

    public func latestPersonalRecord(_ scope: String) -> PersonalRecord? {
        (try? fetch(#Predicate<PersonalRecordModel> { $0.accountScope == scope }, sort: [SortDescriptor(\.date, order: .reverse)], limit: 1).first)
            .map(Self.snapshot)
    }

    private static func snapshot(_ row: ProgressExerciseModel) -> ProgressExercise {
        ProgressExercise(publicId: row.publicId, name: row.name, lastPerformedAt: row.lastPerformedAt, sessionCount: row.sessionCount,
                         setCount: row.setCount, bestLoadKg: row.bestLoadKg, bestReps: row.bestReps, bestRepsWeightKg: row.bestRepsWeightKg,
                         volumeKg: row.volumeKg, volumePartial: row.volumePartial, loadComparable: row.loadComparable, trend: row.trend)
    }

    private static func snapshot(_ row: PersonalRecordModel) -> PersonalRecord {
        PersonalRecord(exercisePublicId: row.exercisePublicId, type: row.type, value: row.value, unit: row.unit,
                       date: row.date, sessionPublicId: row.sessionPublicId)
    }

    // MARK: Plans

    public func hasQueuedPlanningWork(_ scope: String) -> Bool {
        let rows = (try? fetch(#Predicate<PendingActionModel> { $0.accountScope == scope })) ?? []
        return rows.contains { $0.actionType.hasPrefix("planning_") }
    }

    /// Upserts plan summaries that are not protected by local edits; returns the ids whose detail should be refreshed.
    @discardableResult
    public func applyPlanSummaries(_ scope: String, _ list: MobilePlanListDTO) throws -> [String] {
        let queued = hasQueuedPlanningWork(scope)
        return try write {
            var refreshable: [String] = []
            for summary in list.items {
                let key = scopedKey(scope, summary.publicId)
                let local = try fetch(#Predicate<PlanModel> { $0.key == key }).first
                if protectLocalPlanningState(local?.syncStatus, hasQueuedPlanningWork: queued) { continue }
                let model = local ?? {
                    let created = PlanModel(scope: scope, publicId: summary.publicId)
                    modelContext.insert(created)
                    return created
                }()
                model.update(from: summary, syncStatus: "synced")
                refreshable.append(summary.publicId)
            }
            return refreshable
        }
    }

    /// Replaces a plan with its full server detail unless it holds unsent local edits. Returns false when skipped.
    @discardableResult
    public func applyPlan(_ scope: String, _ dto: MobilePlanDTO) throws -> Bool {
        try write {
            let key = scopedKey(scope, dto.publicId)
            let local = try fetch(#Predicate<PlanModel> { $0.key == key }).first
            if ["pending", "conflict"].contains(local?.syncStatus ?? "") { return false }
            let plan = local ?? {
                let created = PlanModel(scope: scope, publicId: dto.publicId)
                modelContext.insert(created)
                return created
            }()
            plan.update(from: dto, syncStatus: "synced")
            try deletePlanChildren(scope, planPublicId: dto.publicId)
            for workout in dto.workouts ?? [] {
                modelContext.insert(PlanWorkoutModel(scope: scope, planPublicId: dto.publicId, dto: workout))
                for exercise in workout.exercises {
                    modelContext.insert(PlanExerciseModel(scope: scope, workoutPublicId: workout.publicId, dto: exercise))
                    for set in exercise.sets {
                        modelContext.insert(PlanSetModel(scope: scope, workoutPublicId: workout.publicId, exerciseRowId: exercise.id, dto: set))
                    }
                }
            }
            return true
        }
    }

    func deletePlanChildren(_ scope: String, planPublicId: String) throws {
        let workoutIds = try fetch(#Predicate<PlanWorkoutModel> { $0.accountScope == scope && $0.planPublicId == planPublicId }).map(\.publicId)
        try modelContext.delete(model: PlanWorkoutModel.self, where: #Predicate { $0.accountScope == scope && $0.planPublicId == planPublicId })
        try modelContext.delete(model: PlanExerciseModel.self, where: #Predicate { $0.accountScope == scope && workoutIds.contains($0.workoutPublicId) })
        try modelContext.delete(model: PlanSetModel.self, where: #Predicate { $0.accountScope == scope && workoutIds.contains($0.workoutPublicId) })
    }

    public func plans(_ scope: String, includeArchived: Bool = false) -> [TrainingPlan] {
        let rows = (try? fetch(#Predicate<PlanModel> { $0.accountScope == scope }, sort: [SortDescriptor(\.name)])) ?? []
        return rows.filter { $0.status != "deleted" && (includeArchived || $0.status != "archived") }.map(Self.snapshot)
    }

    public func plan(_ scope: String, publicId: String) -> TrainingPlan? {
        let key = scopedKey(scope, publicId)
        return (try? fetch(#Predicate<PlanModel> { $0.key == key }).first).map(Self.snapshot)
    }

    /// Workouts of a plan in position order, each with its exercises and sets.
    public func planWorkouts(_ scope: String, planPublicId: String) -> [PlanWorkout] {
        let rows = (try? fetch(
            #Predicate<PlanWorkoutModel> { $0.accountScope == scope && $0.planPublicId == planPublicId },
            sort: [SortDescriptor(\.position)]
        )) ?? []
        return rows.map { planWorkoutSnapshot(scope, $0) }
    }

    public func planWorkout(_ scope: String, publicId: String) -> PlanWorkout? {
        let key = scopedKey(scope, publicId)
        return (try? fetch(#Predicate<PlanWorkoutModel> { $0.key == key }).first).map { planWorkoutSnapshot(scope, $0) }
    }

    private func planWorkoutSnapshot(_ scope: String, _ row: PlanWorkoutModel) -> PlanWorkout {
        let workoutId = row.publicId
        let exercises = (try? fetch(
            #Predicate<PlanExerciseModel> { $0.accountScope == scope && $0.workoutPublicId == workoutId },
            sort: [SortDescriptor(\.exerciseOrder)]
        )) ?? []
        let sets = (try? fetch(
            #Predicate<PlanSetModel> { $0.accountScope == scope && $0.workoutPublicId == workoutId },
            sort: [SortDescriptor(\.setNumber)]
        )) ?? []
        return PlanWorkout(
            publicId: row.publicId, planPublicId: row.planPublicId, name: row.name, notes: row.notes, position: row.position,
            estimatedDurationSeconds: row.estimatedDurationSeconds, revision: row.revision, syncStatus: row.syncStatus,
            exercises: exercises.map { exercise in
                PlanExercise(
                    id: exercise.id, exerciseId: exercise.exerciseId, name: exercise.name, notes: exercise.notes,
                    exerciseOrder: exercise.exerciseOrder,
                    sets: sets.filter { $0.exerciseRowId == exercise.id }.map {
                        PlanSet(id: $0.id, setNumber: $0.setNumber, reps: $0.reps, repsMin: $0.repsMin, repsMax: $0.repsMax,
                                weightKg: $0.weightKg, loadValue: $0.loadValue, loadUnit: $0.loadUnit, loadMode: $0.loadMode,
                                loadDetailsJSON: $0.loadDetailsJSON, rir: $0.rir, rpe: $0.rpe, restSeconds: $0.restSeconds,
                                durationSeconds: $0.durationSeconds, distanceMeters: $0.distanceMeters, notes: $0.notes)
                    }
                )
            }
        )
    }

    private static func snapshot(_ row: PlanModel) -> TrainingPlan {
        TrainingPlan(publicId: row.publicId, name: row.name, description: row.planDescription, status: row.status,
                     revision: row.revision, workoutCount: row.workoutCount, syncStatus: row.syncStatus, archivedAt: row.archivedAt)
    }
}
