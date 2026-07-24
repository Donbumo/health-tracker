package io.healthtracker.companion.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.KSerializer
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.JsonEncoder
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import java.math.BigDecimal

const val CONTRACT_VERSION = "1.0"

object BigDecimalSerializer : KSerializer<BigDecimal> {
    override val descriptor: SerialDescriptor =
        PrimitiveSerialDescriptor("BigDecimal", PrimitiveKind.STRING)

    override fun deserialize(decoder: Decoder): BigDecimal {
        val raw = if (decoder is JsonDecoder) decoder.decodeJsonElement().toString().trim('"')
        else decoder.decodeString()
        return raw.toBigDecimal()
    }

    override fun serialize(encoder: Encoder, value: BigDecimal) {
        if (encoder is JsonEncoder) encoder.encodeJsonElement(JsonPrimitive(value))
        else encoder.encodeString(value.toPlainString())
    }
}

@Serializable
data class ApiEnvelope<T>(val data: T, val meta: ApiMeta? = null)

@Serializable
data class ApiMeta(
    @SerialName("request_id") val requestId: String? = null,
    val pagination: Pagination? = null,
)

@Serializable
data class Pagination(
    val page: Int = 1,
    @SerialName("per_page") val perPage: Int = 0,
    @SerialName("has_more") val hasMore: Boolean = false,
)

@Serializable
data class ErrorEnvelope(val error: ApiErrorBody)

@Serializable
data class ApiErrorBody(
    val code: String,
    val message: String,
    val details: JsonObject? = null,
    @SerialName("request_id") val requestId: String? = null,
)

@Serializable
data class DeviceRegistration(
    @SerialName("device_id") val deviceId: String,
    val name: String,
    val platform: String = "android",
    @SerialName("app_version") val appVersion: String,
    @SerialName("os_version") val osVersion: String,
)

@Serializable
data class LoginRequest(val email: String, val password: String, val device: DeviceRegistration)

@Serializable
data class RefreshRequest(@SerialName("refresh_token") val refreshToken: String)

@Serializable
data class TokenResponse(
    @SerialName("access_token") val accessToken: String,
    @SerialName("refresh_token") val refreshToken: String,
    @SerialName("token_type") val tokenType: String,
    @SerialName("expires_in") val expiresIn: Long,
    @SerialName("refresh_expires_at") val refreshExpiresAt: String,
)

@Serializable
data class HealthResponse(val status: String, val app: String)

@Serializable
data class UserProfile(
    val id: String,
    val email: String,
    val role: String,
    val timezone: String,
    @SerialName("created_at") val createdAt: String,
    val capabilities: Map<String, Boolean> = emptyMap(),
)

@Serializable
data class BootstrapResponse(
    @SerialName("schema_version") val schemaVersion: String,
    @SerialName("server_time") val serverTime: String,
    val cursor: String,
    @SerialName("active_routine") val activeRoutine: JsonObject? = null,
    @SerialName("planned_workouts") val plannedWorkouts: List<PlannedWorkoutDto>,
    @SerialName("completed_workouts") val completedWorkouts: List<CompletedWorkoutDto>,
    val capabilities: Map<String, Boolean>,
    val limits: SyncLimits,
    val schemas: Map<String, String>,
    val device: BootstrapDevice,
    val companion: BootstrapCompanion,
)

@Serializable
data class SyncLimits(
    @SerialName("push_operations") val pushOperations: Int,
    @SerialName("pull_limit") val pullLimit: Int,
    @SerialName("json_bytes") val jsonBytes: Int,
)

@Serializable
data class BootstrapDevice(
    @SerialName("device_id") val deviceId: String,
    @SerialName("session_id") val sessionId: String,
)

@Serializable
data class BootstrapCompanion(
    val profile: CompanionProfileDto? = null,
    val deliveries: List<DeliveryDto> = emptyList(),
    val versions: Map<String, String>,
)

@Serializable
data class PlannedWorkoutDto(
    @SerialName("schema_version") val schemaVersion: String,
    val id: String,
    @SerialName("training_plan_id") val trainingPlanId: String,
    @SerialName("training_plan_version_id") val trainingPlanVersionId: String,
    @SerialName("scheduled_for_date") val scheduledForDate: String,
    val timezone: String,
    val status: String,
    val title: String,
    val snapshot: JsonObject,
    @SerialName("source_version") val sourceVersion: Int,
    val revision: Int,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String,
    @SerialName("completed_at") val completedAt: String? = null,
    @SerialName("cancelled_at") val cancelledAt: String? = null,
    val deleted: Boolean,
)

@Serializable
data class CompletedWorkoutDto(
    @SerialName("schema_version") val schemaVersion: String,
    val id: String? = null,
    @SerialName("client_event_id") val clientEventId: String? = null,
    @SerialName("planned_workout_id") val plannedWorkoutId: String? = null,
    @SerialName("training_plan_id") val trainingPlanId: String? = null,
    @SerialName("training_plan_version_id") val trainingPlanVersionId: String? = null,
    @SerialName("planned_week_number") val plannedWeekNumber: Int? = null,
    @SerialName("planned_day_number") val plannedDayNumber: Int? = null,
    @SerialName("started_at") val startedAt: String,
    @SerialName("completed_at") val completedAt: String,
    val timezone: String,
    @SerialName("duration_seconds") val durationSeconds: Int? = null,
    @SerialName("average_heart_rate_bpm") val averageHeartRateBpm: Int? = null,
    @SerialName("calories_burned") @Serializable(with = BigDecimalSerializer::class)
    val caloriesBurned: BigDecimal? = null,
    val notes: String? = null,
    val revision: Int? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
    val exercises: List<CompletedExerciseDto>,
)

@Serializable
data class CompletedExerciseDto(
    @SerialName("exercise_order") val exerciseOrder: Int,
    @SerialName("planned_exercise_order") val plannedExerciseOrder: Int,
    val name: String,
    val notes: String? = null,
    val sets: List<CompletedSetDto>,
)

@Serializable
data class CompletedSetDto(
    @SerialName("set_number") val setNumber: Int,
    @SerialName("planned_set_number") val plannedSetNumber: Int,
    @SerialName("weight_kg") @Serializable(with = BigDecimalSerializer::class)
    val weightKg: BigDecimal,
    @SerialName("load_details") val loadDetails: LoadDetailsDto? = null,
    val reps: Int,
    @Serializable(with = BigDecimalSerializer::class) val rir: BigDecimal? = null,
    @Serializable(with = BigDecimalSerializer::class) val rpe: BigDecimal? = null,
    @SerialName("rest_seconds") val restSeconds: Int? = null,
    @SerialName("duration_seconds") val durationSeconds: Int? = null,
    val notes: String? = null,
)

@Serializable
data class WeightComponentDto(val value: String, val unit: String)

@Serializable
data class LoadDetailsDto(
    @SerialName("schema_version") val schemaVersion: String = CONTRACT_VERSION,
    @SerialName("load_mode") val loadMode: String,
    @SerialName("original_input") val originalInput: JsonObject,
    @SerialName("original_unit") val originalUnit: String,
    val components: Map<String, WeightComponentDto>,
    @SerialName("normalized_total_kg") val normalizedTotalKg: String,
    @SerialName("calculated_total_lb") val calculatedTotalLb: String,
    @SerialName("display_total") val displayTotal: WeightComponentDto,
    @SerialName("bodyweight_kg") val bodyweightKg: JsonElement = JsonNull,
    val assistance: JsonElement = JsonNull,
    @SerialName("calculation_version") val calculationVersion: String = CONTRACT_VERSION,
    val warnings: List<String>? = null,
)

@Serializable
data class NegotiationRequest(
    @SerialName("schema_version") val schemaVersion: String = CONTRACT_VERSION,
    @SerialName("protocol_versions") val protocolVersions: List<String> = listOf(CONTRACT_VERSION),
    @SerialName("workout_schema_versions") val workoutSchemaVersions: List<String> = listOf(CONTRACT_VERSION),
    @SerialName("result_schema_versions") val resultSchemaVersions: List<String> = listOf(CONTRACT_VERSION),
    val features: List<String>,
    val metrics: List<String>,
    val limits: CompanionLimits,
    @SerialName("base_revision") val baseRevision: Int? = null,
)

@Serializable
data class CompanionLimits(
    @SerialName("max_payload_bytes") val maxPayloadBytes: Int = 262_144,
    @SerialName("max_progress_events_per_workout") val maxProgressEventsPerWorkout: Int = 500,
)

@Serializable
data class NegotiationResponse(
    @SerialName("selected_protocol_version") val selectedProtocolVersion: String,
    @SerialName("selected_workout_schema_version") val selectedWorkoutSchemaVersion: String,
    @SerialName("selected_result_schema_version") val selectedResultSchemaVersion: String,
    @SerialName("accepted_features") val acceptedFeatures: List<String>,
    @SerialName("rejected_features") val rejectedFeatures: List<String>,
    @SerialName("accepted_metrics") val acceptedMetrics: List<String>,
    @SerialName("rejected_metrics") val rejectedMetrics: List<String>,
    @SerialName("effective_limits") val effectiveLimits: CompanionLimits,
    @SerialName("server_capabilities") val serverCapabilities: Map<String, Boolean>,
    val profile: CompanionProfileDto,
)

@Serializable
data class CompanionProfileDto(
    @SerialName("schema_version") val schemaVersion: String,
    val id: String,
    @SerialName("device_id") val deviceId: String,
    @SerialName("protocol_version") val protocolVersion: String,
    @SerialName("workout_schema_version") val workoutSchemaVersion: String,
    @SerialName("result_schema_version") val resultSchemaVersion: String,
    @SerialName("supported_features") val supportedFeatures: List<String>,
    @SerialName("supported_metrics") val supportedMetrics: List<String>,
    val limits: CompanionLimits,
    val revision: Int,
    @SerialName("last_negotiated_at") val lastNegotiatedAt: String,
    val revoked: Boolean,
)

@Serializable
data class DeliveryCreateRequest(
    @SerialName("schema_version") val schemaVersion: String = CONTRACT_VERSION,
    @SerialName("planned_workout_id") val plannedWorkoutId: String,
    @SerialName("expires_at") val expiresAt: String? = null,
)

@Serializable
data class DeliveryDto(
    @SerialName("schema_version") val schemaVersion: String,
    val id: String,
    @SerialName("device_id") val deviceId: String,
    @SerialName("profile_id") val profileId: String,
    @SerialName("planned_workout_id") val plannedWorkoutId: String,
    @SerialName("package_schema_version") val packageSchemaVersion: String,
    @SerialName("package_hash") val packageHash: String,
    val status: String,
    val revision: Int,
    @SerialName("last_client_sequence") val lastClientSequence: Int,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String,
    @SerialName("expires_at") val expiresAt: String? = null,
    @SerialName("failure_code") val failureCode: String? = null,
    @SerialName("training_session_id") val trainingSessionId: String? = null,
    val duplicate: Boolean = false,
)

@Serializable
data class WorkoutPackageDto(
    @SerialName("schema_version") val schemaVersion: String,
    @SerialName("package_id") val packageId: String,
    @SerialName("planned_workout_id") val plannedWorkoutId: String,
    @SerialName("plan_id") val planId: String,
    @SerialName("plan_version_id") val planVersionId: String,
    val title: String,
    @SerialName("scheduled_for_date") val scheduledForDate: String,
    val timezone: String,
    val revision: Int,
    @SerialName("generated_at") val generatedAt: String,
    @SerialName("expires_at") val expiresAt: String? = null,
    val exercises: List<PackageExerciseDto>,
    @SerialName("supported_metrics") val supportedMetrics: List<String>,
    @SerialName("unsupported_fields") val unsupportedFields: List<String>,
    @SerialName("package_hash") val packageHash: String,
    @SerialName("server_capabilities") val serverCapabilities: Map<String, Boolean>,
    @SerialName("device_capabilities") val deviceCapabilities: JsonObject,
    @SerialName("compatibility_warnings") val compatibilityWarnings: List<String>,
)

@Serializable
data class PackageExerciseDto(
    @SerialName("exercise_order") val exerciseOrder: Int,
    val name: String,
    val notes: String? = null,
    val sets: List<JsonObject>,
)

@Serializable
data class DeliveryOperationRequest(
    @SerialName("schema_version") val schemaVersion: String = CONTRACT_VERSION,
    @SerialName("client_operation_id") val clientOperationId: String,
    @SerialName("base_revision") val baseRevision: Int,
    @SerialName("received_at") val receivedAt: String? = null,
    @SerialName("package_hash") val packageHash: String? = null,
    @SerialName("reason_code") val reasonCode: String? = null,
)

@Serializable
data class ProgressRequest(
    @SerialName("schema_version") val schemaVersion: String = CONTRACT_VERSION,
    @SerialName("client_event_id") val clientEventId: String,
    @SerialName("client_sequence") val clientSequence: Int,
    @SerialName("event_type") val eventType: String,
    @SerialName("occurred_at") val occurredAt: String,
    val payload: JsonObject,
)

@Serializable
data class CompletionRequest(
    @SerialName("schema_version") val schemaVersion: String = CONTRACT_VERSION,
    @SerialName("client_event_id") val clientEventId: String,
    @SerialName("package_hash") val packageHash: String,
    @SerialName("base_revision") val baseRevision: Int,
    val result: CompletedWorkoutDto,
)

@Serializable
data class CompletionResponse(
    val delivery: DeliveryDto,
    @SerialName("completed_workout") val completedWorkout: CompletedWorkoutDto,
    val duplicate: Boolean,
)

@Serializable
data class PullResponse(
    @SerialName("schema_version") val schemaVersion: String,
    val changes: List<SyncChangeDto>,
    @SerialName("next_cursor") val nextCursor: String,
    @SerialName("has_more") val hasMore: Boolean,
    @SerialName("server_time") val serverTime: String,
)

@Serializable
data class SyncStatusResponse(
    @SerialName("schema_version") val schemaVersion: String,
    @SerialName("device_id") val deviceId: String,
    val cursor: String,
    @SerialName("last_pull_at_sequence") val lastPullAtSequence: Long,
    @SerialName("last_push_at") val lastPushAt: String? = null,
    @SerialName("server_sequence") val serverSequence: Long,
    @SerialName("server_time") val serverTime: String,
)

@Serializable
data class SyncChangeDto(
    @SerialName("entity_type") val entityType: String,
    @SerialName("entity_id") val entityId: String,
    val operation: String,
    val revision: Int,
    @SerialName("changed_at") val changedAt: String,
    @SerialName("payload_hash") val payloadHash: String,
    val payload: JsonElement? = null,
)

@Serializable
data class PushRequest(
    @SerialName("schema_version") val schemaVersion: String = CONTRACT_VERSION,
    @SerialName("batch_id") val batchId: String,
    val operations: List<PushOperation>,
)

@Serializable
data class PushOperation(
    @SerialName("client_operation_id") val clientOperationId: String,
    @SerialName("entity_type") val entityType: String,
    val operation: String,
    @SerialName("entity_id") val entityId: String,
    @SerialName("base_revision") val baseRevision: Int? = null,
    val payload: JsonObject,
)

@Serializable
data class PushResponse(
    @SerialName("schema_version") val schemaVersion: String,
    @SerialName("batch_id") val batchId: String,
    val results: List<PushResult>,
    val summary: Map<String, Int>,
    @SerialName("server_time") val serverTime: String,
)

@Serializable
data class PushResult(
    @SerialName("client_operation_id") val clientOperationId: String,
    val status: String,
    @SerialName("entity_id") val entityId: String? = null,
    val revision: Int? = null,
    @SerialName("error_code") val errorCode: String? = null,
    val conflict: JsonObject? = null,
)

enum class AuthState {
    NO_SERVER, SIGNED_OUT, AUTHENTICATING, AUTHENTICATED, TOKEN_EXPIRED,
    DEVICE_REVOKED, SERVER_INCOMPATIBLE, OFFLINE, TEMPORARY_ERROR, PERMANENT_ERROR,
}

enum class SyncStatus { IDLE, SYNCING, PENDING, CONFLICT, ERROR }

enum class AppErrorCode {
    NETWORK_UNAVAILABLE, TIMEOUT, UNAUTHORIZED, REFRESH_FAILED, DEVICE_REVOKED,
    SERVER_INCOMPATIBLE, SCHEMA_INCOMPATIBLE, PACKAGE_HASH_MISMATCH, PACKAGE_EXPIRED,
    REVISION_CONFLICT, SUBMISSION_CONFLICT, VALIDATION_ERROR, RATE_LIMITED,
    SERVER_ERROR, LOCAL_STORAGE_ERROR, DRAFT_CORRUPT, UNKNOWN,
}

data class AppFailure(
    val code: AppErrorCode,
    val userMessage: String,
    val retryable: Boolean,
    val retryAfterSeconds: Long? = null,
    val requestId: String? = null,
) : RuntimeException(userMessage)
