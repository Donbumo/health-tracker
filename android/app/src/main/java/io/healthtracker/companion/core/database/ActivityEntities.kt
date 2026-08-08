package io.healthtracker.companion.core.database

import androidx.room.Entity
import androidx.room.Index

@Entity(
    tableName = "activity_imports",
    primaryKeys = ["accountScope", "serverIdentity", "publicId"],
    indices = [
        Index(value = ["accountScope", "serverIdentity", "state", "createdAt"]),
        Index(value = ["accountScope", "serverIdentity", "sha256"]),
    ],
)
data class ActivityImportEntity(
    val accountScope: String,
    val serverIdentity: String,
    val publicId: String,
    val serverPublicId: String?,
    val displayName: String,
    val detectedFormat: String?,
    val mimeType: String?,
    val sizeBytes: Long,
    val sha256: String,
    val sourceUri: String?,
    val uriPermissionPersisted: Boolean,
    val partialFileName: String?,
    val routePolicy: String,
    val redactStartMeters: Int,
    val redactEndMeters: Int,
    val state: String,
    val warningsJson: String,
    val errorCode: String?,
    val createdAt: String,
    val updatedAt: String,
)

@Entity(
    tableName = "activities",
    primaryKeys = ["accountScope", "serverIdentity", "publicId"],
    indices = [
        Index(value = ["accountScope", "serverIdentity", "startedAt"]),
        Index(value = ["accountScope", "serverIdentity", "discipline", "status"]),
    ],
)
data class ActivityEntity(
    val accountScope: String,
    val serverIdentity: String,
    val publicId: String,
    val discipline: String,
    val subtype: String?,
    val title: String?,
    val startedAt: String,
    val timezone: String?,
    val durationSeconds: Long?,
    val elapsedSeconds: Long?,
    val distanceMeters: String?,
    val caloriesKcal: String?,
    val averageHeartRate: String?,
    val maxHeartRate: String?,
    val sourceFormat: String,
    val sourceDevice: String?,
    val sourceFilename: String?,
    val status: String,
    val revision: Int,
    val summaryJson: String,
    val syncStatus: String,
    val updatedAt: String,
)

@Entity(
    tableName = "activity_laps",
    primaryKeys = ["accountScope", "serverIdentity", "activityPublicId", "lapIndex"],
    indices = [Index(value = ["accountScope", "serverIdentity", "activityPublicId"])],
)
data class ActivityLapEntity(
    val accountScope: String,
    val serverIdentity: String,
    val activityPublicId: String,
    val lapIndex: Int,
    val startedAt: String?,
    val durationSeconds: String?,
    val distanceMeters: String?,
    val metricsJson: String,
)

@Entity(
    tableName = "activity_series_metadata",
    primaryKeys = ["accountScope", "serverIdentity", "activityPublicId"],
)
data class ActivitySeriesMetadataEntity(
    val accountScope: String,
    val serverIdentity: String,
    val activityPublicId: String,
    val sampleCount: Long,
    val availableMetricsJson: String,
    val startsAt: String?,
    val endsAt: String?,
    val cachedSeriesFileName: String?,
    val updatedAt: String,
)

@Entity(
    tableName = "activity_routes",
    primaryKeys = ["accountScope", "serverIdentity", "activityPublicId"],
    indices = [Index(value = ["accountScope", "serverIdentity", "visibilityState"])],
)
data class ActivityRouteEntity(
    val accountScope: String,
    val serverIdentity: String,
    val activityPublicId: String,
    val visibilityState: String,
    val privacyPolicy: String,
    val pointCount: Long,
    val hasElevation: Boolean,
    val cachedRouteFileName: String?,
    val deletedAt: String?,
    val updatedAt: String,
)

@Entity(
    tableName = "activity_duplicate_candidates",
    primaryKeys = ["accountScope", "serverIdentity", "publicId"],
    indices = [Index(value = ["accountScope", "serverIdentity", "resolution"])],
)
data class ActivityDuplicateCandidateEntity(
    val accountScope: String,
    val serverIdentity: String,
    val publicId: String,
    val activityPublicId: String,
    val candidateActivityPublicId: String,
    val classification: String,
    val evidenceJson: String,
    val resolution: String,
    val createdAt: String,
)

@Entity(
    tableName = "plan_activity_links",
    primaryKeys = ["accountScope", "serverIdentity", "publicId"],
    indices = [Index(value = ["accountScope", "serverIdentity", "activityPublicId"], unique = true)],
)
data class PlanActivityLinkEntity(
    val accountScope: String,
    val serverIdentity: String,
    val publicId: String,
    val activityPublicId: String,
    val plannedWorkoutPublicId: String,
    val linkType: String,
    val state: String,
    val evidenceJson: String,
    val updatedAt: String,
)

@Entity(
    tableName = "plan_actual_comparisons",
    primaryKeys = ["accountScope", "serverIdentity", "publicId"],
    indices = [Index(value = ["accountScope", "serverIdentity", "activityPublicId"])],
)
data class PlanActualComparisonEntity(
    val accountScope: String,
    val serverIdentity: String,
    val publicId: String,
    val activityPublicId: String,
    val planActivityLinkPublicId: String,
    val status: String,
    val summaryJson: String,
    val createdAt: String,
)

@Entity(
    tableName = "activity_operations",
    primaryKeys = ["accountScope", "serverIdentity", "operationId"],
    indices = [
        Index(value = ["accountScope", "serverIdentity", "status", "createdAt"]),
        Index(value = ["accountScope", "serverIdentity", "importPublicId"]),
        Index(value = ["accountScope", "serverIdentity", "idempotencyKey"], unique = true),
    ],
)
data class ActivityOperationEntity(
    val accountScope: String,
    val serverIdentity: String,
    val operationId: String,
    val importPublicId: String,
    val operationType: String,
    val idempotencyKey: String,
    val payloadJson: String,
    val payloadHash: String,
    val status: String,
    val attemptCount: Int,
    val notBeforeEpochMs: Long,
    val createdAt: String,
    val lastErrorCode: String?,
)
