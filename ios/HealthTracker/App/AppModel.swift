import Foundation
import HealthTrackerKit
import Observation
import UIKit

/// App-wide session state (Android `CompanionViewModel` auth subset).
@MainActor
@Observable
final class AppModel {
    private(set) var auth: AuthState = .authenticating
    private(set) var profile: UserProfile?
    private(set) var preferences: AppPreferences
    private(set) var connected = true
    private(set) var busy = false
    var message: String?

    private let session: SessionService
    private let connectivity: ConnectivityMonitor
    private var started = false

    static let appVersion = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.0.0"
    static let buildNumber = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "0"

    init(session: SessionService, connectivity: ConnectivityMonitor) {
        self.session = session
        self.connectivity = connectivity
        self.preferences = session.preferences.values
    }

    static func live() -> AppModel {
        let preferences = PreferenceStore()
        let tokens = TokenStore()
        // Keychain items survive app deletion; a fresh install must not inherit an old session.
        if preferences.consumeFirstLaunch() { tokens.clear() }
        let api = APIClient(preferences: preferences, tokens: tokens)
        let session = SessionService(
            api: api, preferences: preferences, tokens: tokens,
            accounts: UserDefaultsAccountStore(), appVersion: appVersion
        )
        return AppModel(session: session, connectivity: ConnectivityMonitor())
    }

    func start() async {
        guard !started else { return }
        started = true
        connected = connectivity.isConnected
        let local = session.preferences.values
        if local.serverURL == nil {
            auth = .noServer
        } else if let scope = local.accountScope, let cached = session.restoreLocalSession() {
            profile = cached
            auth = .authenticated
            if connected { await restoreOnline(scope) }
        } else {
            auth = .signedOut
        }
        for await isConnected in connectivity.updates() {
            let recovered = isConnected && !connected
            connected = isConnected
            if recovered, auth == .authenticated, profile?.role == "offline_cache",
               let scope = session.preferences.values.accountScope {
                await restoreOnline(scope)
            }
        }
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
            } catch {
                self.auth = previous == .authenticating ? .signedOut : previous
                throw error
            }
        }
    }

    func logout(revoke: Bool = false, localOnly: Bool = false) {
        guard let scope = preferences.accountScope else { return }
        perform {
            if localOnly {
                try self.session.clearLocal(scope: scope)
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
            self.signedOut()
        }
    }

    func switchServer() {
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

    private func signedOut() {
        profile = nil
        preferences = session.preferences.values
        auth = preferences.serverURL == nil ? .noServer : .signedOut
    }

    private func restoreOnline(_ scope: String) async {
        do {
            profile = try await session.restoreOnlineSession(scope: scope)
            auth = .authenticated
        } catch {
            let decision = classifyRestoreFailure(error)
            if decision.clearLocalSession {
                try? session.clearConfirmedInvalidSession(scope: scope)
                profile = nil
            }
            auth = decision.state
            message = decision.message
        }
        preferences = session.preferences.values
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
