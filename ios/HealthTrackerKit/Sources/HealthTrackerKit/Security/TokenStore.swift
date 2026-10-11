import Foundation
import Security

/// Byte storage for secrets. Production uses the Keychain; tests use `InMemorySecureStorage`.
public protocol SecureStorage: Sendable {
    func read(_ key: String) -> Data?
    func write(_ key: String, _ value: Data) throws
    func delete(_ key: String)
    func deleteAll()
}

public struct KeychainStorage: SecureStorage {
    private let service: String

    public init(service: String = "io.healthtracker.companion.secure_session_v1") {
        self.service = service
    }

    private func query(_ key: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecUseDataProtectionKeychain as String: true,
        ]
    }

    public func read(_ key: String) -> Data? {
        var request = query(key)
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        guard SecItemCopyMatching(request as CFDictionary, &result) == errSecSuccess else { return nil }
        return result as? Data
    }

    public func write(_ key: String, _ value: Data) throws {
        // After-first-unlock so background sync can refresh; never migrates to other devices or backups.
        let attributes: [String: Any] = [
            kSecValueData as String: value,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        var status = SecItemUpdate(query(key) as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var insert = query(key)
            insert.merge(attributes) { $1 }
            status = SecItemAdd(insert as CFDictionary, nil)
        }
        guard status == errSecSuccess else {
            throw AppFailure(.localStorageError, "No fue posible guardar la sesión segura en el llavero.", retryable: false)
        }
    }

    public func delete(_ key: String) {
        SecItemDelete(query(key) as CFDictionary)
    }

    public func deleteAll() {
        let request: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecUseDataProtectionKeychain as String: true,
        ]
        SecItemDelete(request as CFDictionary)
    }
}

public final class InMemorySecureStorage: SecureStorage, @unchecked Sendable {
    private var items: [String: Data] = [:]
    private let lock = NSLock()

    public init() {}

    public func read(_ key: String) -> Data? { lock.withLock { items[key] } }
    public func write(_ key: String, _ value: Data) throws { lock.withLock { items[key] = value } }
    public func delete(_ key: String) { _ = lock.withLock { items.removeValue(forKey: key) } }
    public func deleteAll() { lock.withLock { items.removeAll() } }
}

/// Session tokens bound to one server identity. The access token stays in memory only;
/// the refresh token lives in the Keychain. `mutationVersion` lets concurrent flows detect
/// that the session changed underneath them (same contract as Android `SecureTokenStore`).
public final class TokenStore: @unchecked Sendable {
    private let storage: SecureStorage
    private let lock = NSRecursiveLock()
    private var access: String?
    private var version: Int64 = 0

    public init(storage: SecureStorage = KeychainStorage()) {
        self.storage = storage
    }

    public func accessToken(serverIdentity: String? = nil) -> String? {
        lock.withLock { identityMatches(serverIdentity) ? access : nil }
    }

    public func refreshToken(serverIdentity: String? = nil) -> String? {
        lock.withLock {
            guard identityMatches(serverIdentity), let data = storage.read(Keys.refresh) else { return nil }
            return String(data: data, encoding: .utf8)
        }
    }

    public var mutationVersion: Int64 { lock.withLock { version } }

    public func setTokens(access: String, refresh: String, serverIdentity: String? = nil) throws {
        try lock.withLock {
            try storage.write(Keys.refresh, Data(refresh.utf8))
            if let serverIdentity {
                try storage.write(Keys.serverIdentity, Data(serverIdentity.utf8))
            } else {
                storage.delete(Keys.serverIdentity)
            }
            self.access = access
            version += 1
        }
    }

    public func replaceTokensIfVersion(_ expected: Int64, access: String, refresh: String, serverIdentity: String) throws -> Bool {
        try lock.withLock {
            guard version == expected else { return false }
            try setTokens(access: access, refresh: refresh, serverIdentity: serverIdentity)
            return true
        }
    }

    public func clear() {
        lock.withLock {
            access = nil
            storage.deleteAll()
            version += 1
        }
    }

    @discardableResult
    public func clearIfVersion(_ expected: Int64) -> Bool {
        lock.withLock {
            guard version == expected else { return false }
            clear()
            return true
        }
    }

    private func identityMatches(_ expected: String?) -> Bool {
        guard let expected else { return true }
        return storage.read(Keys.serverIdentity).flatMap { String(data: $0, encoding: .utf8) } == expected
    }

    private enum Keys {
        static let refresh = "refresh_token"
        static let serverIdentity = "server_identity"
    }
}
