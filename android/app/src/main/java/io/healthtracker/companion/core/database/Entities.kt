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
    val sourceWorkoutId: String? = null,
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
    val prescribedWeightKg: String? = null,
    val prescribedLoadValue: String? = null,
    val prescribedLoadUnit: String? = null,
    val prescribedLoadMode: String? = null,
    val prescribedRir: String? = null,
    val prescribedRpe: String? = null,
    val prescribedNotes: String? = null,
    val prescribedLoadDetailsJson: String? = null,
)

@Entity(
    tableName = "exercise_catalog",
    primaryKeys = ["accountScope", "publicId"],
    indices = [Index(value = ["accountScope", "normalizedName"])],
)
data class ExerciseCatalogEntity(
    val accountScope: String,
    val publicId: String,
    val name: String,
    val normalizedName: String,
    val aliases: String,
    val selectable: Boolean,
    val archived: Boolean,
    val preferredLoadMode: String?,
    val preferredUnit: String?,
    val updatedAt: String,
)

@Entity(tableName = "planning_catalog_state", primaryKeys = ["accountScope", "query"])
data class PlanningCatalogStateEntity(
    val accountScope: String,
    val query: String,
    val nextCursor: String?,
    val hasMore: Boolean,
    val updatedAt: String,
)

@Entity(
    tableName = "mobile_plans",
    primaryKeys = ["accountScope", "publicId"],
    indices = [Index(value = ["accountScope", "status", "updatedAt"])],
)
data class MobilePlanEntity(
    val accountScope: String,
    val publicId: String,
    val name: String,
    val description: String?,
    val status: String,
    val revision: Int,
    val activeVersionId: String?,
    val activeVersion: Int?,
    val syncStatus: String,
    val createdAt: String,
    val updatedAt: String,
    val archivedAt: String?,
)

@Entity(
    tableName = "mobile_plan_workouts",
    primaryKeys = ["accountScope", "publicId"],
    foreignKeys = [ForeignKey(
        entity = MobilePlanEntity::class,
        parentColumns = ["accountScope", "publicId"],
        childColumns = ["accountScope", "planPublicId"],
        onDelete = ForeignKey.CASCADE,
    )],
    indices = [Index(value = ["accountScope", "planPublicId", "position"], unique = true)],
)
data class MobilePlanWorkoutEntity(
    val accountScope: String,
    val publicId: String,
    val planPublicId: String,
    val name: String,
    val notes: String?,
    val position: Int,
    val estimatedDurationSeconds: Int?,
    val revision: Int,
    val syncStatus: String,
    val createdAt: String,
    val updatedAt: String,
)

@Entity(
    tableName = "mobile_plan_exercises",
    primaryKeys = ["accountScope", "workoutPublicId", "publicId"],
    foreignKeys = [ForeignKey(
        entity = MobilePlanWorkoutEntity::class,
        parentColumns = ["accountScope", "publicId"],
        childColumns = ["accountScope", "workoutPublicId"],
        onDelete = ForeignKey.CASCADE,
    )],
    indices = [Index(value = ["accountScope", "workoutPublicId", "position"], unique = true)],
)
data class MobilePlanExerciseEntity(
    val accountScope: String,
    val workoutPublicId: String,
    val publicId: String,
    val catalogExerciseId: String?,
    val name: String,
    val notes: String?,
    val position: Int,
)

@Entity(
    tableName = "mobile_plan_sets",
    primaryKeys = ["accountScope", "workoutPublicId", "exercisePublicId", "publicId"],
    foreignKeys = [ForeignKey(
        entity = MobilePlanExerciseEntity::class,
        parentColumns = ["accountScope", "workoutPublicId", "publicId"],
        childColumns = ["accountScope", "workoutPublicId", "exercisePublicId"],
        onDelete = ForeignKey.CASCADE,
    )],
    indices = [Index(value = ["accountScope", "workoutPublicId", "exercisePublicId", "setNumber"], unique = true)],
)
data class MobilePlanSetEntity(
    val accountScope: String,
    val workoutPublicId: String,
    val exercisePublicId: String,
    val publicId: String,
    val setNumber: Int,
    val reps: Int?,
    val repsMin: Int?,
    val repsMax: Int?,
    val weightKg: String?,
    val loadValue: String?,
    val loadUnit: String,
    val loadMode: String,
    val loadDetailsJson: String?,
    val rir: String?,
    val rpe: String?,
    val restSeconds: Int?,
    val durationSeconds: Int?,
    val distanceMeters: String?,
    val notes: String?,
)

@Entity(tableName = "planning_conflicts", primaryKeys = ["accountScope", "entityId"])
data class PlanningConflictEntity(
    val accountScope: String,
    val entityId: String,
    val entityType: String,
    val localRevision: Int,
    val serverRevision: Int?,
    val changedFields: String,
    val localName: String?,
    val remoteName: String?,
    val createdAt: String,
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

@Entity(
    tableName = "history_sessions",
    primaryKeys = ["accountScope", "publicId"],
    indices = [
        Index(value = ["accountScope", "completedAt"]),
        Index(value = ["accountScope", "clientEventId"], unique = true),
    ],
)
data class HistorySessionEntity(
    val accountScope: String,
    val publicId: String,
    val clientEventId: String,
    val plannedWorkoutId: String?,
    val trainingPlanId: String?,
    val trainingPlanVersionId: String?,
    val name: String,
    val performedAt: String,
    val startedAt: String?,
    val completedAt: String,
    val timezone: String,
    val durationSeconds: Int?,
    val exerciseCount: Int,
    val setCount: Int,
    val volumeKg: String?,
    val volumePartial: Boolean,
    val source: String,
    val syncStatus: String,
    val notes: String?,
    val detailCached: Boolean,
    val updatedAt: String,
)

@Entity(
    tableName = "history_exercises",
    primaryKeys = ["accountScope", "sessionPublicId", "exerciseOrder"],
    foreignKeys = [ForeignKey(
        entity = HistorySessionEntity::class,
        parentColumns = ["accountScope", "publicId"],
        childColumns = ["accountScope", "sessionPublicId"],
        onDelete = ForeignKey.CASCADE,
    )],
    indices = [
        Index(value = ["accountScope", "sessionPublicId"]),
        Index(value = ["accountScope", "exercisePublicId"]),
    ],
)
data class HistoryExerciseEntity(
    val accountScope: String,
    val sessionPublicId: String,
    val exerciseOrder: Int,
    val exercisePublicId: String?,
    val name: String,
    val notes: String?,
)

@Entity(
    tableName = "history_sets",
    primaryKeys = ["accountScope", "sessionPublicId", "exerciseOrder", "setNumber"],
    foreignKeys = [ForeignKey(
        entity = HistoryExerciseEntity::class,
        parentColumns = ["accountScope", "sessionPublicId", "exerciseOrder"],
        childColumns = ["accountScope", "sessionPublicId", "exerciseOrder"],
        onDelete = ForeignKey.CASCADE,
    )],
    indices = [Index(value = ["accountScope", "sessionPublicId", "exerciseOrder"])],
)
data class HistorySetEntity(
    val accountScope: String,
    val sessionPublicId: String,
    val exerciseOrder: Int,
    val setNumber: Int,
    val weightKg: String?,
    val displayValue: String?,
    val displayUnit: String?,
    val loadMode: String,
    val reps: Int,
    val rir: String?,
    val rpe: String?,
    val restSeconds: Int?,
    val durationSeconds: String?,
    val distanceMeters: String?,
    val notes: String?,
)

@Entity(tableName = "history_pages", primaryKeys = ["accountScope", "cacheKey", "sessionPublicId"])
data class HistoryPageEntity(
    val accountScope: String,
    val cacheKey: String,
    val sessionPublicId: String,
    val position: Int,
)

@Entity(tableName = "history_query_state", primaryKeys = ["accountScope", "cacheKey"])
data class HistoryQueryStateEntity(
    val accountScope: String,
    val cacheKey: String,
    val nextCursor: String?,
    val hasMore: Boolean,
    val updatedAt: String,
)

@Entity(tableName = "progress_summaries", primaryKeys = ["accountScope", "range"])
data class ProgressSummaryEntity(
    val accountScope: String,
    val range: String,
    val sessions: Int,
    val trainingDays: Int,
    val distinctExercises: Int,
    val completedSets: Int,
    val totalReps: Int,
    val volumeKg: String?,
    val volumePartial: Boolean,
    val durationSeconds: Int,
    val comparisonJson: String?,
    val updatedAt: String,
)

@Entity(
    tableName = "progress_exercises",
    primaryKeys = ["accountScope", "range", "publicId"],
    indices = [Index(value = ["accountScope", "range", "lastPerformedAt"])],
)
data class ProgressExerciseEntity(
    val accountScope: String,
    val range: String,
    val publicId: String,
    val name: String,
    val lastPerformedAt: String?,
    val sessionCount: Int,
    val setCount: Int,
    val bestLoadKg: String?,
    val bestReps: Int?,
    val bestRepsWeightKg: String?,
    val volumeKg: String?,
    val volumePartial: Boolean,
    val loadComparable: Boolean,
    val loadModes: String,
    val trend: String,
    val updatedAt: String,
)

@Entity(tableName = "progress_points", primaryKeys = ["accountScope", "range", "exercisePublicId", "sessionPublicId"])
data class ProgressPointEntity(
    val accountScope: String,
    val range: String,
    val exercisePublicId: String,
    val sessionPublicId: String,
    val date: String,
    val performedAt: String,
    val bestLoadKg: String?,
    val bestReps: Int?,
    val volumeKg: String?,
    val setCount: Int,
    val averageRir: String?,
    val averageRpe: String?,
    val loadComparable: Boolean,
)

@Entity(tableName = "personal_records", primaryKeys = ["accountScope", "range", "exercisePublicId", "type"])
data class PersonalRecordEntity(
    val accountScope: String,
    val range: String,
    val exercisePublicId: String,
    val type: String,
    val value: String,
    val unit: String,
    val date: String,
    val sessionPublicId: String,
    val setIndex: Int?,
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
