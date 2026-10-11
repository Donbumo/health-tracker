import Foundation

/// Local identity of a signed-in account, isolated by `scope` (server identity + user UUID).
public struct AccountRecord: Codable, Sendable, Equatable {
    public let scope: String
    public let serverURL: String
    public let userPublicId: String
    public let displayEmail: String
    public let deviceId: String
    public let timezone: String
    public let createdAt: String

    public init(scope: String, serverURL: String, userPublicId: String, displayEmail: String, deviceId: String, timezone: String, createdAt: String) {
        self.scope = scope
        self.serverURL = serverURL
        self.userPublicId = userPublicId
        self.displayEmail = displayEmail
        self.deviceId = deviceId
        self.timezone = timezone
        self.createdAt = createdAt
    }
}

public protocol AccountStore: Sendable {
    func account(_ scope: String) -> AccountRecord?
    func upsert(_ account: AccountRecord) throws
    func clearAccountData(_ scope: String) throws
}

/// Stage 1 store. Stage 2 replaces it with the SwiftData offline cache, keeping this protocol.
public final class UserDefaultsAccountStore: AccountStore, @unchecked Sendable {
    private let defaults: UserDefaults
    private let lock = NSLock()

    public init(defaults: UserDefaults = UserDefaults(suiteName: "companion_accounts_v1") ?? .standard) {
        self.defaults = defaults
    }

    public func account(_ scope: String) -> AccountRecord? {
        lock.withLock {
            defaults.data(forKey: key(scope)).flatMap { try? JSONDecoder().decode(AccountRecord.self, from: $0) }
        }
    }

    public func upsert(_ account: AccountRecord) throws {
        let data = try JSONEncoder().encode(account)
        lock.withLock { defaults.set(data, forKey: key(account.scope)) }
    }

    public func clearAccountData(_ scope: String) throws {
        lock.withLock { defaults.removeObject(forKey: key(scope)) }
    }

    private func key(_ scope: String) -> String { "account.\(scope)" }
}
