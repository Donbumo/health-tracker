import Foundation

public enum SyncStatus: String, Sendable, Equatable {
    case idle, syncing, pending, conflict, error
}

/// Executes one queued operation against the server. Feature stages register handlers by action type
/// (`companion_*`, `planning_*`, `health_*`). Throwing a retryable `AppFailure` backs the action off;
/// a non-retryable one parks it as a conflict that blocks the FIFO queue until resolved.
public protocol PendingActionHandler: Sendable {
    func handle(_ action: PendingAction, scope: String, api: APIClient, store: LocalStore) async throws
}

/// Mobile Sync orchestration (android `CompanionRepository.synchronize`): drain the strict-FIFO
/// pending queue, bootstrap if there is no cursor, pull pages, then verify the server's device state.
public actor SyncEngine {
    private let api: APIClient
    private let store: LocalStore
    private let preferences: PreferenceStore
    private var handlers: [String: PendingActionHandler] = [:]
    private var running: Task<Void, Error>?
    private let now: @Sendable () -> Date
    private let jitter: @Sendable (Int64) -> Int64

    public private(set) var status: SyncStatus = .idle
    private var statusContinuations: [UUID: AsyncStream<SyncStatus>.Continuation] = [:]

    static let maxPullPages = 20
    static let pullPageSize = 100
    static let maxActionsPerRun = 100

    public init(
        api: APIClient,
        store: LocalStore,
        preferences: PreferenceStore,
        now: @escaping @Sendable () -> Date = Date.init,
        jitter: @escaping @Sendable (Int64) -> Int64 = { Int64.random(in: 0...max(0, $0)) }
    ) {
        self.api = api
        self.store = store
        self.preferences = preferences
        self.now = now
        self.jitter = jitter
    }

    public func register(_ handler: PendingActionHandler, for actionType: String) {
        handlers[actionType] = handler
    }

    public func statusUpdates() -> AsyncStream<SyncStatus> {
        AsyncStream { continuation in
            let id = UUID()
            statusContinuations[id] = continuation
            continuation.yield(status)
            continuation.onTermination = { [weak self] _ in
                Task { await self?.removeContinuation(id) }
            }
        }
    }

    private func removeContinuation(_ id: UUID) { statusContinuations.removeValue(forKey: id) }

    private func publish(_ value: SyncStatus) {
        status = value
        statusContinuations.values.forEach { $0.yield(value) }
    }

    /// Concurrent callers join the active run and share its outcome instead of starting another pull.
    public func synchronize(scope: String) async throws {
        if let running {
            try await running.value
            return
        }
        let task = Task { try await self.runLocked(scope: scope) }
        running = task
        defer { running = nil }
        try await task.value
    }

    private func runLocked(scope: String) async throws {
        publish(.syncing)
        do {
            try await processPending(scope: scope)
            try await pull(scope: scope)
            preferences.setLastSyncAt(ISO8601DateFormatter().string(from: now()))
            let snapshot = await store.snapshot(scope)
            publish(snapshot.conflictCount > 0 ? .conflict : snapshot.pendingCount > 0 ? .pending : .idle)
        } catch let failure as AppFailure {
            let snapshot = await store.snapshot(scope)
            publish(snapshot.conflictCount > 0 ? .conflict : (failure.retryable || snapshot.pendingCount > 0) ? .pending : .error)
            throw failure
        } catch {
            publish(.error)
            throw error
        }
    }

    // MARK: Push (strict FIFO)

    private func processPending(scope: String) async throws {
        for _ in 0..<Self.maxActionsPerRun {
            guard let action = await store.headOfQueue(scope) else { return }
            // A conflicted or backed-off head blocks later operations: required transitions keep their order.
            if action.status == "conflict" || action.notBefore > now() { return }
            guard let handler = handlers[action.actionType] else {
                try await store.markPendingConflict(action.key, errorCode: "unsupported_action")
                throw AppFailure(.localStorageError, "Esta versión no reconoce una operación pendiente.", retryable: false)
            }
            do {
                try await handler.handle(action, scope: scope, api: api, store: store)
                try await store.completePending(action.key)
            } catch let failure as AppFailure {
                if failure.retryable {
                    let delay = failure.retryAfterSeconds.map { $0 * 1000 } ?? backoffMillis(attempt: action.attemptCount + 1)
                    try await store.reschedulePending(action.key, errorCode: failure.code.rawValue, notBefore: now().addingTimeInterval(Double(delay) / 1000))
                } else {
                    try await store.markPendingConflict(action.key, errorCode: failure.code.rawValue)
                }
                throw failure
            }
        }
    }

    /// True when the queue head can be attempted now (used to decide whether another run is needed).
    public func hasReadyPending(scope: String) async -> Bool {
        guard let head = await store.headOfQueue(scope) else { return false }
        return head.status == "pending" && head.notBefore <= now()
    }

    /// 15 s × 2^attempt (attempt capped at 8) plus up to 25 % jitter, never above 6 h.
    public func backoffMillis(attempt: Int) -> Int64 {
        let base = 15_000 * (Int64(1) << Int64(min(attempt, 8)))
        return min(6 * 60 * 60 * 1000, base + jitter(base / 4))
    }

    // MARK: Pull

    private func pull(scope: String) async throws {
        let deviceId = preferences.values.deviceId
        if await store.syncCursor(scope) == nil {
            let bootstrap = try await api.bootstrap()
            try SyncContract.verify(bootstrap)
            try await store.applyBootstrap(scope, bootstrap, now: now())
        }
        guard var cursor = await store.syncCursor(scope) else { return }
        var pages = 0
        while true {
            let page = try await api.pull(cursor: cursor, limit: Self.pullPageSize)
            try await store.applyPullPage(scope, page, deviceId: deviceId, now: now())
            cursor = page.nextCursor
            pages += 1
            if !page.hasMore || pages >= Self.maxPullPages { break }
        }
        let remote = try await api.syncStatus()
        guard remote.schemaVersion == contractVersion, remote.deviceId == deviceId else {
            throw AppFailure(.schemaIncompatible, "El estado de sync no corresponde a este dispositivo.", retryable: false)
        }
    }
}

// MARK: Trigger policy

public enum SyncTrigger: Sendable {
    case loginBootstrap, downloadAck, pendingOperation, refreshSuccess, manual, connectivityRecovered, foreground, background

    /// Durable-work triggers are never throttled; ambient ones are coalesced.
    public var urgent: Bool {
        switch self {
        case .loginBootstrap, .downloadAck, .pendingOperation, .refreshSuccess, .manual: true
        case .connectivityRecovered, .foreground, .background: false
        }
    }
}

public func shouldEnqueueSync(_ trigger: SyncTrigger, lastAmbientAt: TimeInterval?, now: TimeInterval, minimumInterval: TimeInterval) -> Bool {
    guard !trigger.urgent, let lastAmbientAt else { return true }
    return now - lastAmbientAt >= minimumInterval
}
