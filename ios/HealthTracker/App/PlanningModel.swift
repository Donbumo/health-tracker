import Foundation
import HealthTrackerKit
import Observation

/// Plan editing, catalog, agenda and conflicts (Android `CompanionViewModel` planning subset).
/// Every change is saved locally first and queued; the queue drains on the next sync.
@MainActor
@Observable
final class PlanningModel {
    private(set) var conflicts: [PlanningConflict] = []
    private(set) var catalog: [CatalogExercise] = []
    private(set) var catalogQuery = ""
    private(set) var catalogHasMore = false
    private(set) var catalogLoading = false

    private let repository: PlanningRepository
    private let store: LocalStore
    @ObservationIgnored private var catalogTask: Task<Void, Never>?
    /// Active account scope, connectivity and the profile time zone; set by `AppModel`.
    @ObservationIgnored var context: @MainActor () -> (scope: String?, connected: Bool, timezone: String) = { (nil, false, "UTC") }
    @ObservationIgnored var report: @MainActor (String) -> Void = { _ in }
    @ObservationIgnored var requestSync: @MainActor (SyncTrigger) -> Void = { _ in }
    @ObservationIgnored var onLocalChange: @MainActor () async -> Void = {}

    init(repository: PlanningRepository, store: LocalStore) {
        self.repository = repository
        self.store = store
    }

    private var scope: String? { context().scope }

    func reload() async {
        guard let scope else { conflicts = []; catalog = []; return }
        conflicts = await store.planningConflicts(scope)
        catalog = await store.catalog(scope, query: catalogQuery)
        catalogHasMore = await store.catalogState(scope, query: catalogQuery.lowercased())?.hasMore ?? false
    }

    /// Runs a local mutation, then reloads every screen and asks for a sync.
    @discardableResult
    private func mutate<T: Sendable>(_ success: String? = nil, _ work: @MainActor (PlanningRepository, String) async throws -> T) async -> T? {
        guard let scope else { return nil }
        do {
            let result = try await work(repository, scope)
            if let success { report(success) }
            requestSync(.pendingOperation)
            await onLocalChange()
            return result
        } catch {
            report(Self.message(error))
            await onLocalChange()
            return nil
        }
    }

    // MARK: Plans

    func createPlan(name: String) async -> String? {
        await mutate("Rutina guardada en este dispositivo.") { try await $0.createPlan(scope: $1, name: name) }
    }

    func editPlan(_ plan: TrainingPlan, name: String, description: String) async {
        let normalized = description.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.trimmingCharacters(in: .whitespaces).isEmpty,
              name.trimmingCharacters(in: .whitespacesAndNewlines) != plan.name || (normalized.isEmpty ? nil : normalized) != plan.description else { return }
        await mutate { try await $0.editPlan(scope: $1, publicId: plan.publicId, name: name, description: description) }
    }

    /// Archiving requires cancelling the plan's active schedules first (Android rule).
    func archive(_ plan: TrainingPlan, planned: [PlannedWorkout]) async -> Bool {
        if planned.contains(where: { $0.planId == plan.publicId && ["planned", "locally_pending", "syncing", "in_progress"].contains($0.status) }) {
            report("Cancela las programaciones activas antes de archivar la rutina.")
            return false
        }
        return await mutate("Rutina archivada.") { try await $0.editPlan(scope: $1, publicId: plan.publicId, name: plan.name, description: plan.description, status: "archived") } != nil
    }

    func restore(_ plan: TrainingPlan) async {
        await mutate("Rutina restaurada.") { try await $0.editPlan(scope: $1, publicId: plan.publicId, name: plan.name, description: plan.description, status: "active") }
    }

    func duplicatePlan(_ plan: TrainingPlan) async -> String? {
        await mutate("Copia de la rutina guardada.") { try await $0.duplicatePlan(scope: $1, sourcePlanId: plan.publicId, name: "\(plan.name) (copia)") }
    }

    func createWorkout(planId: String, name: String) async -> String? {
        await mutate { try await $0.createWorkout(scope: $1, planId: planId, name: name) }
    }

    func duplicateWorkout(_ workoutId: String) async -> String? {
        await mutate("Entrenamiento duplicado.") { try await $0.duplicateWorkout(scope: $1, sourceWorkoutId: workoutId) }
    }

    func moveWorkout(planId: String, workoutId: String, delta: Int) async {
        await mutate { try await $0.moveWorkout(scope: $1, planId: planId, workoutId: workoutId, delta: delta) }
    }

    func saveWorkout(_ workoutId: String, name: String, notes: String, exercises: [PlanExercise]) async {
        guard !name.trimmingCharacters(in: .whitespaces).isEmpty, let scope else { return }
        do {
            if try await repository.saveWorkout(scope: scope, workoutId: workoutId, name: name, notes: notes, exercises: exercises) {
                requestSync(.pendingOperation)
                await onLocalChange()
            }
        } catch {
            report(Self.message(error))
        }
    }

    // MARK: Agenda

    func schedule(workoutId: String, date: Date) async {
        let day = TrainingModel.dayKey(date)
        await mutate("Entrenamiento programado para \(Formatters.day(day)).") {
            try await $0.schedule(scope: $1, workoutId: workoutId, date: day, timezone: self.context().timezone)
        }
    }

    func cancelSchedule(_ id: String) async {
        await mutate("Programación cancelada.") { try await $0.cancelSchedule(scope: $1, scheduledId: id) }
    }

    func reschedule(_ id: String, date: Date) async {
        let day = TrainingModel.dayKey(date)
        await mutate("Programación cambiada al \(Formatters.day(day)).") {
            try await $0.reschedule(scope: $1, scheduledId: id, date: day, timezone: self.context().timezone)
        }
    }

    func refreshSchedule() async {
        guard let scope, context().connected else { return }
        do {
            try await repository.refreshSchedule(scope: scope, today: TrainingModel.dayKey(Date()))
        } catch {
            report(Self.message(error))
        }
        await onLocalChange()
    }

    // MARK: Conflicts

    func keepRemote(_ id: String) async {
        await mutate { try await $0.keepRemote(scope: $1, entityId: id) }
    }

    func retry(_ id: String) async {
        await mutate { try await $0.retry(scope: $1, entityId: id) }
    }

    func duplicateConflict(_ id: String) async {
        await mutate("La copia local se conservó como un recurso nuevo.") { try await $0.duplicateConflict(scope: $1, entityId: id) }
    }

    // MARK: Catalog

    /// Debounced catalog search; the cached matches show immediately, offline included.
    func searchCatalog(_ query: String) {
        catalogQuery = query
        catalogTask?.cancel()
        catalogTask = Task {
            await reload()
            try? await Task.sleep(for: .milliseconds(300))
            guard !Task.isCancelled else { return }
            await loadCatalog(reset: true)
        }
    }

    func loadCatalog(reset: Bool) async {
        guard let scope, context().connected, !catalogLoading else { return }
        catalogLoading = true
        defer { catalogLoading = false }
        do {
            try await repository.refreshCatalog(scope: scope, query: catalogQuery, reset: reset)
        } catch {
            report(Self.message(error))
        }
        await reload()
    }

    static func message(_ error: Error) -> String {
        (error as? AppFailure)?.userMessage ?? "No fue posible completar la operación."
    }
}
