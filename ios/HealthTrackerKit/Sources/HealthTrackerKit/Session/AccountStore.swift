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
    func account(_ scope: String) async -> AccountRecord?
    func upsert(_ account: AccountRecord) async throws
    func clearAccountData(_ scope: String) async throws
}
