import Foundation
import HealthTrackerKit
import Observation

/// Live workout state (Android `CompanionViewModel` workout subset): downloads, the active draft,
/// debounced autosave and the final complete/abort operations.
@MainActor
@Observable
final class WorkoutModel {
    enum AutosaveCommand: Sendable {
        case set(DraftSet)
        case summary(deliveryId: String, heartRate: Int?, calories: String?, notes: String?)

        var key: String {
            switch self {
            case let .set(value): "set:\(value.deliveryId):\(value.exerciseOrder):\(value.setNumber)"
            case let .summary(deliveryId, _, _, _): "summary:\(deliveryId)"
            }
        }
    }

    private(set) var draft: WorkoutDraft?
    private(set) var exercises: [PackageExerciseInfo] = []
    private(set) var sets: [DraftSet] = []
    private(set) var packages: [WorkoutPackageInfo] = []
    private(set) var downloading: String?
    private(set) var starting = false
    private(set) var finalActionInProgress = false
    private(set) var setActions: Set<String> = []
    private(set) var autosaveState: AutosaveState = .saved
    var presented = false

    private let repository: WorkoutRepository
    private let store: LocalStore
    @ObservationIgnored private var autosave: DebouncedAutosave<AutosaveCommand>!
    /// Active account scope, connectivity and device id; set by `AppModel`.
    @ObservationIgnored var context: @MainActor () -> (scope: String?, connected: Bool, deviceId: String) = { (nil, false, "") }
    @ObservationIgnored var report: @MainActor (String) -> Void = { _ in }
    /// Asks the sync coordinator to drain the queue now.
    @ObservationIgnored var requestSync: @MainActor (SyncTrigger) -> Void = { _ in }
    /// Reloads the rest of the app (planned workouts, history) after a local change.
    @ObservationIgnored var onLocalChange: @MainActor () -> Void = {}

    init(repository: WorkoutRepository, store: LocalStore) {
        self.repository = repository
        self.store = store
        autosave = DebouncedAutosave(
            persist: { [repository, weak self] command in
                guard let scope = await self?.context().scope else { return }
                switch command {
                case let .set(value): try await repository.saveSet(scope: scope, value)
                case let .summary(deliveryId, heartRate, calories, notes):
                    try await repository.updateSummary(scope: scope, deliveryId: deliveryId, heartRate: heartRate, calories: calories, notes: notes)
                }
            },
            onSettled: { [weak self] error in
                await self?.autosaveSettled(error)
            }
        )
    }

    private var scope: String? { context().scope }

    func reload() async {
        guard let scope else {
            draft = nil; exercises = []; sets = []; packages = []; presented = false
            return
        }
        packages = await store.packages(scope)
        draft = await store.activeDraft(scope)
        if let draft {
            exercises = await store.packageExercises(scope, packageId: draft.packageId)
            sets = await store.draftSets(scope, deliveryId: draft.deliveryId)
        } else {
            exercises = []
            sets = []
            presented = false
        }
    }

    func package(forPlanned plannedId: String) -> WorkoutPackageInfo? {
        packages.first { $0.plannedWorkoutId == plannedId }
    }

    // MARK: Download and start

    func download(_ plannedId: String) async {
        guard let scope, downloading == nil else { return }
        downloading = plannedId
        defer { downloading = nil }
        do {
            _ = try await repository.downloadWorkout(scope: scope, plannedId: plannedId)
            report("Entrenamiento descargado y verificado.")
            requestSync(.downloadAck)
        } catch {
            report(Self.message(error))
        }
        await reload()
        onLocalChange()
    }

    func start(_ plannedId: String) async {
        guard let scope, !starting, let package = package(forPlanned: plannedId) else { return }
        starting = true
        defer { starting = false }
        do {
            _ = try await repository.startWorkout(scope: scope, deliveryId: package.deliveryId, deviceId: context().deviceId)
            report("Entrenamiento listo para uso offline.")
            requestSync(.pendingOperation)
            await reload()
            presented = true
        } catch {
            report(Self.message(error))
            await reload()
        }
    }

    /// Re-validates the active draft before showing it again.
    func resume() async {
        guard let scope, let current = draft else { return }
        _ = try? await store.validateDraft(scope, deliveryId: current.deliveryId, currentScope: scope, deviceId: context().deviceId)
        await reload()
        presented = true
    }

    // MARK: Capture

    func queueSave(_ value: DraftSet) {
        autosaveState = .saving
        let command = AutosaveCommand.set(value)
        Task { await autosave.submit(key: command.key, value: command) }
    }

    func queueSummary(heartRate: Int?, calories: String?, notes: String?) {
        guard let draft else { return }
        autosaveState = .saving
        let command = AutosaveCommand.summary(deliveryId: draft.deliveryId, heartRate: heartRate, calories: calories, notes: notes)
        Task { await autosave.submit(key: command.key, value: command) }
    }

    func flush() async {
        do {
            try await autosave.flush()
        } catch {
            autosaveState = .error
        }
    }

    func complete(_ value: DraftSet) async {
        guard let scope else { return }
        let key = "complete:\(value.id)"
        guard !setActions.contains(key) else { return }
        setActions.insert(key)
        defer { setActions.remove(key) }
        await autosave.discard(key: AutosaveCommand.set(value).key)
        var completed = value
        completed.completed = true
        do {
            if try await repository.checkpointSet(scope: scope, completed) { requestSync(.pendingOperation) }
        } catch {
            report(Self.message(error))
        }
        await reload()
    }

    func duplicate(_ value: DraftSet) async {
        guard let scope else { return }
        let key = "duplicate:\(value.id)"
        guard !setActions.contains(key) else { return }
        setActions.insert(key)
        defer { setActions.remove(key) }
        await flush()
        do { try await repository.duplicateSet(scope: scope, value) } catch { report(Self.message(error)) }
        await reload()
    }

    func copyLoad(from source: DraftSet, to target: DraftSet) async {
        guard let scope else { return }
        var updated = target
        updated.weightKg = source.weightKg
        updated.loadDetailsJSON = source.loadDetailsJSON
        do { try await repository.saveSet(scope: scope, updated) } catch { report(Self.message(error)) }
        await reload()
    }

    func pauseOrResume() async {
        guard let scope, let draft else { return }
        await flush()
        do {
            if try await repository.pauseOrResume(scope: scope, deliveryId: draft.deliveryId, pause: draft.status != "paused") {
                requestSync(.pendingOperation)
            }
        } catch {
            report(Self.message(error))
        }
        await reload()
    }

    func finish(abort: Bool) async {
        guard let scope, let draft, !finalActionInProgress else { return }
        finalActionInProgress = true
        defer { finalActionInProgress = false }
        await flush()
        do {
            let queued = abort
                ? try await repository.abortWorkout(scope: scope, deliveryId: draft.deliveryId)
                : try await repository.completeWorkout(scope: scope, deliveryId: draft.deliveryId)
            if queued { requestSync(.pendingOperation) }
            report(abort ? "Cancelación pendiente de confirmar con el servidor." : "Finalización guardada; se enviará una sola vez al recuperar conexión.")
            presented = false
        } catch {
            report(Self.message(error))
        }
        await reload()
        onLocalChange()
    }

    func discardCorrupt() async {
        guard let scope, let draft else { return }
        do {
            try await repository.discardCorruptDraft(scope: scope, deliveryId: draft.deliveryId)
            report("El borrador corrupto se descartó sin enviar su contenido.")
            presented = false
        } catch {
            report(Self.message(error))
        }
        await reload()
        onLocalChange()
    }

    // MARK: Private

    private func autosaveSettled(_ error: Error?) async {
        if let error {
            autosaveState = .error
            report(Self.message(error))
        } else {
            autosaveState = context().connected ? .saved : .savedLocal
        }
        await reload()
    }

    static func message(_ error: Error) -> String {
        if let failure = error as? AppFailure { return failure.userMessage }
        if let load = error as? LoadValidationError { return load.message }
        return "No fue posible completar la operación."
    }
}
