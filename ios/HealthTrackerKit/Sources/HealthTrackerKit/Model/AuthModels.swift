import Foundation

public struct APIEnvelope<T: Decodable & Sendable>: Decodable, Sendable {
    public let data: T
    public let meta: APIMeta?
}

public struct APIMeta: Decodable, Sendable {
    public let requestId: String?
    public let pagination: Pagination?

    enum CodingKeys: String, CodingKey {
        case requestId = "request_id"
        case pagination
    }
}

public struct Pagination: Decodable, Sendable {
    public let page: Int
    public let perPage: Int
    public let hasMore: Bool

    enum CodingKeys: String, CodingKey {
        case page
        case perPage = "per_page"
        case hasMore = "has_more"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        page = try container.decodeIfPresent(Int.self, forKey: .page) ?? 1
        perPage = try container.decodeIfPresent(Int.self, forKey: .perPage) ?? 0
        hasMore = try container.decodeIfPresent(Bool.self, forKey: .hasMore) ?? false
    }
}

public struct ErrorEnvelope: Decodable, Sendable {
    public let error: APIErrorBody
}

public struct APIErrorBody: Decodable, Sendable, Equatable {
    public let code: String
    public let message: String
    public let requestId: String?

    public init(code: String, message: String, requestId: String? = nil) {
        self.code = code
        self.message = message
        self.requestId = requestId
    }

    enum CodingKeys: String, CodingKey {
        case code, message
        case requestId = "request_id"
    }
}

public struct DeviceRegistration: Encodable, Sendable {
    public let deviceId: String
    public let name: String
    public let platform: String
    public let appVersion: String
    public let osVersion: String

    public init(deviceId: String, name: String, platform: String = "ios", appVersion: String, osVersion: String) {
        self.deviceId = deviceId
        self.name = name
        self.platform = platform
        self.appVersion = appVersion
        self.osVersion = osVersion
    }

    enum CodingKeys: String, CodingKey {
        case deviceId = "device_id"
        case name, platform
        case appVersion = "app_version"
        case osVersion = "os_version"
    }
}

public struct LoginRequest: Encodable, Sendable {
    public let email: String
    public let password: String
    public let device: DeviceRegistration
}

public struct RefreshRequest: Encodable, Sendable {
    public let refreshToken: String

    enum CodingKeys: String, CodingKey {
        case refreshToken = "refresh_token"
    }
}

public struct TokenResponse: Decodable, Sendable {
    public let accessToken: String
    public let refreshToken: String
    public let tokenType: String
    public let expiresIn: Int64
    public let refreshExpiresAt: String

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case tokenType = "token_type"
        case expiresIn = "expires_in"
        case refreshExpiresAt = "refresh_expires_at"
    }
}

public struct HealthResponse: Decodable, Sendable {
    public let status: String
    public let app: String
}

public struct UserProfile: Codable, Sendable, Equatable {
    public let id: String
    public let email: String
    public let role: String
    public let timezone: String
    public let createdAt: String
    public let capabilities: [String: Bool]

    public init(id: String, email: String, role: String, timezone: String, createdAt: String, capabilities: [String: Bool] = [:]) {
        self.id = id
        self.email = email
        self.role = role
        self.timezone = timezone
        self.createdAt = createdAt
        self.capabilities = capabilities
    }

    enum CodingKeys: String, CodingKey {
        case id, email, role, timezone, capabilities
        case createdAt = "created_at"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        email = try container.decode(String.self, forKey: .email)
        role = try container.decode(String.self, forKey: .role)
        timezone = try container.decode(String.self, forKey: .timezone)
        createdAt = try container.decode(String.self, forKey: .createdAt)
        capabilities = try container.decodeIfPresent([String: Bool].self, forKey: .capabilities) ?? [:]
    }
}

/// Empty `{}` payloads such as logout responses.
public struct EmptyPayload: Decodable, Sendable {}
