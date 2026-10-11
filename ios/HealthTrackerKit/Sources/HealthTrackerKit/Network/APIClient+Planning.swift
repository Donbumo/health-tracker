import Foundation

// MARK: Planning writes, exercise catalog and agenda (android `ApiClient.exerciseCatalog…plannedWorkout`)

public struct ExerciseCatalogResponseDTO: Decodable, Sendable {
    public let items: [ExerciseCatalogItemDTO]
    public let nextCursor: String?
    public let hasMore: Bool

    enum CodingKeys: String, CodingKey {
        case items
        case nextCursor = "next_cursor"
        case hasMore = "has_more"
    }
}

public struct ExerciseCatalogItemDTO: Decodable, Sendable, Equatable {
    public let publicId: String
    public let name: String
    public let aliases: [String]
    public let archived: Bool
    public let selectable: Bool
    public let preferredLoadMode: String?
    public let preferredUnit: String?

    enum CodingKeys: String, CodingKey {
        case publicId = "public_id"
        case name, aliases, archived, selectable
        case preferredLoadMode = "preferred_load_mode"
        case preferredUnit = "preferred_unit"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        publicId = try c.decode(String.self, forKey: .publicId)
        name = try c.decode(String.self, forKey: .name)
        aliases = try c.decodeIfPresent([String].self, forKey: .aliases) ?? []
        archived = try c.decode(Bool.self, forKey: .archived)
        selectable = try c.decode(Bool.self, forKey: .selectable)
        preferredLoadMode = try c.decodeIfPresent(String.self, forKey: .preferredLoadMode)
        preferredUnit = try c.decodeIfPresent(String.self, forKey: .preferredUnit)
    }
}

public struct ScheduleMutationResponse: Decodable, Sendable {
    public let publicId: String
    public let status: String
    public let revision: Int
    public let scheduledForDate: String
    public let timezone: String

    enum CodingKeys: String, CodingKey {
        case publicId = "public_id"
        case status, revision
        case scheduledForDate = "scheduled_for_date"
        case timezone
    }
}

public struct ScheduledWorkoutMutationResponse: Decodable, Sendable {
    public let id: String
    public let status: String
    public let revision: Int
    public let scheduledForDate: String
    public let timezone: String
    public let updatedAt: String

    enum CodingKeys: String, CodingKey {
        case id, status, revision
        case scheduledForDate = "scheduled_for_date"
        case timezone
        case updatedAt = "updated_at"
    }
}

extension APIClient {
    public func exerciseCatalog(search: String = "", cursor: String? = nil, limit: Int = 50) async throws -> ExerciseCatalogResponseDTO {
        var query = ["limit=\(limit)"]
        if !search.trimmingCharacters(in: .whitespaces).isEmpty { query.append("search=\(Self.encodeQuery(search))") }
        if let cursor { query.append("cursor=\(Self.encodeQuery(cursor))") }
        return try await call("/api/v1/mobile/exercises?\(query.joined(separator: "&"))", method: "GET")
    }

    public func planWorkout(_ publicId: String) async throws -> MobilePlanWorkoutDTO {
        try await call("/api/v1/mobile/workouts/\(Self.encodePathComponent(publicId))", method: "GET")
    }

    public func plannedWorkouts(from: String, to: String) async throws -> [PlannedWorkoutDTO] {
        try await call("/api/v1/planned-workouts?from=\(Self.encodeQuery(from))&to=\(Self.encodeQuery(to))", method: "GET")
    }

    public func plannedWorkout(_ publicId: String) async throws -> PlannedWorkoutDTO {
        try await call("/api/v1/planned-workouts/\(Self.encodePathComponent(publicId))", method: "GET")
    }

    /// Generic planning mutation returning the envelope `data` as JSON.
    func planningMutation(_ path: String, method: String, body: JSONValue, key: String) async throws -> JSONValue {
        try await callJSON(path, method: method, body: Data(body.encoded().utf8), idempotencyKey: key)
    }

    public func createPlan(_ body: JSONValue, key: String) async throws {
        _ = try await planningMutation("/api/v1/mobile/plans", method: "POST", body: body, key: key)
    }

    public func patchPlan(_ publicId: String, _ body: JSONValue, key: String) async throws {
        _ = try await planningMutation("/api/v1/mobile/plans/\(Self.encodePathComponent(publicId))", method: "PATCH", body: body, key: key)
    }

    public func createPlanWorkout(planId: String, _ body: JSONValue, key: String) async throws {
        _ = try await planningMutation("/api/v1/mobile/plans/\(Self.encodePathComponent(planId))/workouts", method: "POST", body: body, key: key)
    }

    public func patchPlanWorkout(_ publicId: String, _ body: JSONValue, key: String) async throws {
        _ = try await planningMutation("/api/v1/mobile/workouts/\(Self.encodePathComponent(publicId))", method: "PATCH", body: body, key: key)
    }

    public func schedulePlanWorkout(_ workoutId: String, _ body: JSONValue, key: String) async throws -> ScheduleMutationResponse {
        try await call("/api/v1/mobile/workouts/\(Self.encodePathComponent(workoutId))/schedule", method: "POST",
                       body: Data(body.encoded().utf8), idempotencyKey: key)
    }

    public func reschedulePlannedWorkout(_ publicId: String, _ body: JSONValue, key: String) async throws -> ScheduledWorkoutMutationResponse {
        try await call("/api/v1/planned-workouts/\(Self.encodePathComponent(publicId))", method: "PATCH",
                       body: Data(body.encoded().utf8), idempotencyKey: key)
    }

    public func cancelScheduledWorkout(_ publicId: String, _ body: JSONValue, key: String) async throws {
        _ = try await planningMutation("/api/v1/mobile/scheduled-workouts/\(Self.encodePathComponent(publicId))", method: "DELETE", body: body, key: key)
    }
}
