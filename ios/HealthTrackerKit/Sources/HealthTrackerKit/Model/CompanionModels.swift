import Foundation

// Companion delivery, package, progress and completion contracts (android `ApiModels.kt`).
// Request bodies are built as `JSONValue` so decimals keep their exact text on the wire.

extension DeliveryDTO {
    /// Local copy with an optimistic status and revision while a transition is queued.
    func with(status: String, revision: Int) -> DeliveryDTO {
        DeliveryDTO(id: id, deviceId: deviceId, profileId: profileId, plannedWorkoutId: plannedWorkoutId, packageHash: packageHash,
                    status: status, revision: revision, lastClientSequence: lastClientSequence, updatedAt: updatedAt,
                    expiresAt: expiresAt, trainingSessionId: trainingSessionId)
    }
}

public struct WorkoutPackageDTO: Decodable, Sendable {
    public let schemaVersion: String
    public let packageId: String
    public let plannedWorkoutId: String
    public let planId: String
    public let planVersionId: String
    public let title: String
    public let scheduledForDate: String
    public let timezone: String
    public let revision: Int
    public let generatedAt: String
    public let expiresAt: String?
    public let exercises: [PackageExerciseDTO]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case packageId = "package_id"
        case plannedWorkoutId = "planned_workout_id"
        case planId = "plan_id"
        case planVersionId = "plan_version_id"
        case title
        case scheduledForDate = "scheduled_for_date"
        case timezone, revision
        case generatedAt = "generated_at"
        case expiresAt = "expires_at"
        case exercises
    }
}

public struct PackageExerciseDTO: Decodable, Sendable {
    public let exerciseOrder: Int
    public let name: String
    public let notes: String?
    public let sets: [JSONValue]

    enum CodingKeys: String, CodingKey {
        case exerciseOrder = "exercise_order"
        case name, notes, sets
    }
}

/// A package whose SHA-256 (canonical JSON without `package_hash`) matched its declared hash.
public struct VerifiedPackage: Sendable {
    public let value: WorkoutPackageDTO
    public let calculatedHash: String
}

public struct CompletionResponse: Decodable, Sendable {
    public let delivery: DeliveryDTO
    public let completedWorkout: CompletedWorkoutDTO
    public let duplicate: Bool

    enum CodingKeys: String, CodingKey {
        case delivery
        case completedWorkout = "completed_workout"
        case duplicate
    }
}

public enum CompanionPayload {
    /// `DeliveryOperationRequest`; absent optionals are omitted like Android (`explicitNulls = false`).
    public static func operation(id: String, baseRevision: Int, receivedAt: String? = nil, packageHash: String? = nil, reasonCode: String? = nil) -> JSONValue {
        var members: [(String, JSONValue)] = [
            ("schema_version", .string(contractVersion)),
            ("client_operation_id", .string(id)),
            ("base_revision", .number(String(baseRevision))),
        ]
        if let receivedAt { members.append(("received_at", .string(receivedAt))) }
        if let packageHash { members.append(("package_hash", .string(packageHash))) }
        if let reasonCode { members.append(("reason_code", .string(reasonCode))) }
        return .object(members)
    }

    public static func progress(eventId: String, sequence: Int, eventType: String, occurredAt: String, payload: JSONValue) -> JSONValue {
        .object([
            ("schema_version", .string(contractVersion)),
            ("client_event_id", .string(eventId)),
            ("client_sequence", .number(String(sequence))),
            ("event_type", .string(eventType)),
            ("occurred_at", .string(occurredAt)),
            ("payload", payload),
        ])
    }

    public static func completion(eventId: String, packageHash: String, baseRevision: Int, result: JSONValue) -> JSONValue {
        .object([
            ("schema_version", .string(contractVersion)),
            ("client_event_id", .string(eventId)),
            ("package_hash", .string(packageHash)),
            ("base_revision", .number(String(baseRevision))),
            ("result", result),
        ])
    }
}

extension JSONValue {
    /// Integer value of a JSON number literal.
    public var intValue: Int? {
        if case let .number(text) = self { return Int(text) }
        return nil
    }

    /// Text of a string or number literal (decimals stay exact).
    public var textValue: String? {
        switch self {
        case let .string(value): value
        case let .number(value): value
        default: nil
        }
    }
}
