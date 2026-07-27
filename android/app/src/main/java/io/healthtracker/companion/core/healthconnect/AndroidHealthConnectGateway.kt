package io.healthtracker.companion.core.healthconnect

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.activity.result.contract.ActivityResultContract
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.HealthConnectFeatures
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.changes.DeletionChange
import androidx.health.connect.client.changes.UpsertionChange
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.BodyFatRecord
import androidx.health.connect.client.records.BodyWaterMassRecord
import androidx.health.connect.client.records.LeanBodyMassRecord
import androidx.health.connect.client.records.MealType
import androidx.health.connect.client.records.NutritionRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.WeightRecord
import androidx.health.connect.client.request.AggregateRequest
import androidx.health.connect.client.request.ChangesTokenRequest
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import java.io.IOException
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import kotlin.reflect.KClass

class AndroidHealthConnectGateway(private val context: Context) : HealthConnectGateway {
    private val providerPackage = "com.google.android.apps.healthdata"

    override fun availability(): HealthConnectAvailability {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) return HealthConnectAvailability.UNAVAILABLE_DEVICE
        return when (HealthConnectClient.getSdkStatus(context, providerPackage)) {
            HealthConnectClient.SDK_AVAILABLE -> HealthConnectAvailability.AVAILABLE
            HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED -> HealthConnectAvailability.UPDATE_REQUIRED
            else -> HealthConnectAvailability.UNAVAILABLE_PROVIDER
        }
    }

    override fun permissionRequestContract(): ActivityResultContract<Set<String>, Set<String>> =
        PermissionController.createRequestPermissionResultContract(providerPackage)

    override fun permissionsFor(types: Set<HealthConnectRecordType>, includeBackground: Boolean): Set<String> = buildSet {
        types.forEach { add(HealthPermission.getReadPermission(recordClass(it))) }
        if (includeBackground && backgroundReadAvailable()) add(HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND)
    }

    override suspend fun grantedPermissions(): Set<String> = withClient { it.permissionController.getGrantedPermissions() }

    override fun manageAccessIntent(): Intent = Intent(HealthConnectClient.ACTION_HEALTH_CONNECT_SETTINGS)

    override fun providerIntent(): Intent = Intent(
        Intent.ACTION_VIEW,
        Uri.parse("market://details?id=$providerPackage"),
    ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

    override fun backgroundReadAvailable(): Boolean = runCatching {
        client().features.getFeatureStatus(HealthConnectFeatures.FEATURE_READ_HEALTH_DATA_IN_BACKGROUND) ==
            HealthConnectFeatures.FEATURE_STATUS_AVAILABLE
    }.getOrDefault(false)

    override suspend fun readPage(
        type: HealthConnectRecordType,
        start: Instant,
        end: Instant,
        pageToken: String?,
    ): HealthConnectPage = withClient { client ->
        val response = client.readRecords(
            ReadRecordsRequest(
                recordType = recordClass(type),
                timeRangeFilter = TimeRangeFilter.between(start, end),
                pageSize = 500,
                pageToken = pageToken,
            ),
        )
        HealthConnectPage(response.records.mapNotNull(::mapRecord), response.pageToken)
    }

    override suspend fun aggregateDailySteps(
        startDate: String,
        endDateExclusive: String,
        zoneId: ZoneId,
    ): List<DailyStepsAggregate> = withClient { client ->
        val start = LocalDate.parse(startDate)
        val end = LocalDate.parse(endDateExclusive)
        buildList {
            var date = start
            while (date < end) {
                val from = date.atStartOfDay(zoneId).toInstant()
                val until = date.plusDays(1).atStartOfDay(zoneId).toInstant()
                val result = client.aggregate(
                    AggregateRequest(
                        metrics = setOf(StepsRecord.COUNT_TOTAL),
                        timeRangeFilter = TimeRangeFilter.between(from, until),
                    ),
                )
                add(DailyStepsAggregate(date.toString(), result[StepsRecord.COUNT_TOTAL]))
                date = date.plusDays(1)
            }
        }
    }

    override suspend fun changesToken(type: HealthConnectRecordType): String = withClient {
        it.getChangesToken(ChangesTokenRequest(recordTypes = setOf(recordClass(type))))
    }

    override suspend fun changes(token: String): HealthConnectChangesPage = withClient { client ->
        val response = client.getChanges(token)
        HealthConnectChangesPage(
            changes = response.changes.mapNotNull { change ->
                when (change) {
                    is UpsertionChange -> mapRecord(change.record)?.let(HealthConnectChange::Upsert)
                    is DeletionChange -> HealthConnectChange.Delete(change.recordId)
                    else -> null
                }
            },
            nextToken = response.nextChangesToken,
            hasMore = response.hasMore,
            tokenExpired = response.changesTokenExpired,
        )
    }

    private fun client(): HealthConnectClient {
        if (availability() != HealthConnectAvailability.AVAILABLE) {
            throw HealthConnectGatewayException("provider_unavailable", retryable = true)
        }
        return HealthConnectClient.getOrCreate(context, providerPackage)
    }

    private suspend fun <T> withClient(block: suspend (HealthConnectClient) -> T): T = try {
        block(client())
    } catch (failure: HealthConnectGatewayException) {
        throw failure
    } catch (failure: SecurityException) {
        throw HealthConnectGatewayException("permission_revoked", retryable = false, failure)
    } catch (failure: IOException) {
        throw HealthConnectGatewayException("provider_io", retryable = true, failure)
    } catch (failure: Exception) {
        throw HealthConnectGatewayException("provider_error", retryable = true, failure)
    }

    @Suppress("UNCHECKED_CAST")
    private fun recordClass(type: HealthConnectRecordType): KClass<out Record> = when (type) {
        HealthConnectRecordType.WEIGHT -> WeightRecord::class
        HealthConnectRecordType.BODY_FAT -> BodyFatRecord::class
        HealthConnectRecordType.LEAN_BODY_MASS -> LeanBodyMassRecord::class
        HealthConnectRecordType.BODY_WATER_MASS -> BodyWaterMassRecord::class
        HealthConnectRecordType.STEPS -> StepsRecord::class
        HealthConnectRecordType.NUTRITION -> NutritionRecord::class
    }

    private fun mapRecord(record: Record): HealthConnectRecord? {
        val metadata = HealthConnectMetadata(
            id = record.metadata.id,
            clientRecordId = record.metadata.clientRecordId,
            clientRecordVersion = record.metadata.clientRecordVersion,
            dataOrigin = record.metadata.dataOrigin.packageName,
            lastModifiedTime = record.metadata.lastModifiedTime,
        )
        return when (record) {
            is WeightRecord -> HealthConnectWeight(metadata, record.time, record.zoneOffset?.toString(), record.weight.inKilograms)
            is BodyFatRecord -> HealthConnectBodyFat(metadata, record.time, record.zoneOffset?.toString(), record.percentage.value)
            is LeanBodyMassRecord -> HealthConnectLeanBodyMass(metadata, record.time, record.zoneOffset?.toString(), record.mass.inKilograms)
            is BodyWaterMassRecord -> HealthConnectBodyWaterMass(metadata, record.time, record.zoneOffset?.toString(), record.mass.inKilograms)
            is NutritionRecord -> HealthConnectNutrition(
                metadata = metadata,
                startTime = record.startTime,
                endTime = record.endTime,
                zoneOffset = record.startZoneOffset?.toString(),
                endZoneOffset = record.endZoneOffset?.toString(),
                mealType = when (record.mealType) {
                    MealType.MEAL_TYPE_BREAKFAST -> "breakfast"
                    MealType.MEAL_TYPE_LUNCH -> "lunch"
                    MealType.MEAL_TYPE_DINNER -> "dinner"
                    MealType.MEAL_TYPE_SNACK -> "snack"
                    else -> null
                },
                name = record.name,
                caloriesKcal = record.energy?.inKilocalories,
                proteinGrams = record.protein?.inGrams,
                fatGrams = record.totalFat?.inGrams,
                carbohydrateGrams = record.totalCarbohydrate?.inGrams,
                fiberGrams = record.dietaryFiber?.inGrams,
                sugarGrams = record.sugar?.inGrams,
                sodiumMilligrams = record.sodium?.inMilligrams,
            )
            else -> null
        }
    }
}
