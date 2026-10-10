import BackgroundTasks
import Foundation
import HealthTrackerKit

/// Schedules and runs sync (android `SyncScheduler` + `SyncWorker`). Foreground triggers run
/// immediately; `BGAppRefreshTask` keeps the cache fresh roughly every 15 minutes when iOS allows it.
@MainActor
final class SyncCoordinator {
    nonisolated static let backgroundTaskId = "io.healthtracker.companion.sync"
    private static let ambientMinimumInterval: TimeInterval = 5
    private static let periodicInterval: TimeInterval = 15 * 60

    private let session: SessionService
    private let engine: SyncEngine
    private var running: Task<Bool, Never>?
    private var generation = 0
    private var lastAmbientAt: TimeInterval?

    /// Called with the failure code when the server definitively invalidated the session.
    var onSessionInvalidated: ((AppErrorCode) -> Void)?
    /// Called after every run so the UI can reload cached data.
    var onRunFinished: (() -> Void)?

    init(session: SessionService, engine: SyncEngine) {
        self.session = session
        self.engine = engine
    }

    /// Must run before the app finishes launching.
    nonisolated static func registerBackgroundTask(_ coordinator: @escaping @MainActor () -> SyncCoordinator?) {
        BGTaskScheduler.shared.register(forTaskWithIdentifier: backgroundTaskId, using: nil) { task in
            let refresh = BackgroundTaskBox(task)
            Task { @MainActor in
                guard let coordinator = coordinator() else { refresh.complete(true); return }
                coordinator.schedulePeriodic()
                let work = Task { await coordinator.runWorker() }
                refresh.onExpiration { work.cancel() }
                refresh.complete(await work.value)
            }
        }
    }

    func schedulePeriodic() {
        let request = BGAppRefreshTaskRequest(identifier: Self.backgroundTaskId)
        request.earliestBeginDate = Date(timeIntervalSinceNow: Self.periodicInterval)
        try? BGTaskScheduler.shared.submit(request)
    }

    func cancelAll() {
        BGTaskScheduler.shared.cancel(taskRequestWithIdentifier: Self.backgroundTaskId)
        running?.cancel()
        running = nil
    }

    func enqueueNow(_ trigger: SyncTrigger) {
        let now = ProcessInfo.processInfo.systemUptime
        guard shouldEnqueueSync(trigger, lastAmbientAt: lastAmbientAt, now: now, minimumInterval: Self.ambientMinimumInterval) else { return }
        if !trigger.urgent { lastAmbientAt = now }
        generation += 1
        guard running == nil else { return } // the active run re-checks `generation` before finishing
        running = Task {
            let result = await runWorker()
            running = nil
            return result
        }
    }

    /// One worker pass: up to three sync rounds while new triggers or ready work keep arriving.
    @discardableResult
    func runWorker() async -> Bool {
        let local = session.preferences.values
        guard let scope = local.accountScope, local.offlineSessionEligible else { return true }
        defer { onRunFinished?() }
        do {
            var observed = generation
            for _ in 0..<3 {
                try Task.checkCancellation()
                if session.tokens.accessToken(serverIdentity: local.serverURL) == nil {
                    _ = try await session.restoreOnlineSession(scope: scope)
                }
                try await engine.synchronize(scope: scope)
                if generation == observed, await !engine.hasReadyPending(scope: scope) { return true }
                observed = generation
            }
            return true
        } catch let failure as AppFailure where failure.code == .deviceRevoked || failure.code == .refreshFailed {
            try? await session.clearConfirmedInvalidSession(scope: scope)
            cancelAll()
            onSessionInvalidated?(failure.code)
            return false
        } catch {
            return false
        }
    }
}

/// `BGTask` is not `Sendable`, but its completion and expiration APIs are documented as thread-safe.
private final class BackgroundTaskBox: @unchecked Sendable {
    private let task: BGTask
    init(_ task: BGTask) { self.task = task }
    func complete(_ success: Bool) { task.setTaskCompleted(success: success) }
    func onExpiration(_ handler: @escaping @Sendable () -> Void) { task.expirationHandler = handler }
}
