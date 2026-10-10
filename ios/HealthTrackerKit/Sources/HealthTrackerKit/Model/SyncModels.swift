import Foundation

// Mobile Sync 1.0 and Companion 1.0 contracts (android `ApiModels.kt`).

public struct SyncLimits: Decodable, Sendable, Equatable {
    public let pushOperations: Int
    public let pullLimit: Int
    public let jsonBytes: Int

    enum CodingKeys: String, CodingKey {
        case pushOperations = "push_operations"
        case pullLimit = "pull_limit"
        case jsonBytes = "json_bytes"
    }
}

public struct BootstrapDevice: Decodable, Sendable, Equatable {
    public let deviceId: String
    public let sessionId: String

    enum CodingKeys: String, CodingKey {
        case deviceId = "device_id"
        case sessionId = "session_id"
    }
}

public struct BootstrapCompanion: Decodable, Sendable {
    public let profile: CompanionProfileDTO?
    public let deliveries: [DeliveryDTO]
    public let versions: [String: String]

    enum CodingKeys: String, CodingKey { case profile, deliveries, versions }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        profile = try container.decodeIfPresent(CompanionProfileDTO.self, forKey: .profile)
        deliveries = try container.decodeIfPresent([DeliveryDTO].self, forKey: .deliveries) ?? []
        versions = try container.decode([String: String].self, forKey: .versions)
    }
}

public struct BootstrapResponse: Decodable, Sendable {
    public let schemaVersion: String
    public let serverTime: String
    public let cursor: String
    public let plannedWorkouts: [PlannedWorkoutDTO]
    public let completedWorkouts: [CompletedWorkoutDTO]
    public let capabilities: [String: Bool]
    public let limits: SyncLimits
    public let schemas: [String: String]
    public let device: BootstrapDevice
    public let companion: BootstrapCompanion

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case serverTime = "server_time"
        case cursor
        case plannedWorkouts = "planned_workouts"
        case completedWorkouts = "completed_workouts"
        case capabilities, limits, schemas, device, companion
    }
}

public struct PlannedWorkoutDTO: Decodable, Sendable, Equatable {
    public let schemaVersion: String
    public let id: String
    public let trainingPlanId: String
    public let trainingPlanVersionId: String
    public let scheduledForDate: String
    public let timezone: String
    public let status: String
    public let title: String
    public let snapshot: JSONValue
    public let sourceVersion: Int
    public let revision: Int
    public let createdAt: String
    public let updatedAt: String
    public let completedAt: String?
    public let cancelledAt: String?
    public let deleted: Bool

    public var sourceWorkoutId: String? { snapshot["workout_id"]?.stringValue }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case id
        case trainingPlanId = "training_plan_id"
        case trainingPlanVersionId = "training_plan_version_id"
        case scheduledForDate = "scheduled_for_date"
        case timezone, status, title, snapshot
        case sourceVersion = "source_version"
        case revision
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case completedAt = "completed_at"
        case cancelledAt = "cancelled_at"
        case deleted
    }
}

public struct CompletedWorkoutDTO: Decodable, Sendable {
    public let schemaVersion: String
    public let id: String?
    public let clientEventId: String?
    public let plannedWorkoutId: String?
    public let trainingPlanId: String?
    public let trainingPlanVersionId: String?
    public let startedAt: String
    public let completedAt: String
    public let timezone: String
    public let durationSeconds: Int?
    public let notes: String?
    public let revision: Int?
    public let exercises: [CompletedExerciseDTO]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case id
        case clientEventId = "client_event_id"
        case plannedWorkoutId = "planned_workout_id"
        case trainingPlanId = "training_plan_id"
        case trainingPlanVersionId = "training_plan_version_id"
        case startedAt = "started_at"
        case completedAt = "completed_at"
        case timezone
        case durationSeconds = "duration_seconds"
        case notes, revision, exercises
    }
}

public struct CompletedExerciseDTO: Decodable, Sendable {
    public let exerciseOrder: Int
    public let plannedExerciseOrder: Int
    public let name: String
    public let sets: [CompletedSetDTO]

    enum CodingKeys: String, CodingKey {
        case exerciseOrder = "exercise_order"
        case plannedExerciseOrder = "planned_exercise_order"
        case name, sets
    }
}

public struct CompletedSetDTO: Decodable, Sendable {
    public let setNumber: Int
    public let weightKg: Decimal
    public let reps: Int
    public let loadMode: String?

    enum CodingKeys: String, CodingKey {
        case setNumber = "set_number"
        case weightKg = "weight_kg"
        case reps
        case loadDetails = "load_details"
    }

    private struct LoadDetails: Decodable {
        let loadMode: String
        enum CodingKeys: String, CodingKey { case loadMode = "load_mode" }
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        setNumber = try container.decode(Int.self, forKey: .setNumber)
        weightKg = try container.decode(Decimal.self, forKey: .weightKg)
        reps = try container.decode(Int.self, forKey: .reps)
        loadMode = try container.decodeIfPresent(LoadDetails.self, forKey: .loadDetails)?.loadMode
    }

    public static let comparableVolumeModes: Set<String> = [
        "direct_total", "per_side", "bar_plus_per_side", "machine_initial_total",
        "machine_initial_per_side", "machine_external_per_side_initial_total",
        "selector_stack", "dumbbell_each",
    ]

    /// Weight × reps for comparable load modes only, matching Android `traditionalVolume()`.
    public var traditionalVolume: Decimal? {
        guard Self.comparableVolumeModes.contains(loadMode ?? "direct_total"), weightKg >= 0, reps > 0 else { return nil }
        return weightKg * Decimal(reps)
    }
}

public struct CompanionLimits: Codable, Sendable, Equatable {
    public var maxPayloadBytes: Int = 262_144
    public var maxProgressEventsPerWorkout: Int = 500

    public init() {}

    enum CodingKeys: String, CodingKey {
        case maxPayloadBytes = "max_payload_bytes"
        case maxProgressEventsPerWorkout = "max_progress_events_per_workout"
    }
}

public struct CompanionProfileDTO: Decodable, Sendable, Equatable {
    public let id: String
    public let deviceId: String
    public let protocolVersion: String
    public let workoutSchemaVersion: String
    public let resultSchemaVersion: String
    public let revision: Int
    public let lastNegotiatedAt: String
    public let revoked: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case deviceId = "device_id"
        case protocolVersion = "protocol_version"
        case workoutSchemaVersion = "workout_schema_version"
        case resultSchemaVersion = "result_schema_version"
        case revision
        case lastNegotiatedAt = "last_negotiated_at"
        case revoked
    }
}

public struct DeliveryDTO: Decodable, Sendable, Equatable {
    public let id: String
    public let profileId: String
    public let plannedWorkoutId: String
    public let packageHash: String
    public let status: String
    public let revision: Int
    public let lastClientSequence: Int
    public let updatedAt: String
    public let expiresAt: String?
    public let trainingSessionId: String?

    enum CodingKeys: String, CodingKey {
        case id
        case profileId = "profile_id"
        case plannedWorkoutId = "planned_workout_id"
        case packageHash = "package_hash"
        case status, revision
        case lastClientSequence = "last_client_sequence"
        case updatedAt = "updated_at"
        case expiresAt = "expires_at"
        case trainingSessionId = "training_session_id"
    }
}

public struct NegotiationRequest: Encodable, Sendable {
    public var schemaVersion = contractVersion
    public var protocolVersions = [contractVersion]
    public var workoutSchemaVersions = [contractVersion]
    public var resultSchemaVersions = [contractVersion]
    public var features: [String]
    public var metrics: [String]
    public var limits = CompanionLimits()
    public var baseRevision: Int?

    /// Same feature and metric set the Android companion negotiates.
    public static func companion(baseRevision: Int?) -> NegotiationRequest {
        NegotiationRequest(
            features: ["offline", "rest_timer", "rpe", "rir", "weight", "heart_rate_summary", "calories_summary"],
            metrics: ["reps", "weight_kg", "duration_seconds", "distance_m", "rest_seconds", "rpe", "rir", "average_heart_rate_bpm", "calories_burned"],
            baseRevision: baseRevision
        )
    }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case protocolVersions = "protocol_versions"
        case workoutSchemaVersions = "workout_schema_versions"
        case resultSchemaVersions = "result_schema_versions"
        case features, metrics, limits
        case baseRevision = "base_revision"
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(protocolVersions, forKey: .protocolVersions)
        try container.encode(workoutSchemaVersions, forKey: .workoutSchemaVersions)
        try container.encode(resultSchemaVersions, forKey: .resultSchemaVersions)
        try container.encode(features, forKey: .features)
        try container.encode(metrics, forKey: .metrics)
        try container.encode(limits, forKey: .limits)
        // Omitted when absent, like Android (`explicitNulls = false`); the server rejects `null`.
        try container.encodeIfPresent(baseRevision, forKey: .baseRevision)
    }
}

public struct NegotiationResponse: Decodable, Sendable {
    public let selectedProtocolVersion: String
    public let selectedWorkoutSchemaVersion: String
    public let selectedResultSchemaVersion: String
    public let acceptedFeatures: [String]
    public let acceptedMetrics: [String]
    public let effectiveLimits: CompanionLimits
    public let profile: CompanionProfileDTO

    enum CodingKeys: String, CodingKey {
        case selectedProtocolVersion = "selected_protocol_version"
        case selectedWorkoutSchemaVersion = "selected_workout_schema_version"
        case selectedResultSchemaVersion = "selected_result_schema_version"
        case acceptedFeatures = "accepted_features"
        case acceptedMetrics = "accepted_metrics"
        case effectiveLimits = "effective_limits"
        case profile
    }
}

public struct SyncChangeDTO: Decodable, Sendable {
    public let entityType: String
    public let entityId: String
    public let operation: String
    public let revision: Int
    public let changedAt: String
    public let payload: JSONValue?

    enum CodingKeys: String, CodingKey {
        case entityType = "entity_type"
        case entityId = "entity_id"
        case operation, revision
        case changedAt = "changed_at"
        case payload
    }

    /// Decodes the change payload into a typed DTO.
    public func decodePayload<T: Decodable>(_ type: T.Type) throws -> T? {
        guard let payload, payload != .null else { return nil }
        return try JSONDecoder().decode(T.self, from: Data(payload.encoded().utf8))
    }
}

public struct PullResponse: Decodable, Sendable {
    public let schemaVersion: String
    public let changes: [SyncChangeDTO]
    public let nextCursor: String
    public let hasMore: Bool
    public let serverTime: String

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case changes
        case nextCursor = "next_cursor"
        case hasMore = "has_more"
        case serverTime = "server_time"
    }
}

public struct SyncStatusResponse: Decodable, Sendable {
    public let schemaVersion: String
    public let deviceId: String
    public let cursor: String
    public let serverTime: String

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case deviceId = "device_id"
        case cursor
        case serverTime = "server_time"
    }
}

// MARK: Contract verification

public enum SyncContract {
    public static let requiredCapabilities: Set<String> = [
        "offline_sync_push", "incremental_pull", "planned_workouts", "completed_workouts",
        "companion_delivery", "capability_negotiation", "progress_checkpoints", "workout_package",
        "mobile_planning", "exercise_catalog",
    ]

    public static func verify(_ value: BootstrapResponse) throws {
        if value.schemaVersion != contractVersion || value.schemas.values.contains(where: { $0 != contractVersion }) {
            throw AppFailure(.schemaIncompatible, "El servidor publica schemas incompatibles.", retryable: false)
        }
        if requiredCapabilities.contains(where: { value.capabilities[$0] != true }) {
            throw AppFailure(.serverIncompatible, "El servidor no ofrece todas las capacidades iOS requeridas.", retryable: false)
        }
        if value.limits.pushOperations < 1 || value.limits.pullLimit < 1 {
            throw AppFailure(.serverIncompatible, "El servidor publica límites de sync inválidos.", retryable: false)
        }
    }

    public static func verify(_ value: NegotiationResponse) throws {
        guard value.selectedProtocolVersion == contractVersion,
              value.selectedWorkoutSchemaVersion == contractVersion,
              value.selectedResultSchemaVersion == contractVersion else {
            throw AppFailure(.serverIncompatible, "No existe una versión Companion compatible.", retryable: false)
        }
        let features: Set<String> = ["offline", "rpe", "rir", "weight"]
        let metrics: Set<String> = ["reps", "weight_kg", "rest_seconds", "rpe", "rir"]
        guard features.isSubset(of: Set(value.acceptedFeatures)), metrics.isSubset(of: Set(value.acceptedMetrics)) else {
            throw AppFailure(.serverIncompatible, "El servidor rechazó capacidades necesarias para la captura iOS.", retryable: false)
        }
        guard value.effectiveLimits.maxPayloadBytes >= 1, value.effectiveLimits.maxProgressEventsPerWorkout >= 1 else {
            throw AppFailure(.serverIncompatible, "El servidor publicó límites Companion inválidos.", retryable: false)
        }
    }

    /// Profile needs renegotiation when absent or not on the 1.0 contract.
    public static func needsNegotiation(_ profile: CompanionProfileDTO?) -> Bool {
        guard let profile else { return true }
        return profile.protocolVersion != contractVersion ||
            profile.workoutSchemaVersion != contractVersion ||
            profile.resultSchemaVersion != contractVersion
    }
}
