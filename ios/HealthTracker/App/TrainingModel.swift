import Foundation
import HealthTrackerKit
import Observation

/// History, progress and plan state (Android `CompanionViewModel` history/progress/planning subset).
/// The cache is always shown first; a refresh failure keeps it and reports a sanitized message.
@MainActor
@Observable
final class TrainingModel {
    static let progressRanges = ["7", "30", "90", "180", "365", "all"]

    // History
    private(set) var history: [HistorySession] = []
    private(set) var historyFilters = HistoryFilters()
    private(set) var historyState: HistoryQueryState?
    private(set) var historyRefreshing = false
    private(set) var historyError: String?
    private(set) var selectedHistory: HistoryDetail?

    // Progress
    private(set) var progressRange = "30"
    private(set) var progressSummary: ProgressSummary?
    private(set) var progressExercises: [ProgressExercise] = []
    private(set) var progressRefreshing = false
    private(set) var progressError: String?
    private(set) var latestRecord: PersonalRecord?
    private(set) var selectedExercise: ProgressExercise?
    private(set) var progressPoints: [ProgressPoint] = []
    private(set) var personalRecords: [PersonalRecord] = []

    // Plans
    private(set) var plans: [TrainingPlan] = []
    private(set) var showArchivedPlans = false
    private(set) var planningRefreshing = false
    private(set) var selectedPlan: TrainingPlan?
    private(set) var planWorkouts: [PlanWorkout] = []
    private(set) var selectedPlanWorkout: PlanWorkout?

    private let repository: TrainingRepository
    private let store: LocalStore
    /// Supplies the active account scope and connectivity; set by `AppModel`.
    @ObservationIgnored var context: @MainActor () -> (scope: String?, connected: Bool) = { (nil, false) }
    /// Shows a transient message; set by `AppModel`.
    @ObservationIgnored var report: @MainActor (String) -> Void = { _ in }
    private var selectedHistoryId: String?
    private var selectedExerciseId: String?
    private var selectedPlanId: String?
    private var selectedPlanWorkoutId: String?

    init(repository: TrainingRepository, store: LocalStore) {
        self.repository = repository
        self.store = store
    }

    private var scope: String? { context().scope }
    private var connected: Bool { context().connected }

    /// Reloads every visible list from the local cache.
    func reload() async {
        guard let scope else {
            history = []; historyState = nil; selectedHistory = nil
            progressSummary = nil; progressExercises = []; latestRecord = nil
            selectedExercise = nil; progressPoints = []; personalRecords = []
            plans = []; selectedPlan = nil; planWorkouts = []; selectedPlanWorkout = nil
            return
        }
        history = await store.history(scope, cacheKey: historyFilters.cacheKey)
        historyState = await store.historyQueryState(scope, cacheKey: historyFilters.cacheKey)
        if let id = selectedHistoryId { selectedHistory = await store.historyDetail(scope, publicId: id) }
        progressSummary = await store.progressSummary(scope, range: progressRange)
        progressExercises = await store.progressExercises(scope, range: progressRange)
        latestRecord = await store.latestPersonalRecord(scope)
        if let id = selectedExerciseId {
            selectedExercise = await store.progressExercise(scope, range: progressRange, publicId: id)
            progressPoints = await store.progressPoints(scope, range: progressRange, publicId: id)
            personalRecords = await store.personalRecords(scope, range: progressRange, publicId: id)
        }
        plans = await store.plans(scope, includeArchived: showArchivedPlans)
        if let id = selectedPlanId {
            selectedPlan = await store.plan(scope, publicId: id)
            planWorkouts = await store.planWorkouts(scope, planPublicId: id)
        }
        if let id = selectedPlanWorkoutId { selectedPlanWorkout = await store.planWorkout(scope, publicId: id) }
    }

    // MARK: History

    func refreshHistory(reset: Bool = true) async {
        guard let scope, connected, !historyRefreshing else { return }
        historyRefreshing = true
        defer { historyRefreshing = false }
        do {
            try await repository.refreshHistory(scope: scope, filters: historyFilters, reset: reset)
            historyError = nil
        } catch {
            historyError = Self.message(error)
        }
        await reload()
    }

    /// Dates use `yyyy-MM-dd`; an inverted range is rejected before reaching the server.
    func setHistoryFilters(from: Date?, to: Date?, exercisePublicId: String?) async {
        let fromKey = from.map(Self.dayKey)
        let toKey = to.map(Self.dayKey)
        if let fromKey, let toKey, fromKey > toKey {
            report("La fecha inicial debe ser anterior a la final.")
            return
        }
        historyFilters = HistoryFilters(dateFrom: fromKey, dateTo: toKey, exercisePublicId: exercisePublicId)
        await reload()
        await refreshHistory()
    }

    func clearHistoryFilters() async {
        historyFilters = HistoryFilters()
        await reload()
        await refreshHistory()
    }

    func openHistory(_ publicId: String) async {
        selectedHistoryId = publicId
        selectedHistory = nil
        await reload()
        guard let scope, connected else { return }
        do {
            try await repository.refreshHistoryDetail(scope: scope, publicId: publicId)
        } catch {
            historyError = Self.message(error)
        }
        await reload()
    }

    // MARK: Progress

    func setProgressRange(_ range: String) async {
        guard Self.progressRanges.contains(range) else { return }
        progressRange = range
        await reload()
        await refreshProgress()
        if let id = selectedExerciseId { await openProgressExercise(id) }
    }

    func refreshProgress() async {
        guard let scope, connected, !progressRefreshing else { return }
        progressRefreshing = true
        defer { progressRefreshing = false }
        do {
            try await repository.refreshProgress(scope: scope, range: progressRange)
            progressError = nil
        } catch {
            progressError = Self.message(error)
        }
        await reload()
    }

    func openProgressExercise(_ publicId: String) async {
        selectedExerciseId = publicId
        await reload()
        guard let scope, connected else { return }
        do {
            try await repository.refreshProgressExercise(scope: scope, range: progressRange, publicId: publicId)
        } catch {
            progressError = Self.message(error)
        }
        await reload()
    }

    // MARK: Plans

    func refreshPlans() async {
        guard let scope, connected, !planningRefreshing else { return }
        planningRefreshing = true
        defer { planningRefreshing = false }
        do {
            try await repository.refreshPlans(scope: scope)
            if showArchivedPlans { try await repository.refreshPlans(scope: scope, status: "archived") }
        } catch {
            report(Self.message(error))
        }
        await reload()
    }

    func setShowArchivedPlans(_ show: Bool) async {
        showArchivedPlans = show
        await reload()
        if show { await refreshPlans() }
    }

    func openPlan(_ publicId: String) async {
        selectedPlanId = publicId
        await reload()
    }

    func openPlanWorkout(_ publicId: String) async {
        selectedPlanWorkoutId = publicId
        await reload()
    }

    // MARK: Helpers

    static func message(_ error: Error) -> String {
        (error as? AppFailure)?.userMessage ?? "No fue posible actualizar."
    }

    static func dayKey(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }
}
