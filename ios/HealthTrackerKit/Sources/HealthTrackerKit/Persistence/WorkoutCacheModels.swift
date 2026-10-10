import Foundation
import SwiftData

// Downloaded packages and local workout drafts (android Room `workout_packages`, `package_*`,
// `workout_drafts`, `draft_sets`). A draft is keyed by its delivery and never leaves its account scope.

@Model
final class WorkoutPackageModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var packageId: String
    var deliveryId: String
    var plannedWorkoutId: String
    var planId: String
    var planVersionId: String
    var title: String
    var scheduledForDate: String
    var timezone: String
    var revision: Int
    var generatedAt: String
    var expiresAt: String?
    var packageHash: String
    var verifiedAt: String

    init(scope: String, deliveryId: String, package: WorkoutPackageDTO, hash: String, verifiedAt: String) {
        key = scopedKey(scope, package.packageId)
        accountScope = scope
        packageId = package.packageId
        self.deliveryId = deliveryId
        plannedWorkoutId = package.plannedWorkoutId
        planId = package.planId
        planVersionId = package.planVersionId
        title = package.title
        scheduledForDate = package.scheduledForDate
        timezone = package.timezone
        revision = package.revision
        generatedAt = package.generatedAt
        expiresAt = package.expiresAt
        packageHash = hash
        self.verifiedAt = verifiedAt
    }
}

@Model
final class PackageExerciseModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var packageId: String
    var exerciseOrder: Int
    var name: String
    var notes: String?

    init(scope: String, packageId: String, exerciseOrder: Int, name: String, notes: String?) {
        key = scopedKey(scope, "\(packageId)#\(exerciseOrder)")
        accountScope = scope
        self.packageId = packageId
        self.exerciseOrder = exerciseOrder
        self.name = name
        self.notes = notes
    }
}

@Model
final class PackageSetModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var packageId: String
    var exerciseOrder: Int
    var setNumber: Int
    var reps: Int?
    var repsMin: Int?
    var repsMax: Int?
    var durationSeconds: Int?
    var distanceMeters: String?
    var restSeconds: Int?
    var target: String?
    var weightKg: String?
    var loadValue: String?
    var loadUnit: String?
    var loadMode: String?
    var rir: String?
    var rpe: String?
    var notes: String?
    var loadDetailsJSON: String?

    init(scope: String, packageId: String, exerciseOrder: Int, setNumber: Int, json: JSONValue) {
        key = scopedKey(scope, "\(packageId)#\(exerciseOrder)#\(setNumber)")
        accountScope = scope
        self.packageId = packageId
        self.exerciseOrder = exerciseOrder
        self.setNumber = setNumber
        reps = json["reps"]?.intValue
        repsMin = json["reps_min"]?.intValue
        repsMax = json["reps_max"]?.intValue
        durationSeconds = json["duration_seconds"]?.intValue
        distanceMeters = json["distance_m"]?.textValue
        restSeconds = json["rest_seconds"]?.intValue
        target = json["target"].flatMap { $0 == .null ? nil : String($0.encoded().prefix(500)) }
        weightKg = json["weight_kg"]?.textValue
        loadValue = json["load_value"]?.textValue
        loadUnit = json["load_unit"]?.textValue
        loadMode = json["load_mode"]?.textValue
        rir = json["rir"]?.textValue
        rpe = json["rpe"]?.textValue
        notes = json["notes"]?.textValue
        loadDetailsJSON = json["load_details"].flatMap { $0 == .null ? nil : $0.encoded() }
    }
}

@Model
final class WorkoutDraftModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var deliveryId: String
    var packageId: String
    var clientSubmissionId: String
    var clientEventId: String
    var schemaVersion: String
    var packageHash: String
    /// active, paused, saved, pending_sync, completion_pending, aborted_pending or corrupt.
    var status: String
    var startedAt: String
    var pausedAt: String?
    var averageHeartRateBpm: Int?
    var caloriesBurned: String?
    var notes: String?
    var checkpointSequence: Int
    var payloadHash: String
    var updatedAt: String
    var expiresAt: String
    var corruptReasonCode: String?

    init(scope: String, deliveryId: String, packageId: String, packageHash: String, startedAt: String, expiresAt: String,
         checkpointSequence: Int, clientSubmissionId: String, clientEventId: String) {
        key = scopedKey(scope, deliveryId)
        accountScope = scope
        self.deliveryId = deliveryId
        self.packageId = packageId
        self.clientSubmissionId = clientSubmissionId
        self.clientEventId = clientEventId
        schemaVersion = contractVersion
        self.packageHash = packageHash
        status = "active"
        self.startedAt = startedAt
        self.checkpointSequence = checkpointSequence
        payloadHash = ""
        updatedAt = startedAt
        self.expiresAt = expiresAt
    }
}

@Model
final class DraftSetModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var deliveryId: String
    var exerciseOrder: Int
    var setNumber: Int
    var plannedSetNumber: Int
    var reps: Int
    var rir: String?
    var rpe: String?
    var weightKg: String
    var loadDetailsJSON: String?
    var durationSeconds: Int?
    var distanceMeters: String?
    var restSeconds: Int?
    var notes: String?
    var checkpointSequence: Int?
    var completed: Bool
    var updatedAt: String

    init(scope: String, deliveryId: String, exerciseOrder: Int, setNumber: Int, plannedSetNumber: Int, reps: Int, weightKg: String, updatedAt: String) {
        key = DraftSetModel.key(scope, deliveryId, exerciseOrder, setNumber)
        accountScope = scope
        self.deliveryId = deliveryId
        self.exerciseOrder = exerciseOrder
        self.setNumber = setNumber
        self.plannedSetNumber = plannedSetNumber
        self.reps = reps
        self.weightKg = weightKg
        completed = false
        self.updatedAt = updatedAt
    }

    static func key(_ scope: String, _ deliveryId: String, _ exerciseOrder: Int, _ setNumber: Int) -> String {
        scopedKey(scope, "\(deliveryId)#\(exerciseOrder)#\(setNumber)")
    }
}
