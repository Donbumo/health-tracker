package io.healthtracker.companion.core.healthconnect

import android.content.Intent
import androidx.activity.result.contract.ActivityResultContract
import java.time.Instant
import java.time.ZoneId

enum class HealthConnectRecordType(val storageValue: String, val importSupported: Boolean = true) {
    WEIGHT("weight"),
    BODY_FAT("body_fat"),
    LEAN_BODY_MASS("lean_body_mass", importSupported = false),
    BODY_WATER_MASS("body_water_mass", importSupported = false),
    STEPS("steps"),
    NUTRITION("nutrition");

    companion object {
        val defaults = setOf(WEIGHT, BODY_FAT, STEPS)
        fun fromStorage(value: String): HealthConnectRecordType? = entries.firstOrNull { it.storageValue == value }
    }
}

enum class HealthConnectAvailability {
    UNAVAILABLE_DEVICE,
    UNAVAILABLE_PROVIDER,
    UPDATE_REQUIRED,
    AVAILABLE,
}

enum class HealthConnectUiStatus {
    UNAVAILABLE_DEVICE,
    UNAVAILABLE_PROVIDER,
    UPDATE_REQUIRED,
    AVAILABLE_NOT_CONNECTED,
    PERMISSIONS_PARTIAL,
    ACCESS_REVOKED,
    CONNECTED,
    SYNCING,
    PAUSED,
    ERROR_RECOVERABLE,
}

data class HealthConnectMetadata(
    val id: String,
    val clientRecordId: String?,
    val clientRecordVersion: Long?,
    val dataOrigin: String,
    val lastModifiedTime: Instant,
)

sealed interface HealthConnectRecord {
    val metadata: HealthConnectMetadata
    val startTime: Instant
    val endTime: Instant?
    val zoneOffset: String?
}

data class HealthConnectWeight(
    override val metadata: HealthConnectMetadata,
    override val startTime: Instant,
    override val zoneOffset: String?,
    val kilograms: Double,
) : HealthConnectRecord { override val endTime: Instant? = null }

data class HealthConnectBodyFat(
    override val metadata: HealthConnectMetadata,
    override val startTime: Instant,
    override val zoneOffset: String?,
    val percentage: Double,
) : HealthConnectRecord { override val endTime: Instant? = null }

data class HealthConnectLeanBodyMass(
    override val metadata: HealthConnectMetadata,
    override val startTime: Instant,
    override val zoneOffset: String?,
    val kilograms: Double,
) : HealthConnectRecord { override val endTime: Instant? = null }

data class HealthConnectBodyWaterMass(
    override val metadata: HealthConnectMetadata,
    override val startTime: Instant,
    override val zoneOffset: String?,
    val kilograms: Double,
) : HealthConnectRecord { override val endTime: Instant? = null }

data class HealthConnectNutrition(
    override val metadata: HealthConnectMetadata,
    override val startTime: Instant,
    override val endTime: Instant,
    override val zoneOffset: String?,
    val endZoneOffset: String?,
    val mealType: String?,
    val name: String?,
    val caloriesKcal: Double?,
    val proteinGrams: Double?,
    val fatGrams: Double?,
    val carbohydrateGrams: Double?,
    val fiberGrams: Double?,
    val sugarGrams: Double?,
    val sodiumMilligrams: Double?,
) : HealthConnectRecord

data class HealthConnectPage(
    val records: List<HealthConnectRecord>,
    val nextPageToken: String?,
)

sealed interface HealthConnectChange {
    data class Upsert(val record: HealthConnectRecord) : HealthConnectChange
    data class Delete(val recordId: String) : HealthConnectChange
}

data class HealthConnectChangesPage(
    val changes: List<HealthConnectChange>,
    val nextToken: String,
    val hasMore: Boolean,
    val tokenExpired: Boolean,
)

data class DailyStepsAggregate(val date: String, val steps: Long?)

class HealthConnectGatewayException(
    val sanitizedCode: String,
    val retryable: Boolean,
    cause: Throwable? = null,
) : Exception(sanitizedCode, cause)

interface HealthConnectGateway {
    fun availability(): HealthConnectAvailability
    fun permissionRequestContract(): ActivityResultContract<Set<String>, Set<String>>
    fun permissionsFor(types: Set<HealthConnectRecordType>, includeBackground: Boolean = false): Set<String>
    suspend fun grantedPermissions(): Set<String>
    fun manageAccessIntent(): Intent
    fun providerIntent(): Intent
    fun backgroundReadAvailable(): Boolean
    suspend fun readPage(
        type: HealthConnectRecordType,
        start: Instant,
        end: Instant,
        pageToken: String? = null,
    ): HealthConnectPage
    suspend fun aggregateDailySteps(startDate: String, endDateExclusive: String, zoneId: ZoneId): List<DailyStepsAggregate>
    suspend fun changesToken(type: HealthConnectRecordType): String
    suspend fun changes(token: String): HealthConnectChangesPage
}
