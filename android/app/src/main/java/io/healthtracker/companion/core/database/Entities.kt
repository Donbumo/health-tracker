package io.healthtracker.companion.core.database

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index

@Entity(tableName = "accounts", primaryKeys = ["scope"])
data class AccountEntity(
    val scope: String,
    val serverUrl: String,
    val userPublicId: String,
    val displayEmail: String,
    val deviceId: String,
    val timezone: String,
    val createdAt: String,
)

@Entity(tableName = "local_profiles", primaryKeys = ["accountScope"])
data class LocalProfileEntity(
    val accountScope: String,
    val profileId: String?,
    val protocolVersion: String?,
    val workoutSchemaVersion: String?,
    val resultSchemaVersion: String?,
    val revision: Int?,
    val negotiatedAt: String?,
)

@Entity(
    tableName = "planned_workouts",
    primaryKeys = ["accountScope", "id"],
    indices = [Index(value = ["accountScope", "scheduledForDate"]), Index(value = ["accountScope", "status"])],
)
data class PlannedWorkoutEntity(
    val accountScope: String,
    val id: String,
    val planId: String,
    val planVersionId: String,
    val scheduledForDate: String,
    val timezone: String,
    val status: String,
    val title: String,
    val revision: Int,
    val updatedAt: String,
    val deleted: Boolean,
)

@Entity(
    tableName = "workout_packages",
    primaryKeys = ["accountScope", "packageId"],
    indices = [Index(value = ["accountScope", "plannedWorkoutId"], unique = true)],
)
data class WorkoutPackageEntity(
    val accountScope: String,
    val packageId: String,
    val deliveryId: String,
    val plannedWorkoutId: String,
    val planId: String,
    val planVersionId: String,
    val title: String,
    val scheduledForDate: String,
    val timezone: String,
    val revision: Int,
    val generatedAt: String,
    val expiresAt: String?,
    val packageHash: String,
    val verifiedAt: String,
)

@Entity(
    tableName = "package_exercises",
    primaryKeys = ["accountScope", "packageId", "exerciseOrder"],
    foreignKeys = [
        ForeignKey(
            entity = WorkoutPackageEntity::class,
            parentColumns = ["accountScope", "packageId"],
            childColumns = ["accountScope", "packageId"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [Index(value = ["accountScope", "packageId"])],
)
data class PackageExerciseEntity(
    val accountScope: String,
    val packageId: String,
    val exerciseOrder: Int,
    val name: String,
    val notes: String?,
)

@Entity(
    tableName = "package_sets",
    primaryKeys = ["accountScope", "packageId", "exerciseOrder", "setNumber"],
    foreignKeys = [
        ForeignKey(
            entity = PackageExerciseEntity::class,
            parentColumns = ["accountScope", "packageId", "exerciseOrder"],
            childColumns = ["accountScope", "packageId", "exerciseOrder"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [Index(value = ["accountScope", "packageId", "exerciseOrder"])],
)
data class PackageSetEntity(
    val accountScope: String,
    val packageId: String,
    val exerciseOrder: Int,
    val setNumber: Int,
    val reps: Int?,
    val repsMin: Int?,
    val repsMax: Int?,
    val durationSeconds: Int?,
    val distanceMeters: String?,
    val restSeconds: Int?,
    val target: String?,
)

@Entity(
    tableName = "deliveries",
    primaryKeys = ["accountScope", "id"],
    indices = [Index(value = ["accountScope", "plannedWorkoutId"]), Index(value = ["accountScope", "status"])],
)
data class DeliveryEntity(
    val accountScope: String,
    val id: String,
    val plannedWorkoutId: String,
    val profileId: String,
    val packageHash: String,
    val status: String,
    val revision: Int,
    val lastClientSequence: Int,
    val expiresAt: String?,
    val trainingSessionId: String?,
    val updatedAt: String,
)

@Entity(
    tableName = "workout_drafts",
    primaryKeys = ["accountScope", "deliveryId"],
    indices = [Index(value = ["accountScope", "status"])],
)
data class WorkoutDraftEntity(
    val accountScope: String,
    val deliveryId: String,
    val packageId: String,
    val clientSubmissionId: String,
    val clientEventId: String,
    val schemaVersion: String,
    val packageHash: String,
    val status: String,
    val startedAt: String,
    val pausedAt: String?,
    val elapsedSeconds: Int,
    val averageHeartRateBpm: Int?,
    val caloriesBurned: String?,
    val notes: String?,
    val checkpointSequence: Int,
    val payloadHash: String,
    val updatedAt: String,
    val expiresAt: String,
    val corruptReasonCode: String?,
)

@Entity(
    tableName = "draft_sets",
    primaryKeys = ["accountScope", "deliveryId", "exerciseOrder", "setNumber"],
    foreignKeys = [
        ForeignKey(
            entity = WorkoutDraftEntity::class,
            parentColumns = ["accountScope", "deliveryId"],
            childColumns = ["accountScope", "deliveryId"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [Index(value = ["accountScope", "deliveryId"])],
)
data class DraftSetEntity(
    val accountScope: String,
    val deliveryId: String,
    val exerciseOrder: Int,
    val setNumber: Int,
    val plannedSetNumber: Int,
    val reps: Int,
    val rir: String?,
    val rpe: String?,
    val weightKg: String,
    val loadDetailsJson: String?,
    val durationSeconds: Int?,
    val distanceMeters: String?,
    val restSeconds: Int?,
    val notes: String?,
    val checkpointSequence: Int?,
    val completed: Boolean,
    val updatedAt: String,
)

@Entity(
    tableName = "pending_actions",
    indices = [
        Index(value = ["accountScope", "status", "notBeforeEpochMs"]),
        Index(value = ["accountScope", "idempotencyKey"], unique = true),
    ],
)
data class PendingActionEntity(
    @androidx.room.PrimaryKey(autoGenerate = true) val localId: Long = 0,
    val accountScope: String,
    val actionType: String,
    val entityId: String,
    val idempotencyKey: String,
    val payloadJson: String,
    val payloadHash: String,
    val status: String = "pending",
    val attemptCount: Int = 0,
    val notBeforeEpochMs: Long = 0,
    val createdAt: String,
    val lastErrorCode: String? = null,
)

@Entity(
    tableName = "recent_sessions",
    primaryKeys = ["accountScope", "id"],
    indices = [Index(value = ["accountScope", "completedAt"])],
)
data class RecentSessionEntity(
    val accountScope: String,
    val id: String,
    val clientEventId: String,
    val plannedWorkoutId: String?,
    val title: String,
    val completedAt: String,
    val durationSeconds: Int?,
    val exerciseCount: Int,
    val setCount: Int,
    val totalLoadKg: String,
    val origin: String,
    val syncStatus: String,
    val summary: String,
)

@Entity(tableName = "sync_state", primaryKeys = ["accountScope", "deviceId"])
data class SyncStateEntity(
    val accountScope: String,
    val deviceId: String,
    val cursor: String,
    val lastSyncAt: String?,
    val lastServerTime: String?,
    val lastErrorCode: String?,
)
