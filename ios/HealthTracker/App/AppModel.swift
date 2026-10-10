import Foundation
import HealthTrackerKit
import Observation
import UIKit

/// App-wide session and sync state (Android `CompanionViewModel` subset).
@MainActor
@Observable
final class AppModel {
    private(set) var auth: AuthState = .authenticating
    private(set) var profile: UserProfile?
    private(set) var preferences: AppPreferences
    private(set) var connected = true
    private(set) var busy = false
    private(set) var syncStatus: SyncStatus = .idle
    private(set) var syncSnapshot = SyncSnapshot(pendingCount: 0, conflictCount: 0, hasSyncState: false)
    private(set) var planned: [PlannedWorkout] = []
    private(set) var recent: [RecentSession] = []
    var message: String?

    private let session: SessionService
    private let engine: SyncEngine
    let sync: SyncCoordinator
    let training: TrainingModel
    let workout: WorkoutModel
    private let connectivity: ConnectivityMonitor
    private var started = false

    static let appVersion = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.0.0"
    static let buildNumber = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "0"

    init(session: SessionService, engine: SyncEngine, connectivity: ConnectivityMonitor) {
        self.session = session
        self.engine = engine
        self.connectivity = connectivity
        self.sync = SyncCoordinator(session: session, engine: engine)
        self.training = TrainingModel(repository: TrainingRepository(api: session.api, store: session.store), store: session.store)
        self.workout = WorkoutModel(repository: WorkoutRepository(api: session.api, store: session.store), store: session.store)
        self.preferences = session.preferences.values
        sync.onRunFinished = { [weak self] in Task { await self?.reloadCache() } }
        sync.onSessionInvalidated = { [weak self] code in self?.sessionInvalidated(code) }
        training.context = { [weak self] in (self?.preferences.accountScope, self?.connected ?? false) }
        training.report = { [weak self] text in self?.message = text }
        workout.context = { [weak self] in
            (self?.preferences.accountScope, self?.connected ?? false, self?.preferences.deviceId ?? "")
        }
        workout.report = { [weak self] text in self?.message = text }
        workout.requestSync = { [weak self] trigger in self?.sync.enqueueNow(trigger) }
        workout.onLocalChange = { [weak self] in Task { await self?.reloadCache() } }
    }

    static func live() -> AppModel {
        let preferences = PreferenceStore()
        let tokens = TokenStore()
        // Keychain items survive app deletion; a fresh install must not inherit an old session.
        if preferences.consumeFirstLaunch() { tokens.clear() }
        let store: LocalStore
        do {
            store = try LocalStore.make()
        } catch {
            // The cache is rebuildable from the server; never block launch on it.
            store = try! LocalStore.make(inMemory: true)
        }
        let api = APIClient(preferences: preferences, tokens: tokens)
        let session = SessionService(api: api, preferences: preferences, tokens: tokens, store: store, appVersion: appVersion)
        let engine = SyncEngine(api: api, store: store, preferences: preferences, handlers: CompanionHandlers.all)
        return AppModel(session: session, engine: engine, connectivity: ConnectivityMonitor())
    }

    func start() async {
        guard !started else { return }
        started = true
        connected = connectivity.isConnected
        Task { [weak self] in await self?.observeSyncStatus() }
        let local = session.preferences.values
        if local.serverURL == nil {
            auth = .noServer
        } else if let scope = local.accountScope, let cached = await session.restoreLocalSession() {
            profile = cached
            auth = .authenticated
            await reloadCache()
            sync.schedulePeriodic()
            if connected { await restoreOnline(scope) }
        } else {
            auth = .signedOut
        }
        for await isConnected in connectivity.updates() {
            let recovered = isConnected && !connected
            connected = isConnected
            guard recovered, auth == .authenticated else { continue }
            if session.tokens.accessToken(serverIdentity: preferences.serverURL) == nil, let scope = preferences.accountScope {
                await restoreOnline(scope)
            } else {
                sync.enqueueNow(.connectivityRecovered)
            }
        }
    }

    func appBecameActive() {
        guard auth == .authenticated else { return }
        sync.enqueueNow(.foreground)
    }

    func syncNow() {
        guard auth == .authenticated else { return }
        sync.enqueueNow(.manual)
    }

    func testServer(url: String, localHTTP: Bool) {
        perform {
            _ = try await self.session.testServer(url, explicitLocalHTTP: localHTTP)
            self.message = "Conexión verificada con Health Tracker."
        }
    }

    func login(url: String, localHTTP: Bool, email: String, password: String, deviceName: String) {
        perform {
            let previous = self.auth
            self.auth = .authenticating
            do {
                let outcome = try await self.session.login(
                    rawURL: url, explicitLocalHTTP: localHTTP, email: email, password: password,
                    deviceName: deviceName, osVersion: "iOS \(UIDevice.current.systemVersion)"
                )
                self.profile = outcome.profile
                self.auth = .authenticated
                self.message = "Sesión iniciada y dispositivo registrado."
                await self.reloadCache()
                self.sync.schedulePeriodic()
                self.sync.enqueueNow(.loginBootstrap)
            } catch {
                self.auth = previous == .authenticating ? .signedOut : previous
                throw error
            }
        }
    }

    func logout(revoke: Bool = false, localOnly: Bool = false) {
        guard let scope = preferences.accountScope else { return }
        perform {
            self.sync.cancelAll()
            if localOnly {
                try await self.session.clearLocal(scope: scope)
            } else {
                try await self.session.logout(scope: scope, revokeDevice: revoke)
            }
            self.signedOut()
        }
    }

    func logoutAll() {
        guard let scope = preferences.accountScope else { return }
        perform {
            try await self.session.logoutAll(scope: scope)
            self.sync.cancelAll()
            self.signedOut()
        }
    }

    func switchServer() {
        sync.cancelAll()
        session.detachForServerSwitch()
        signedOut()
        message = "Sesión separada. Confirma la nueva URL e inicia sesión; los datos anteriores siguen aislados."
    }

    func setTheme(_ theme: ThemePreference) {
        session.preferences.setTheme(theme)
        preferences = session.preferences.values
    }

    func setUnit(_ unit: UnitPreference) {
        session.preferences.setUnit(unit)
        preferences = session.preferences.values
    }

    // MARK: Private

    private func observeSyncStatus() async {
        for await status in await engine.statusUpdates() {
            syncStatus = status
        }
    }

    private func reloadCache() async {
        preferences = session.preferences.values
        guard let scope = preferences.accountScope else {
            planned = []
            recent = []
            syncSnapshot = SyncSnapshot(pendingCount: 0, conflictCount: 0, hasSyncState: false)
            await training.reload()
            await workout.reload()
            return
        }
        planned = await session.store.plannedWorkouts(scope)
        recent = await session.store.recentSessions(scope, limit: 10)
        syncSnapshot = await session.store.snapshot(scope)
        await training.reload()
        await workout.reload()
    }

    private func signedOut() {
        profile = nil
        preferences = session.preferences.values
        auth = preferences.serverURL == nil ? .noServer : .signedOut
        Task { await reloadCache() }
    }

    private func sessionInvalidated(_ code: AppErrorCode) {
        profile = nil
        preferences = session.preferences.values
        auth = code == .deviceRevoked ? .deviceRevoked : .tokenExpired
        message = code == .deviceRevoked ? "Este dispositivo fue revocado desde el servidor." : "La sesión venció. Inicia sesión nuevamente."
        Task { await reloadCache() }
    }

    private func restoreOnline(_ scope: String) async {
        do {
            profile = try await session.restoreOnlineSession(scope: scope)
            auth = .authenticated
            sync.enqueueNow(.refreshSuccess)
        } catch {
            let decision = classifyRestoreFailure(error)
            if decision.clearLocalSession {
                try? await session.clearConfirmedInvalidSession(scope: scope)
                sync.cancelAll()
                profile = nil
            }
            auth = decision.state
            message = decision.message
        }
        await reloadCache()
    }

    private func perform(_ work: @escaping @MainActor () async throws -> Void) {
        guard !busy else { return }
        busy = true
        Task {
            defer {
                busy = false
                preferences = session.preferences.values
            }
            do {
                try await work()
            } catch let failure as AppFailure {
                message = failure.userMessage
            } catch {
                message = "No fue posible completar la operación."
            }
        }
    }
}
