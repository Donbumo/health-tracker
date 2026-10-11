import Foundation

// Mobile history, progress and planning read contracts (android `ApiModels.kt`).
// Decimal quantities stay as the server's text ("40.00"), exactly like Android.

public struct MobileHistoryPageDTO: Decodable, Sendable {
    public let schemaVersion: String
    public let items: [MobileHistoryItemDTO]
    public let nextCursor: String?
    public let hasMore: Bool

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case items
        case nextCursor = "next_cursor"
        case hasMore = "has_more"
    }
}

public struct MobileHistoryItemDTO: Decodable, Sendable, Equatable {
    public let publicId: String
    public let performedAt: String
    public let completedAt: String
    public let name: String
    public let durationSeconds: Int?
    public let exerciseCount: Int
    public let setCount: Int
    public let volumeKg: String?
    public let volumePartial: Bool
    public let source: String
    public let syncStatus: String

    enum CodingKeys: String, CodingKey {
        case publicId = "public_id"
        case performedAt = "performed_at"
        case completedAt = "completed_at"
        case name
        case durationSeconds = "duration_seconds"
        case exerciseCount = "exercise_count"
        case setCount = "set_count"
        case volumeKg = "volume_kg"
        case volumePartial = "volume_partial"
        case source
        case syncStatus = "sync_status"
    }
}

public struct MobileHistoryDetailDTO: Decodable, Sendable {
    public let schemaVersion: String
    public let publicId: String
    public let performedAt: String
    public let startedAt: String
    public let completedAt: String
    public let timezone: String
    public let name: String
    public let durationSeconds: Int?
    public let exerciseCount: Int
    public let setCount: Int
    public let volumeKg: String?
    public let volumePartial: Bool
    public let source: String
    public let syncStatus: String
    public let notes: String?
    public let plannedWorkoutId: String?
    public let trainingPlanId: String?
    public let trainingPlanVersionId: String?
    public let exercises: [MobileHistoryExerciseDTO]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case publicId = "public_id"
        case performedAt = "performed_at"
        case startedAt = "started_at"
        case completedAt = "completed_at"
        case timezone, name
        case durationSeconds = "duration_seconds"
        case exerciseCount = "exercise_count"
        case setCount = "set_count"
        case volumeKg = "volume_kg"
        case volumePartial = "volume_partial"
        case source
        case syncStatus = "sync_status"
        case notes
        case plannedWorkoutId = "planned_workout_id"
        case trainingPlanId = "training_plan_id"
        case trainingPlanVersionId = "training_plan_version_id"
        case exercises
    }
}

public struct MobileHistoryExerciseDTO: Decodable, Sendable {
    public let exercisePublicId: String?
    public let exerciseOrder: Int
    public let name: String
    public let notes: String?
    public let sets: [MobileHistorySetDTO]

    enum CodingKeys: String, CodingKey {
        case exercisePublicId = "exercise_public_id"
        case exerciseOrder = "exercise_order"
        case name, notes, sets
    }
}

public struct WeightComponentDTO: Decodable, Sendable, Equatable {
    public let value: String
    public let unit: String
}

public struct MobileHistorySetDTO: Decodable, Sendable {
    public let setNumber: Int
    public let weightKg: String?
    public let displayLoad: WeightComponentDTO?
    public let loadMode: String
    public let reps: Int
    public let rir: String?
    public let rpe: String?
    public let restSeconds: Int?
    public let durationSeconds: String?
    public let distanceMeters: String?
    public let notes: String?

    enum CodingKeys: String, CodingKey {
        case setNumber = "set_number"
        case weightKg = "weight_kg"
        case displayLoad = "display_load"
        case loadMode = "load_mode"
        case reps, rir, rpe
        case restSeconds = "rest_seconds"
        case durationSeconds = "duration_seconds"
        case distanceMeters = "distance_meters"
        case notes
    }
}

public struct ProgressMetricsDTO: Decodable, Sendable, Equatable {
    public let sessions: Int
    public let trainingDays: Int
    public let distinctExercises: Int
    public let completedSets: Int
    public let totalReps: Int
    public let volumeKg: String?
    public let volumePartial: Bool
    public let durationSeconds: Int

    enum CodingKeys: String, CodingKey {
        case sessions
        case trainingDays = "training_days"
        case distinctExercises = "distinct_exercises"
        case completedSets = "completed_sets"
        case totalReps = "total_reps"
        case volumeKg = "volume_kg"
        case volumePartial = "volume_partial"
        case durationSeconds = "duration_seconds"
    }
}

public struct ProgressComparisonDTO: Decodable, Sendable, Equatable {
    public let change: String
    public let percent: String?
    public let previous: String
}

public struct ProgressSummaryDTO: Decodable, Sendable {
    public let schemaVersion: String
    public let range: String
    public let generatedAt: String
    public let metrics: ProgressMetricsDTO
    public let comparison: [String: ProgressComparisonDTO]?
    public let comparableLoadModes: [String]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case range
        case generatedAt = "generated_at"
        case metrics, comparison
        case comparableLoadModes = "comparable_load_modes"
    }
}

public struct ProgressExerciseListDTO: Decodable, Sendable {
    public let schemaVersion: String
    public let range: String
    public let items: [ProgressExerciseDTO]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case range, items
    }
}

public struct ProgressBestSetDTO: Decodable, Sendable, Equatable {
    public let reps: Int
    public let weightKg: String

    enum CodingKeys: String, CodingKey {
        case reps
        case weightKg = "weight_kg"
    }
}

public struct ProgressExerciseDTO: Decodable, Sendable, Equatable {
    public let publicId: String
    public let name: String
    public let lastPerformedAt: String?
    public let sessionCount: Int
    public let setCount: Int
    public let bestLoadKg: String?
    public let bestRepetitionSet: ProgressBestSetDTO?
    public let volumeKg: String?
    public let volumePartial: Bool
    public let loadComparable: Bool
    public let loadModes: [String]
    public let trend: String

    enum CodingKeys: String, CodingKey {
        case publicId = "public_id"
        case name
        case lastPerformedAt = "last_performed_at"
        case sessionCount = "session_count"
        case setCount = "set_count"
        case bestLoadKg = "best_load_kg"
        case bestRepetitionSet = "best_repetition_set"
        case volumeKg = "volume_kg"
        case volumePartial = "volume_partial"
        case loadComparable = "load_comparable"
        case loadModes = "load_modes"
        case trend
    }
}

public struct ProgressPointDTO: Decodable, Sendable, Equatable {
    public let date: String
    public let performedAt: String
    public let sessionPublicId: String
    public let bestLoadKg: String?
    public let bestReps: Int?
    public let volumeKg: String?
    public let setCount: Int
    public let averageRir: String?
    public let averageRpe: String?
    public let loadComparable: Bool

    enum CodingKeys: String, CodingKey {
        case date
        case performedAt = "performed_at"
        case sessionPublicId = "session_public_id"
        case bestLoadKg = "best_load_kg"
        case bestReps = "best_reps"
        case volumeKg = "volume_kg"
        case setCount = "set_count"
        case averageRir = "average_rir"
        case averageRpe = "average_rpe"
        case loadComparable = "load_comparable"
    }
}

public struct PersonalRecordDTO: Decodable, Sendable, Equatable {
    public let type: String
    public let value: String
    public let unit: String
    public let date: String
    public let sessionPublicId: String
    public let setIndex: Int?

    enum CodingKeys: String, CodingKey {
        case type, value, unit, date
        case sessionPublicId = "session_public_id"
        case setIndex = "set_index"
    }
}

public struct ProgressExerciseDetailDTO: Decodable, Sendable {
    public let schemaVersion: String
    public let range: String
    public let exercise: ProgressExerciseDTO
    public let points: [ProgressPointDTO]
    public let personalRecords: [PersonalRecordDTO]
    public let recentSessions: [MobileHistoryItemDTO]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case range, exercise, points
        case personalRecords = "personal_records"
        case recentSessions = "recent_sessions"
    }
}

// MARK: Planning (read)

public struct MobilePlanListDTO: Decodable, Sendable {
    public let items: [MobilePlanDTO]
}

public struct MobilePlanDTO: Decodable, Sendable {
    public let publicId: String
    public let name: String
    public let description: String?
    public let status: String
    public let revision: Int
    public let activeVersionId: String?
    public let activeVersion: Int?
    public let workoutCount: Int
    public let workouts: [MobilePlanWorkoutDTO]?
    public let createdAt: String
    public let updatedAt: String
    public let archivedAt: String?

    enum CodingKeys: String, CodingKey {
        case publicId = "public_id"
        case name, description, status, revision
        case activeVersionId = "active_version_id"
        case activeVersion = "active_version"
        case workoutCount = "workout_count"
        case workouts
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case archivedAt = "archived_at"
    }
}

public struct MobilePlanWorkoutDTO: Decodable, Sendable {
    public let publicId: String
    public let name: String
    public let notes: String?
    public let position: Int
    public let exercises: [MobilePlanExerciseDTO]
    public let estimatedDurationSeconds: Int?
    public let revision: Int
    public let createdAt: String
    public let updatedAt: String

    enum CodingKeys: String, CodingKey {
        case publicId = "public_id"
        case name, notes, position, exercises
        case estimatedDurationSeconds = "estimated_duration_seconds"
        case revision
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

public struct MobilePlanExerciseDTO: Decodable, Sendable {
    public let id: String
    public let exerciseId: String?
    public let exerciseOrder: Int
    public let name: String
    public let notes: String?
    public let sets: [MobilePlanSetDTO]

    enum CodingKeys: String, CodingKey {
        case id
        case exerciseId = "exercise_id"
        case exerciseOrder = "exercise_order"
        case name, notes, sets
    }
}

public struct MobilePlanSetDTO: Decodable, Sendable {
    public let id: String
    public let setNumber: Int
    public let reps: Int?
    public let repsMin: Int?
    public let repsMax: Int?
    public let weightKg: String?
    public let loadValue: String?
    public let loadUnit: String
    public let loadMode: String
    public let loadDetails: JSONValue?
    public let rir: String?
    public let rpe: String?
    public let restSeconds: Int?
    public let durationSeconds: Int?
    public let distanceMeters: String?
    public let notes: String?

    enum CodingKeys: String, CodingKey {
        case id
        case setNumber = "set_number"
        case reps
        case repsMin = "reps_min"
        case repsMax = "reps_max"
        case weightKg = "weight_kg"
        case loadValue = "load_value"
        case loadUnit = "load_unit"
        case loadMode = "load_mode"
        case loadDetails = "load_details"
        case rir, rpe
        case restSeconds = "rest_seconds"
        case durationSeconds = "duration_seconds"
        case distanceMeters = "distance_m"
        case notes
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        setNumber = try c.decode(Int.self, forKey: .setNumber)
        reps = try c.decodeIfPresent(Int.self, forKey: .reps)
        repsMin = try c.decodeIfPresent(Int.self, forKey: .repsMin)
        repsMax = try c.decodeIfPresent(Int.self, forKey: .repsMax)
        weightKg = try c.decodeIfPresent(String.self, forKey: .weightKg)
        loadValue = try c.decodeIfPresent(String.self, forKey: .loadValue)
        loadUnit = try c.decodeIfPresent(String.self, forKey: .loadUnit) ?? "kg"
        loadMode = try c.decodeIfPresent(String.self, forKey: .loadMode) ?? "direct_total"
        let details = try c.decodeIfPresent(JSONValue.self, forKey: .loadDetails)
        loadDetails = details == .null ? nil : details
        rir = try c.decodeIfPresent(String.self, forKey: .rir)
        rpe = try c.decodeIfPresent(String.self, forKey: .rpe)
        restSeconds = try c.decodeIfPresent(Int.self, forKey: .restSeconds)
        durationSeconds = try c.decodeIfPresent(Int.self, forKey: .durationSeconds)
        distanceMeters = try c.decodeIfPresent(String.self, forKey: .distanceMeters)
        notes = try c.decodeIfPresent(String.self, forKey: .notes)
    }
}

/// History filter set; `cacheKey` matches Android so each filter combination keeps its own page order.
public struct HistoryFilters: Sendable, Equatable {
    public var dateFrom: String?
    public var dateTo: String?
    public var exercisePublicId: String?

    public init(dateFrom: String? = nil, dateTo: String? = nil, exercisePublicId: String? = nil) {
        self.dateFrom = dateFrom
        self.dateTo = dateTo
        self.exercisePublicId = exercisePublicId
    }

    public var cacheKey: String { "history:\(dateFrom ?? ""):\(dateTo ?? ""):\(exercisePublicId ?? "")" }
    public var isEmpty: Bool { dateFrom == nil && dateTo == nil && exercisePublicId == nil }
}
