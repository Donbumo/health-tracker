import Foundation

/// History, progress and plan refreshes (android `CompanionRepository.refreshHistory…refreshPlan`).
/// Every refresh verifies the 1.0 contract before touching the cache, so an incompatible
/// response never replaces data the user can still read offline.
public struct TrainingRepository: Sendable {
    private let api: APIClient
    private let store: LocalStore
    private let now: @Sendable () -> Date

    public init(api: APIClient, store: LocalStore, now: @escaping @Sendable () -> Date = Date.init) {
        self.api = api
        self.store = store
        self.now = now
    }

    public func refreshHistory(scope: String, filters: HistoryFilters = HistoryFilters(), reset: Bool = true) async throws {
        let state = reset ? nil : await store.historyQueryState(scope, cacheKey: filters.cacheKey)
        if !reset, state?.hasMore == false { return }
        let page = try await api.history(
            cursor: state?.nextCursor, dateFrom: filters.dateFrom, dateTo: filters.dateTo, exercisePublicId: filters.exercisePublicId
        )
        guard page.schemaVersion == contractVersion else {
            throw AppFailure(.schemaIncompatible, "El historial usa una versión incompatible.", retryable: false)
        }
        try await store.applyHistoryPage(scope, cacheKey: filters.cacheKey, page: page, reset: reset, now: now())
    }

    public func refreshHistoryDetail(scope: String, publicId: String) async throws {
        let detail = try await api.historyDetail(publicId)
        guard detail.schemaVersion == contractVersion, detail.publicId == publicId else {
            throw AppFailure(.schemaIncompatible, "El detalle de historial no corresponde a la sesión.", retryable: false)
        }
        try await store.applyHistoryDetail(scope, detail, now: now())
    }

    public func refreshProgress(scope: String, range: String) async throws {
        let summary = try await api.progressSummary(range: range)
        let exercises = try await api.progressExercises(range: range)
        guard summary.schemaVersion == contractVersion, exercises.schemaVersion == contractVersion,
              summary.range == range, exercises.range == range else {
            throw AppFailure(.schemaIncompatible, "El progreso usa un contrato incompatible.", retryable: false)
        }
        try await store.applyProgress(scope, summary: summary, exercises: exercises, now: now())
    }

    public func refreshProgressExercise(scope: String, range: String, publicId: String) async throws {
        let detail = try await api.progressExercise(publicId, range: range)
        guard detail.schemaVersion == contractVersion, detail.range == range, detail.exercise.publicId == publicId else {
            throw AppFailure(.schemaIncompatible, "El detalle de progreso no corresponde al ejercicio.", retryable: false)
        }
        try await store.applyProgressExercise(scope, detail, now: now())
    }

    /// Refreshes the plan list for a status (`active` or `archived`) and the detail of every unprotected plan.
    public func refreshPlans(scope: String, status: String = "active") async throws {
        let list = try await api.plans(status: status)
        let refreshable = try await store.applyPlanSummaries(scope, list)
        for publicId in refreshable {
            try await refreshPlan(scope: scope, publicId: publicId)
        }
    }

    public func refreshPlan(scope: String, publicId: String) async throws {
        let plan = try await api.plan(publicId)
        guard plan.publicId == publicId else {
            throw AppFailure(.schemaIncompatible, "La rutina recibida no corresponde a la solicitada.", retryable: false)
        }
        try await store.applyPlan(scope, plan)
    }
}
