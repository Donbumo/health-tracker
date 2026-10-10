import Foundation

public enum ThemePreference: String, Sendable, CaseIterable { case system = "SYSTEM", light = "LIGHT", dark = "DARK" }
public enum UnitPreference: String, Sendable, CaseIterable { case kg = "KG", lb = "LB" }

public struct AppPreferences: Sendable, Equatable {
    public var serverURL: String?
    public var allowLocalHTTP: Bool
    public var deviceId: String
    public var accountScope: String?
    public var offlineSessionEligible: Bool
    public var theme: ThemePreference
    public var unit: UnitPreference
    public var lastSyncAt: String?
}

/// Non-secret app preferences. Tokens never live here (see `TokenStore`).
public final class PreferenceStore: @unchecked Sendable {
    private let defaults: UserDefaults
    private let lock = NSLock()

    public init(defaults: UserDefaults = UserDefaults(suiteName: "companion_preferences_v1") ?? .standard) {
        self.defaults = defaults
    }

    public var values: AppPreferences {
        lock.withLock {
            let scope = defaults.string(forKey: Keys.accountScope)
            return AppPreferences(
                serverURL: defaults.string(forKey: Keys.serverURL),
                allowLocalHTTP: defaults.bool(forKey: Keys.allowLocalHTTP),
                deviceId: defaults.string(forKey: Keys.deviceId) ?? "",
                accountScope: scope,
                offlineSessionEligible: defaults.object(forKey: Keys.offlineSessionEligible) as? Bool ?? (scope != nil),
                theme: defaults.string(forKey: Keys.theme).flatMap(ThemePreference.init(rawValue:)) ?? .system,
                unit: defaults.string(forKey: Keys.unit).flatMap(UnitPreference.init(rawValue:)) ?? .kg,
                lastSyncAt: defaults.string(forKey: Keys.lastSyncAt)
            )
        }
    }

    /// True the first time the app runs after install. Keychain items survive reinstalls on iOS,
    /// so callers use this to drop tokens that belong to a previous installation.
    public func consumeFirstLaunch() -> Bool {
        lock.withLock {
            if defaults.bool(forKey: Keys.installMarker) { return false }
            defaults.set(true, forKey: Keys.installMarker)
            return true
        }
    }

    public func ensureDeviceId() -> String {
        lock.withLock {
            if let current = defaults.string(forKey: Keys.deviceId), !current.isEmpty { return current }
            let generated = UUID().uuidString.lowercased()
            defaults.set(generated, forKey: Keys.deviceId)
            return generated
        }
    }

    public func configureServer(_ url: String, allowLocalHTTP: Bool) {
        lock.withLock {
            defaults.set(url, forKey: Keys.serverURL)
            defaults.set(allowLocalHTTP, forKey: Keys.allowLocalHTTP)
        }
    }

    public func setAccountScope(_ scope: String?) {
        lock.withLock {
            if let scope { defaults.set(scope, forKey: Keys.accountScope) } else { defaults.removeObject(forKey: Keys.accountScope) }
        }
    }

    public func setOfflineSessionEligible(_ eligible: Bool) {
        lock.withLock { defaults.set(eligible, forKey: Keys.offlineSessionEligible) }
    }

    public func setTheme(_ value: ThemePreference) {
        lock.withLock { defaults.set(value.rawValue, forKey: Keys.theme) }
    }

    public func setUnit(_ value: UnitPreference) {
        lock.withLock { defaults.set(value.rawValue, forKey: Keys.unit) }
    }

    public func setLastSyncAt(_ value: String) {
        lock.withLock { defaults.set(value, forKey: Keys.lastSyncAt) }
    }

    private enum Keys {
        static let serverURL = "server_url"
        static let allowLocalHTTP = "allow_local_http"
        static let deviceId = "device_id"
        static let accountScope = "account_scope"
        static let offlineSessionEligible = "offline_session_eligible"
        static let theme = "theme"
        static let unit = "unit"
        static let lastSyncAt = "last_sync_at"
        static let installMarker = "install_marker_v1"
    }
}
