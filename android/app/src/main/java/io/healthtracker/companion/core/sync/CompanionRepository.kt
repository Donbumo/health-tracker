package io.healthtracker.companion.core.sync

import android.util.Log
import androidx.room.withTransaction
import io.healthtracker.companion.BuildConfig
import io.healthtracker.companion.core.config.PreferenceStore
import io.healthtracker.companion.core.config.ServerUrlValidator
import io.healthtracker.companion.core.database.*
import io.healthtracker.companion.core.model.*
import io.healthtracker.companion.core.network.ApiClient
import io.healthtracker.companion.core.network.CanonicalJson
import io.healthtracker.companion.core.planning.protectLocalPlanningState
import io.healthtracker.companion.core.security.SecureTokenStore
import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.temporal.ChronoUnit
import java.util.UUID
import kotlin.math.min
import kotlin.random.Random
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive

data class LoginOutcome(val accountScope: String, val profile: UserProfile)

data class HistoryFilters(
    val dateFrom: String? = null,
    val dateTo: String? = null,
    val exercisePublicId: String? = null,
) {
    val cacheKey: String
        get() = "history:${dateFrom.orEmpty()}:${dateTo.orEmpty()}:${exercisePublicId.orEmpty()}"
}

private data class HistoryParts(
    val session: HistorySessionEntity,
    val exercises: List<HistoryExerciseEntity>,
    val sets: List<HistorySetEntity>,
)

private data class PlanningParts(
    val plan: MobilePlanEntity,
    val workouts: List<MobilePlanWorkoutEntity>,
    val exercises: List<MobilePlanExerciseEntity>,
    val sets: List<MobilePlanSetEntity>,
)

private const val DRAFT_LOG_TAG = "HealthTrackerDraft"
private val HEALTH_MEAL_TYPES = setOf("breakfast", "lunch", "dinner", "snack", "extra", "other")

class CompanionRepository(
    private val database: CompanionDatabase,
    private val preferences: PreferenceStore,
    private val tokens: SecureTokenStore,
    private val api: ApiClient,
) {
    private val dao = database.companionDao()
    private val syncMutex = Mutex()
    private val planningSaveMutex = Mutex()
    private val scheduleMutationMutex = Mutex()
    private var lastSyncFailure: Throwable? = null
    private val mutableSyncStatus = MutableStateFlow(SyncStatus.IDLE)

    val syncStatus: StateFlow<SyncStatus> = mutableSyncStatus.asStateFlow()

    suspend fun testServer(rawUrl: String, explicitLocalHttp: Boolean): String {
        val validated = ServerUrlValidator.validate(rawUrl, explicitLocalHttp)
        val url = validated.normalizedUrl
            ?: throw AppFailure(AppErrorCode.VALIDATION_ERROR, validated.error ?: "URL inválida.", false)
        val health = api.health(url)
        if (health.status != "ok" || health.app != "health-tracker") {
            throw AppFailure(AppErrorCode.SERVER_INCOMPATIBLE, "El servidor no se identifica como Health Tracker.", false)
        }
        return url
    }

    suspend fun login(
        rawUrl: String,
        explicitLocalHttp: Boolean,
        email: String,
        password: String,
        deviceName: String,
        osVersion: String,
    ): LoginOutcome {
        val baseUrl = testServer(rawUrl, explicitLocalHttp)
        preferences.configureServer(baseUrl, explicitLocalHttp)
        val deviceId = preferences.ensureDeviceId()
        var createdScope: String? = null
        return authenticatedLoginWithCompensation(
            remoteLogin = {
                api.login(
                    baseUrl,
                    LoginRequest(
                        email.trim(), password,
                        DeviceRegistration(deviceId, deviceName, appVersion = BuildConfig.VERSION_NAME, osVersion = osVersion),
                    ),
                )
            },
            authenticatedWork = {
                val profile = api.me()
                val scope = CanonicalJson.accountScope(baseUrl, profile.id)
                createdScope = scope
                preferences.setAccountScope(scope)
                dao.upsertAccount(
                    AccountEntity(scope, baseUrl, profile.id, profile.email, deviceId, profile.timezone, Instant.now().toString()),
                )
                val initial = api.bootstrap()
                verifyBootstrap(initial)
                val negotiated = api.negotiate(
                    NegotiationRequest(
                        features = listOf("offline", "rest_timer", "rpe", "rir", "weight", "heart_rate_summary", "calories_summary"),
                        metrics = listOf("reps", "weight_kg", "duration_seconds", "distance_m", "rest_seconds", "rpe", "rir", "average_heart_rate_bpm", "calories_burned"),
                        limits = CompanionLimits(),
                        baseRevision = initial.companion.profile?.revision,
                    ),
                )
                verifyNegotiation(negotiated)
                database.withTransaction {
                    applyBootstrap(scope, initial)
                    dao.upsertProfile(negotiated.profile.toEntity(scope))
                }
                preferences.setOfflineSessionEligible(true)
                SyncScheduler.schedulePeriodic()
                io.healthtracker.companion.core.healthconnect.HealthConnectScheduler.schedulePeriodic()
                SyncScheduler.enqueueNow(SyncTrigger.LOGIN_BOOTSTRAP)
                LoginOutcome(scope, profile)
            },
            remoteLogout = { api.logout() },
            localCleanup = { cleanupIncompleteLogin(createdScope) },
        )
    }

    private suspend fun cleanupIncompleteLogin(scope: String?) {
        try {
            tokens.clear()
        } finally {
            try {
                preferences.setOfflineSessionEligible(false)
                preferences.setAccountScope(null)
            } finally {
                scope?.let { database.withTransaction { dao.clearAccount(it) } }
            }
        }
    }

    fun observeToday(scope: String, date: LocalDate = LocalDate.now()): Flow<PlannedWorkoutEntity?> =
        dao.observeToday(scope, date.toString())

    fun observePlanned(scope: String): Flow<List<PlannedWorkoutEntity>> = dao.observePlanned(scope)

    fun observeDailyHealth(scope: String, date: LocalDate): Flow<DailyHealthSummaryEntity?> =
        dao.observeDailyHealthSummary(scope, date.toString())

    fun observeBodyStats(scope: String): Flow<List<BodyStatEntity>> = dao.observeBodyStats(scope)

    fun observeNutritionDay(scope: String, date: LocalDate): Flow<NutritionDayEntity?> =
        dao.observeNutritionDay(scope, date.toString())

    fun observeNutritionEntries(scope: String, date: LocalDate): Flow<List<NutritionEntryEntity>> =
        dao.observeNutritionEntries(scope, date.toString())

    fun observeFoodCatalog(scope: String, query: String): Flow<List<FoodCatalogEntity>> =
        dao.observeFoodCatalog(scope, "%${query.trim().lowercase()}%")

    fun observeDailySteps(scope: String, from: LocalDate, to: LocalDate): Flow<List<DailyStepEntity>> =
        dao.observeDailySteps(scope, from.toString(), to.toString())

    fun observeHealthConflicts(scope: String): Flow<List<HealthConflictEntity>> =
        dao.observeHealthConflicts(scope)

    suspend fun resolveHealthConflictUseServer(scope: String, entityId: String) {
        val body = dao.bodyStat(scope, entityId)
        val nutrition = dao.nutritionEntry(scope, entityId)
        val steps = dao.dailyStep(scope, entityId)
        val food = dao.food(scope, entityId)
        database.withTransaction {
            dao.deletePendingForEntity(scope, entityId)
            dao.deleteHealthConflict(scope, entityId)
            body?.let {
                dao.deleteBodyStat(scope, entityId)
                recalculateLocalDayForInstantLocked(scope, it.recordedAt)
            }
            nutrition?.let {
                val day = LocalDate.parse(it.date)
                dao.deleteNutritionEntry(scope, entityId)
                recalculateNutritionDayLocked(scope, day)
                recalculateLocalDayLocked(scope, day, dao.account(scope)?.timezone ?: "UTC")
            }
            steps?.let {
                dao.deleteDailyStep(scope, entityId)
                recalculateLocalDayLocked(scope, LocalDate.parse(it.date), dao.account(scope)?.timezone ?: "UTC")
            }
            food?.let { dao.deleteFood(scope, entityId) }
        }
    }

    suspend fun retryHealthConflict(scope: String, entityId: String) {
        val pending = dao.pendingActionForEntity(scope, entityId)
            ?: throw AppFailure(AppErrorCode.VALIDATION_ERROR, "El cambio pendiente ya no está disponible.", false)
        database.withTransaction {
            dao.updatePendingEntity(
                pending.copy(
                    idempotencyKey = UUID.randomUUID().toString(), status = "pending",
                    attemptCount = 0, notBeforeEpochMs = 0, lastErrorCode = null,
                ),
            )
            dao.deleteHealthConflict(scope, entityId)
            markHealthSyncStatus(scope, pending, "pending")
        }
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    suspend fun duplicateHealthConflict(scope: String, entityId: String): String {
        val body = dao.bodyStat(scope, entityId)
        if (body != null) {
            val copyId = createBodyStatOffline(scope, body.recordedAt, body.weightKg, body.bodyFatPercent, body.notes)
            resolveHealthConflictUseServer(scope, entityId)
            return copyId
        }
        val nutrition = dao.nutritionEntry(scope, entityId)
            ?: throw AppFailure(AppErrorCode.VALIDATION_ERROR, "Este tipo de cambio no se puede duplicar.", false)
        val copyId = createNutritionEntryOffline(
            scope, LocalDate.parse(nutrition.date), nutrition.mealType, nutrition.name,
            nutrition.quantity, nutrition.unit, nutrition.caloriesKcal, nutrition.proteinG,
            nutrition.totalCarbsG ?: nutrition.netCarbsG, nutrition.fatG, nutrition.fiberG,
            nutrition.foodId, nutrition.notes,
        )
        resolveHealthConflictUseServer(scope, entityId)
        return copyId
    }

    fun observeHealthProgress(scope: String, from: LocalDate, to: LocalDate): Flow<List<HealthProgressPointEntity>> =
        dao.observeHealthProgress(scope, from.toString(), to.toString())

    suspend fun refreshHealth(scope: String, date: LocalDate, timezone: String) {
        val today = api.healthToday(date.toString(), timezone)
        val nutrition = api.nutritionDay(date.toString())
        val steps = api.steps(date.toString(), date.toString())
        val body = api.bodyStats(limit = 50)
        database.withTransaction {
            body.items.forEach { remote ->
                val local = dao.bodyStat(scope, remote.id)
                if (local == null || local.syncStatus == "synced") dao.upsertBodyStats(listOf(remote.toEntity(scope)))
            }
            val remoteEntries = nutrition.meals.flatMap { it.items }
            dao.deleteSyncedNutritionEntriesForDate(scope, nutrition.date)
            dao.upsertNutritionEntries(remoteEntries.map { it.toEntity(scope) })
            dao.upsertNutritionDay(nutrition.toEntity(scope))
            steps.items.forEach { remote ->
                val local = dao.dailyStep(scope, remote.id)
                if (local == null || local.syncStatus == "synced") dao.upsertDailySteps(listOf(remote.toEntity(scope)))
            }
            dao.upsertDailyHealthSummary(today.toEntity(scope))
            recalculateLocalDayLocked(scope, date, timezone)
        }
    }

    suspend fun refreshBodyStats(scope: String) {
        var cursor: String? = null
        var pages = 0
        do {
            val page = api.bodyStats(cursor, 100)
            database.withTransaction {
                page.items.forEach { remote ->
                    val local = dao.bodyStat(scope, remote.id)
                    if (local == null || local.syncStatus == "synced") dao.upsertBodyStats(listOf(remote.toEntity(scope)))
                }
            }
            cursor = page.nextCursor
            pages++
        } while (page.hasMore && cursor != null && pages < 10)
    }

    suspend fun refreshNutritionDay(scope: String, date: LocalDate) {
        val remote = api.nutritionDay(date.toString())
        database.withTransaction {
            dao.deleteSyncedNutritionEntriesForDate(scope, date.toString())
            dao.upsertNutritionEntries(remote.meals.flatMap { it.items }.map { it.toEntity(scope) })
            dao.upsertNutritionDay(remote.toEntity(scope))
            recalculateLocalDayLocked(scope, date, dao.account(scope)?.timezone ?: "UTC")
        }
    }

    suspend fun refreshFoods(scope: String, query: String = "", reset: Boolean = true): Boolean {
        val normalized = query.trim().lowercase()
        val cursor = if (reset) null else dao.foodCatalogState(scope, normalized)?.nextCursor
        val page = api.foods(query.trim(), cursor, 100)
        database.withTransaction {
            page.items.forEach { remote ->
                val local = dao.food(scope, remote.id)
                if (local == null || local.syncStatus == "synced") dao.upsertFoodCatalog(listOf(remote.toEntity(scope)))
            }
            dao.upsertFoodCatalogState(
                FoodCatalogStateEntity(scope, normalized, page.nextCursor, page.hasMore, Instant.now().toString()),
            )
        }
        return page.hasMore
    }

    suspend fun refreshSteps(scope: String, from: LocalDate, to: LocalDate) {
        val page = api.steps(from.toString(), to.toString(), 500)
        database.withTransaction {
            page.items.forEach { remote ->
                val local = dao.dailyStep(scope, remote.id)
                if (local == null || local.syncStatus == "synced") dao.upsertDailySteps(listOf(remote.toEntity(scope)))
            }
        }
    }

    suspend fun refreshHealthProgress(scope: String, from: LocalDate, to: LocalDate, timezone: String) {
        val response = api.healthProgress(from.toString(), to.toString(), timezone)
        dao.upsertHealthProgressPoints(response.points.map { it.toEntity(scope) })
    }

    suspend fun createBodyStatOffline(
        scope: String,
        recordedAt: String,
        weightKg: String,
        bodyFatPercent: String? = null,
        notes: String? = null,
    ): String {
        requireDecimal(weightKg, "El peso", BigDecimal("0.001"), BigDecimal("1000"))
        bodyFatPercent?.let { requireDecimal(it, "La grasa corporal", BigDecimal.ZERO, BigDecimal("100")) }
        val id = UUID.randomUUID().toString()
        val now = Instant.now().toString()
        val entity = BodyStatEntity(
            scope, id, recordedAt, weightKg, bodyFatPercent, null, null, null, null, null,
            notes?.trim()?.takeIf { it.isNotEmpty() }?.take(2000), "manual", 0, 1, "pending", now, now,
        )
        val payload = bodyPayload(entity, creating = true)
        database.withTransaction {
            dao.upsertBodyStats(listOf(entity))
            enqueue(scope, "health_body_create", id, UUID.randomUUID().toString(), payload.toString())
            recalculateLocalDayForInstantLocked(scope, recordedAt)
        }
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        return id
    }

    suspend fun updateBodyStatOffline(value: BodyStatEntity) {
        requireDecimal(value.weightKg, "El peso", BigDecimal("0.001"), BigDecimal("1000"))
        val now = Instant.now().toString()
        val updated = value.copy(
            source = if (value.source == "health_connect") "user_override" else value.source,
            localRevision = value.localRevision + 1,
            syncStatus = "pending",
            updatedAt = now,
        )
        database.withTransaction {
            if (value.source == "health_connect") dao.detachHealthConnectLedgers(value.accountScope, value.publicId, now)
            dao.upsertBodyStats(listOf(updated))
            coalesceHealthWrite(scope = value.accountScope, createType = "health_body_create", updateType = "health_body_update", entityId = value.publicId, payload = bodyPayload(updated, creating = value.revision == 0))
            recalculateLocalDayForInstantLocked(value.accountScope, value.recordedAt)
        }
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    suspend fun deleteBodyStatOffline(scope: String, publicId: String) {
        val value = dao.bodyStat(scope, publicId) ?: return
        database.withTransaction {
            if (!discardNeverSyncedCreate(scope, "health_body_create", publicId)) {
                enqueue(scope, "health_body_delete", publicId, UUID.randomUUID().toString(), buildJsonObject { put("base_revision", value.revision) }.toString())
            }
            dao.deleteBodyStat(scope, publicId)
            dao.deleteHealthConflict(scope, publicId)
            recalculateLocalDayForInstantLocked(scope, value.recordedAt)
        }
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    suspend fun createNutritionEntryOffline(
        scope: String,
        date: LocalDate,
        mealType: String,
        name: String,
        quantity: String?,
        unit: String?,
        caloriesKcal: String?,
        proteinG: String?,
        totalCarbsG: String?,
        fatG: String?,
        fiberG: String?,
        foodId: String? = null,
        notes: String? = null,
    ): String {
        if (mealType !in HEALTH_MEAL_TYPES || name.isBlank() || name.length > 200) throw AppFailure(AppErrorCode.VALIDATION_ERROR, "Revisa la comida y el nombre del alimento.", false)
        listOf(quantity, caloriesKcal, proteinG, totalCarbsG, fatG, fiberG).filterNotNull().forEach {
            requireDecimal(it, "El valor nutricional", BigDecimal.ZERO, BigDecimal("1000000"))
        }
        val id = UUID.randomUUID().toString()
        val now = Instant.now().toString()
        val complete = listOf(caloriesKcal, proteinG, totalCarbsG, fatG).all { it != null }
        val entity = NutritionEntryEntity(
            scope, id, date.toString(), mealType, null, name.trim(), quantity, unit?.trim(), foodId,
            caloriesKcal, proteinG, fatG, null, totalCarbsG, fiberG, null, null,
            notes?.trim()?.takeIf { it.isNotEmpty() }?.take(2000), complete, 0, 1, "pending", now, now,
        )
        database.withTransaction {
            dao.upsertNutritionEntries(listOf(entity))
            enqueue(scope, "health_nutrition_create", id, UUID.randomUUID().toString(), nutritionPayload(entity, true).toString())
            recalculateNutritionDayLocked(scope, date)
            recalculateLocalDayLocked(scope, date, dao.account(scope)?.timezone ?: "UTC")
        }
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        return id
    }

    suspend fun updateNutritionEntryOffline(value: NutritionEntryEntity) {
        val now = Instant.now().toString()
        val updated = value.copy(
            source = if (value.source == "health_connect") "user_override" else value.source,
            localRevision = value.localRevision + 1,
            syncStatus = "pending",
            updatedAt = now,
        )
        database.withTransaction {
            if (value.source == "health_connect") dao.detachHealthConnectLedgers(value.accountScope, value.publicId, now)
            dao.upsertNutritionEntries(listOf(updated))
            coalesceHealthWrite(value.accountScope, "health_nutrition_create", "health_nutrition_update", value.publicId, nutritionPayload(updated, updated.revision == 0))
            recalculateNutritionDayLocked(value.accountScope, LocalDate.parse(value.date))
            recalculateLocalDayLocked(value.accountScope, LocalDate.parse(value.date), dao.account(value.accountScope)?.timezone ?: "UTC")
        }
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    suspend fun duplicateNutritionEntryOffline(scope: String, publicId: String): String {
        val source = dao.nutritionEntry(scope, publicId)
            ?: throw AppFailure(AppErrorCode.VALIDATION_ERROR, "La entrada ya no está disponible.", false)
        return createNutritionEntryOffline(
            scope, LocalDate.parse(source.date), source.mealType, source.name, source.quantity, source.unit,
            source.caloriesKcal, source.proteinG, source.totalCarbsG ?: source.netCarbsG, source.fatG,
            source.fiberG, source.foodId, source.notes,
        )
    }

    suspend fun deleteNutritionEntryOffline(scope: String, publicId: String) {
        val value = dao.nutritionEntry(scope, publicId) ?: return
        val date = LocalDate.parse(value.date)
        database.withTransaction {
            if (!discardNeverSyncedCreate(scope, "health_nutrition_create", publicId)) {
                enqueue(scope, "health_nutrition_delete", publicId, UUID.randomUUID().toString(), buildJsonObject { put("base_revision", value.revision) }.toString())
            }
            dao.deleteNutritionEntry(scope, publicId)
            dao.deleteHealthConflict(scope, publicId)
            recalculateNutritionDayLocked(scope, date)
            recalculateLocalDayLocked(scope, date, dao.account(scope)?.timezone ?: "UTC")
        }
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    suspend fun createFoodOffline(scope: String, name: String, servingSizeG: String?, calories: String?, protein: String?, carbs: String?, fat: String?): String {
        if (name.isBlank() || name.length > 200) throw AppFailure(AppErrorCode.VALIDATION_ERROR, "El nombre del alimento no es válido.", false)
        listOf(servingSizeG, calories, protein, carbs, fat).filterNotNull().forEach { requireDecimal(it, "El valor del alimento", BigDecimal.ZERO, BigDecimal("1000000")) }
        val id = UUID.randomUUID().toString()
        val now = Instant.now().toString()
        val entity = FoodCatalogEntity(scope, id, name.trim(), name.trim().lowercase(), null, servingSizeG, null, calories, protein, fat, carbs, null, null, null, null, true, false, listOf(calories, protein, carbs, fat).all { it != null }, 0, "pending", now)
        val payload = buildJsonObject {
            put("public_id", id); put("name", entity.name)
            servingSizeG?.let { put("serving_size_g", it) }; calories?.let { put("calories_per_100g", it) }
            protein?.let { put("protein_g_per_100g", it) }; carbs?.let { put("carbs_g_per_100g", it) }; fat?.let { put("fat_g_per_100g", it) }
        }
        database.withTransaction {
            dao.upsertFoodCatalog(listOf(entity))
            enqueue(scope, "health_food_create", id, UUID.randomUUID().toString(), payload.toString())
        }
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        return id
    }

    suspend fun setStepsOffline(scope: String, date: LocalDate, steps: Long): String {
        if (steps !in 0..10_000_000) throw AppFailure(AppErrorCode.VALIDATION_ERROR, "Los pasos deben estar entre 0 y 10 000 000.", false)
        val existing = dao.dailyStepsForDate(scope, date.toString()).firstOrNull { it.source == "manual" }
        val now = Instant.now().toString()
        val entity = existing?.copy(steps = steps, localRevision = existing.localRevision + 1, syncStatus = "pending", updatedAt = now)
            ?: DailyStepEntity(scope, UUID.randomUUID().toString(), date.toString(), steps, "manual", null, 0, 1, "pending", now, now)
        database.withTransaction {
            dao.upsertDailySteps(listOf(entity))
            val payload = buildJsonObject {
                if (entity.revision == 0) put("public_id", entity.publicId) else put("base_revision", entity.revision)
                put("date", entity.date); put("steps", entity.steps); if (entity.revision == 0) put("source", "manual")
            }
            coalesceHealthWrite(scope, "health_steps_create", "health_steps_update", entity.publicId, payload)
            recalculateLocalDayLocked(scope, date, dao.account(scope)?.timezone ?: "UTC")
        }
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        return entity.publicId
    }

    suspend fun deleteStepsOffline(scope: String, publicId: String) {
        val value = dao.dailyStep(scope, publicId) ?: return
        database.withTransaction {
            if (!discardNeverSyncedCreate(scope, "health_steps_create", publicId)) {
                enqueue(scope, "health_steps_delete", publicId, UUID.randomUUID().toString(), buildJsonObject { put("base_revision", value.revision) }.toString())
            }
            dao.deleteDailyStep(scope, publicId)
            dao.deleteHealthConflict(scope, publicId)
            recalculateLocalDayLocked(scope, LocalDate.parse(value.date), dao.account(scope)?.timezone ?: "UTC")
        }
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    fun observePackages(scope: String): Flow<List<WorkoutPackageEntity>> = dao.observePackages(scope)

    fun observeActiveDraft(scope: String): Flow<WorkoutDraftEntity?> = dao.observeActiveDraft(scope).map { draft ->
        draft?.let { validateRecoveredDraft(it) }
    }
    fun observePendingCount(scope: String): Flow<Int> = dao.observePendingCount(scope)
    fun observeConflictCount(scope: String): Flow<Int> = dao.observeConflictCount(scope)
    fun observeHistory(scope: String, limit: Int = 30, offset: Int = 0): Flow<List<RecentSessionEntity>> =
        dao.observeRecent(scope, limit, offset)

    fun observeHistory(scope: String, filters: HistoryFilters): Flow<List<HistorySessionEntity>> =
        dao.observeHistoryPage(scope, filters.cacheKey)

    fun observeHistoryState(scope: String, filters: HistoryFilters): Flow<HistoryQueryStateEntity?> =
        dao.observeHistoryQueryState(scope, filters.cacheKey)

    fun observeHistorySession(scope: String, publicId: String): Flow<HistorySessionEntity?> =
        dao.observeHistorySession(scope, publicId)

    fun observeHistoryExercises(scope: String, publicId: String): Flow<List<HistoryExerciseEntity>> =
        dao.observeHistoryExercises(scope, publicId)

    fun observeHistorySets(scope: String, publicId: String): Flow<List<HistorySetEntity>> =
        dao.observeHistorySets(scope, publicId)

    fun observeProgressSummary(scope: String, range: String): Flow<ProgressSummaryEntity?> =
        dao.observeProgressSummary(scope, range)

    fun observeProgressExercises(scope: String, range: String): Flow<List<ProgressExerciseEntity>> =
        dao.observeProgressExercises(scope, range)

    fun observeProgressExercise(scope: String, range: String, publicId: String): Flow<ProgressExerciseEntity?> =
        dao.observeProgressExercise(scope, range, publicId)

    fun observeProgressPoints(scope: String, range: String, publicId: String): Flow<List<ProgressPointEntity>> =
        dao.observeProgressPoints(scope, range, publicId)

    fun observePersonalRecords(scope: String, range: String, publicId: String): Flow<List<PersonalRecordEntity>> =
        dao.observePersonalRecords(scope, range, publicId)

    fun observeLatestPersonalRecord(scope: String): Flow<PersonalRecordEntity?> =
        dao.observeLatestPersonalRecord(scope)

    fun observeExerciseCatalog(scope: String, query: String): Flow<List<ExerciseCatalogEntity>> =
        dao.observeCatalog(scope, "%${query.trim().lowercase()}%")

    fun observePlans(scope: String, status: String = "active"): Flow<List<MobilePlanEntity>> = dao.observePlans(scope, status)

    fun observePlan(scope: String, publicId: String): Flow<MobilePlanEntity?> =
        dao.observePlan(scope, publicId)

    fun observePlanWorkouts(scope: String, planId: String): Flow<List<MobilePlanWorkoutEntity>> =
        dao.observePlanWorkouts(scope, planId)

    fun observePlanWorkout(scope: String, publicId: String): Flow<MobilePlanWorkoutEntity?> =
        dao.observePlanWorkout(scope, publicId)

    fun observePlanExercises(scope: String, workoutId: String): Flow<List<MobilePlanExerciseEntity>> =
        dao.observePlanExercises(scope, workoutId)

    fun observePlanSets(scope: String, workoutId: String): Flow<List<MobilePlanSetEntity>> =
        dao.observePlanSets(scope, workoutId)

    fun observePlanningConflicts(scope: String): Flow<List<PlanningConflictEntity>> =
        dao.observePlanningConflicts(scope)

    suspend fun refreshExerciseCatalog(scope: String, query: String = "", reset: Boolean = true) {
        val cacheKey = query.trim().lowercase()
        val state = if (reset) null else dao.catalogState(scope, cacheKey)
        if (!reset && state?.hasMore == false) return
        val response = api.exerciseCatalog(cacheKey, state?.nextCursor)
        val now = Instant.now().toString()
        database.withTransaction {
            dao.upsertCatalog(response.items.map {
                ExerciseCatalogEntity(
                    scope, it.publicId, it.name, it.name.lowercase(), it.aliases.joinToString("|"),
                    it.selectable, it.archived, it.preferredLoadMode, it.preferredUnit, now,
                )
            })
            dao.upsertCatalogState(
                PlanningCatalogStateEntity(scope, cacheKey, response.nextCursor, response.hasMore, now),
            )
        }
    }

    suspend fun refreshPlans(scope: String, status: String = "active") {
        val response = api.plans(status)
        val hasLocalPlanningWork = dao.queuedActions(scope, 1_000).any {
            it.actionType.startsWith("planning_")
        }
        val refreshable = mutableListOf<String>()
        database.withTransaction {
            response.items.forEach { summary ->
                val local = dao.plan(scope, summary.publicId)
                val protected = protectLocalPlanningState(local?.syncStatus, hasLocalPlanningWork)
                if (!protected) {
                    dao.upsertPlans(listOf(summary.toPlanEntity(scope, "synced")))
                    refreshable += summary.publicId
                }
            }
        }
        refreshable.forEach { refreshPlan(scope, it) }
    }

    suspend fun refreshSchedule(
        scope: String,
        from: LocalDate = LocalDate.now().minusDays(180),
        to: LocalDate = LocalDate.now().plusDays(180),
    ) {
        val remote = api.plannedWorkouts(from.toString(), to.toString())
        val protectedIds = dao.queuedActions(scope, 1_000)
            .filter { it.actionType in setOf("planning_schedule", "planning_schedule_patch", "planning_cancel_schedule") }
            .mapTo(mutableSetOf(), PendingActionEntity::entityId)
        database.withTransaction {
            remote.forEach { value ->
                val local = dao.planned(scope, value.id)
                if (value.id !in protectedIds && local?.status !in setOf("locally_pending", "syncing", "conflict")) {
                    dao.upsertPlanned(listOf(value.toEntity(scope)))
                }
            }
        }
    }

    suspend fun refreshPlan(scope: String, publicId: String) {
        val remote = api.plan(publicId)
        val local = dao.plan(scope, publicId)
        if (local?.syncStatus == "pending" || local?.syncStatus == "conflict") return
        val parts = remote.toPlanParts(scope)
        database.withTransaction { dao.replacePlan(parts.plan, parts.workouts, parts.exercises, parts.sets) }
    }

    suspend fun createPlanOffline(scope: String, name: String, description: String?): String {
        val id = UUID.randomUUID().toString()
        val now = Instant.now().toString()
        val request = PlanCreateRequest(id, name.trim(), description?.trim()?.ifBlank { null })
        val key = UUID.randomUUID().toString()
        database.withTransaction {
            dao.upsertPlans(
                listOf(MobilePlanEntity(scope, id, request.name, request.description, "active", 1, null, null, "pending", now, now, null)),
            )
            enqueue(scope, "planning_plan_create", id, key, api.json.encodeToString(request))
        }
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        return id
    }

    suspend fun editPlanOffline(
        scope: String,
        publicId: String,
        name: String,
        description: String?,
        status: String? = null,
    ) = planningSaveMutex.withLock {
        val current = dao.plan(scope, publicId)
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "La rutina no está disponible localmente.", false)
        val now = Instant.now().toString()
        val pendingCreate = dao.pendingAction(scope, publicId, "planning_plan_create")
        val existingPatch = dao.pendingAction(scope, publicId, "planning_plan_patch")
        val baseRevision = existingPatch?.let(::queuedRequest)
            ?.get("base_revision")?.jsonPrimitive?.intOrNull ?: current.revision
        val payload = buildJsonObject {
            put("base_revision", baseRevision)
            put("name", name.trim())
            val normalizedDescription = description?.trim()?.ifBlank { null }
            if (normalizedDescription == null) put("description", JsonNull) else put("description", normalizedDescription)
            status?.let { put("status", it) }
        }
        database.withTransaction {
            val foldedIntoCreate = pendingCreate != null && status == null
            dao.upsertPlans(
                listOf(
                    current.copy(
                        name = name.trim(), description = description?.trim()?.ifBlank { null },
                        status = status ?: current.status,
                        revision = if (foldedIntoCreate || existingPatch != null) current.revision else current.revision + 1,
                        syncStatus = "pending", updatedAt = now,
                        archivedAt = when (status) {
                            "archived" -> now
                            "active" -> null
                            else -> current.archivedAt
                        },
                    ),
                ),
            )
            when {
                foldedIntoCreate -> {
                    val createPayload = buildJsonObject {
                        put("public_id", publicId)
                        put("name", name.trim())
                        val normalizedDescription = description?.trim()?.ifBlank { null }
                        if (normalizedDescription == null) put("description", JsonNull) else put("description", normalizedDescription)
                    }.toString()
                    dao.updatePendingEntity(pendingCreate.withUpdatedPayload(createPayload))
                }
                existingPatch != null -> dao.updatePendingEntity(existingPatch.withUpdatedPayload(payload.toString()))
                else -> enqueue(scope, "planning_plan_patch", publicId, UUID.randomUUID().toString(), payload.toString())
            }
        }
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    suspend fun createWorkoutOffline(scope: String, planId: String, name: String): String {
        val plan = dao.plan(scope, planId)
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "La rutina no está disponible localmente.", false)
        val id = UUID.randomUUID().toString()
        val now = Instant.now().toString()
        val position = dao.planWorkouts(scope, planId).size + 1
        val payload = buildJsonObject {
            put("public_id", id)
            put("base_revision", plan.revision)
            put("name", name.trim())
            put("exercises", buildJsonArray { })
        }
        database.withTransaction {
            dao.upsertPlanWorkouts(
                listOf(MobilePlanWorkoutEntity(scope, id, planId, name.trim(), null, position, null, 1, "pending", now, now)),
            )
            dao.upsertPlans(listOf(plan.copy(revision = plan.revision + 1, syncStatus = "pending", updatedAt = now)))
            enqueue(scope, "planning_workout_create", planId, UUID.randomUUID().toString(), payload.toString())
        }
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        return id
    }

    suspend fun duplicatePlanOffline(scope: String, sourcePlanId: String, name: String): String {
        val source = dao.plan(scope, sourcePlanId)
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "La rutina no está disponible localmente.", false)
        val targetId = createPlanOffline(scope, name, source.description)
        for (sourceWorkout in dao.planWorkouts(scope, sourcePlanId)) {
            val targetWorkoutId = createWorkoutOffline(scope, targetId, sourceWorkout.name)
            val sourceExercises = dao.planExercises(scope, sourceWorkout.publicId)
            val sourceSets = dao.planSets(scope, sourceWorkout.publicId)
            saveWorkoutOffline(
                scope,
                targetWorkoutId,
                sourceWorkout.name,
                sourceWorkout.notes,
                sourceExercises.map { it.copy(workoutPublicId = targetWorkoutId) },
                sourceSets.map { it.copy(workoutPublicId = targetWorkoutId) },
            )
        }
        return targetId
    }

    suspend fun duplicateWorkoutOffline(scope: String, sourceWorkoutId: String): String {
        val source = dao.planWorkout(scope, sourceWorkoutId)
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "El entrenamiento no está disponible localmente.", false)
        val targetId = createWorkoutOffline(scope, source.planPublicId, "${source.name} (copia)")
        saveWorkoutOffline(
            scope,
            targetId,
            "${source.name} (copia)",
            source.notes,
            dao.planExercises(scope, sourceWorkoutId).map { it.copy(workoutPublicId = targetId) },
            dao.planSets(scope, sourceWorkoutId).map { it.copy(workoutPublicId = targetId) },
        )
        return targetId
    }

    suspend fun reorderWorkoutsOffline(scope: String, planId: String, orderedIds: List<String>) {
        val plan = dao.plan(scope, planId)
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "La rutina no está disponible localmente.", false)
        val current = dao.planWorkouts(scope, planId).associateBy { it.publicId }
        if (orderedIds.toSet() != current.keys || orderedIds.size != current.size) {
            throw AppFailure(AppErrorCode.VALIDATION_ERROR, "El orden de entrenamientos no es válido.", false)
        }
        val now = Instant.now().toString()
        val payload = buildJsonObject {
            put("base_revision", plan.revision)
            put("workout_order", buildJsonArray { orderedIds.forEach { add(kotlinx.serialization.json.JsonPrimitive(it)) } })
        }
        database.withTransaction {
            dao.offsetPlanWorkoutPositions(scope, planId)
            dao.upsertPlanWorkouts(orderedIds.mapIndexed { index, id -> current.getValue(id).copy(position = index + 1, revision = current.getValue(id).revision + 1, syncStatus = "pending", updatedAt = now) })
            dao.upsertPlans(listOf(plan.copy(revision = plan.revision + 1, syncStatus = "pending", updatedAt = now)))
            enqueue(scope, "planning_plan_patch", planId, UUID.randomUUID().toString(), payload.toString())
        }
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    suspend fun scheduleWorkoutOffline(scope: String, workoutId: String, date: LocalDate, timezone: String): String =
        scheduleMutationMutex.withLock {
            val workout = dao.planWorkout(scope, workoutId)
                ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "El entrenamiento no está disponible localmente.", false)
            dao.pendingActionsByType(scope, "planning_schedule").firstOrNull { pending ->
                val (queuedWorkoutId, request) = queuedSchedule(pending)
                queuedWorkoutId == workoutId &&
                    request["scheduled_for_date"]?.jsonPrimitive?.content == date.toString() &&
                    request["timezone"]?.jsonPrimitive?.content == timezone
            }?.let { return@withLock it.entityId }
            val id = UUID.randomUUID().toString()
            val now = Instant.now().toString()
            val request = buildJsonObject {
                put("public_id", id)
                put("scheduled_for_date", date.toString())
                put("timezone", timezone)
            }
            database.withTransaction {
                dao.upsertPlanned(listOf(PlannedWorkoutEntity(scope, id, workout.planPublicId, "pending", date.toString(), timezone, "locally_pending", workout.name, 1, now, false, workoutId)))
                enqueue(scope, "planning_schedule", id, UUID.randomUUID().toString(), scheduleQueuePayload(workoutId, request).toString())
            }
            SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
            id
        }

    suspend fun cancelScheduleOffline(scope: String, scheduledId: String) = scheduleMutationMutex.withLock {
        val planned = dao.planned(scope, scheduledId)
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "La programación no está disponible localmente.", false)
        val pendingCreate = dao.pendingAction(scope, scheduledId, "planning_schedule")
        if (pendingCreate != null && pendingCreate.attemptCount == 0 && pendingCreate.lastErrorCode == null) {
            database.withTransaction {
                dao.deletePending(pendingCreate.localId)
                dao.deletePlanned(scope, scheduledId)
            }
            return@withLock
        }
        if (dao.pendingAction(scope, scheduledId, "planning_cancel_schedule") != null) return@withLock
        val pendingPatch = dao.pendingAction(scope, scheduledId, "planning_schedule_patch")
        val pendingPatchBase = pendingPatch?.let(::queuedRequest)
            ?.get("base_revision")?.jsonPrimitive?.intOrNull
        val canDiscardPatch = pendingPatch != null && pendingPatch.attemptCount == 0 && pendingPatch.lastErrorCode == null
        val baseRevision = when {
            pendingPatchBase == null -> planned.revision
            canDiscardPatch -> pendingPatchBase
            else -> pendingPatchBase + 1
        }
        val payload = buildJsonObject { put("base_revision", baseRevision) }
        database.withTransaction {
            if (canDiscardPatch) dao.deletePending(pendingPatch.localId)
            dao.upsertPlanned(listOf(planned.copy(status = "cancelled", updatedAt = Instant.now().toString(), deleted = false)))
            enqueue(scope, "planning_cancel_schedule", scheduledId, UUID.randomUUID().toString(), payload.toString())
        }
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    suspend fun rescheduleWorkoutOffline(scope: String, scheduledId: String, date: LocalDate, timezone: String): String =
        scheduleMutationMutex.withLock {
            val planned = dao.planned(scope, scheduledId)
                ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "La programación no está disponible localmente.", false)
            if (planned.status in setOf("completed", "cancelled")) {
                throw AppFailure(AppErrorCode.REVISION_CONFLICT, "La programación ya está finalizada.", false)
            }
            if (planned.scheduledForDate == date.toString() && planned.timezone == timezone) return@withLock scheduledId
            val now = Instant.now().toString()
            val pendingCreate = dao.pendingAction(scope, scheduledId, "planning_schedule")
            if (pendingCreate != null && pendingCreate.attemptCount == 0 && pendingCreate.lastErrorCode == null) {
                val (workoutId, oldRequest) = queuedSchedule(pendingCreate)
                val request = JsonObject(oldRequest.toMutableMap().apply {
                    this["scheduled_for_date"] = JsonPrimitive(date.toString())
                    this["timezone"] = JsonPrimitive(timezone)
                })
                val payload = scheduleQueuePayload(workoutId, request).toString()
                database.withTransaction {
                    dao.upsertPlanned(listOf(planned.copy(scheduledForDate = date.toString(), timezone = timezone, status = "locally_pending", updatedAt = now)))
                    dao.updatePendingEntity(pendingCreate.withUpdatedPayload(payload))
                }
                return@withLock scheduledId
            }
            val existingPatch = dao.pendingAction(scope, scheduledId, "planning_schedule_patch")
            val existingPatchBase = existingPatch?.let(::queuedRequest)
                ?.get("base_revision")?.jsonPrimitive?.intOrNull
            val canCoalescePatch = existingPatch != null && existingPatch.attemptCount == 0 && existingPatch.lastErrorCode == null
            val baseRevision = when {
                existingPatchBase == null -> planned.revision
                canCoalescePatch -> existingPatchBase
                else -> existingPatchBase + 1
            }
            val payload = buildJsonObject {
                put("base_revision", baseRevision)
                put("scheduled_for_date", date.toString())
                put("timezone", timezone)
            }.toString()
            database.withTransaction {
                dao.upsertPlanned(listOf(planned.copy(scheduledForDate = date.toString(), timezone = timezone, status = "locally_pending", updatedAt = now)))
                if (existingPatch == null || !canCoalescePatch) {
                    enqueue(scope, "planning_schedule_patch", scheduledId, UUID.randomUUID().toString(), payload)
                } else {
                    dao.updatePendingEntity(existingPatch.withUpdatedPayload(payload))
                }
            }
            SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
            scheduledId
        }

    suspend fun saveWorkoutOffline(
        scope: String,
        workoutId: String,
        name: String,
        notes: String?,
        exercises: List<MobilePlanExerciseEntity>,
        sets: List<MobilePlanSetEntity>,
    ) = planningSaveMutex.withLock {
        saveWorkoutOfflineLocked(scope, workoutId, name, notes, exercises, sets)
    }

    suspend fun updatePlanSetOffline(value: MobilePlanSetEntity) = planningSaveMutex.withLock {
        val workout = dao.planWorkout(value.accountScope, value.workoutPublicId)
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "El entrenamiento no está disponible localmente.", false)
        val exercises = dao.planExercises(value.accountScope, value.workoutPublicId)
        val sets = dao.planSets(value.accountScope, value.workoutPublicId)
        if (sets.none { it.publicId == value.publicId }) return@withLock
        saveWorkoutOfflineLocked(
            value.accountScope,
            value.workoutPublicId,
            workout.name,
            workout.notes,
            exercises,
            sets.map { if (it.publicId == value.publicId) value else it },
        )
    }

    private suspend fun saveWorkoutOfflineLocked(
        scope: String,
        workoutId: String,
        name: String,
        notes: String?,
        exercises: List<MobilePlanExerciseEntity>,
        sets: List<MobilePlanSetEntity>,
    ) {
        val workout = dao.planWorkout(scope, workoutId)
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "El entrenamiento no está disponible localmente.", false)
        val plan = dao.plan(scope, workout.planPublicId)
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "La rutina no está disponible localmente.", false)
        val orderedExercises = exercises.sortedBy { it.position }.mapIndexed { index, item ->
            item.copy(accountScope = scope, workoutPublicId = workoutId, position = index + 1)
        }
        val orderedSets = orderedExercises.flatMap { exercise ->
            sets.filter { it.exercisePublicId == exercise.publicId }.sortedBy { it.setNumber }.mapIndexed { index, item ->
                item.copy(accountScope = scope, workoutPublicId = workoutId, setNumber = index + 1)
            }
        }
        val normalizedName = name.trim()
        val normalizedNotes = notes?.trim()?.ifBlank { null }
        val currentExercises = dao.planExercises(scope, workoutId)
        val setOrder = compareBy<MobilePlanSetEntity>({ it.exercisePublicId }, { it.setNumber })
        if (
            workout.name == normalizedName &&
            workout.notes == normalizedNotes &&
            currentExercises == orderedExercises &&
            dao.planSets(scope, workoutId).sortedWith(setOrder) == orderedSets.sortedWith(setOrder)
        ) return
        val pendingCreate = dao.pendingActionsByType(scope, "planning_workout_create").firstOrNull { pending ->
            queuedRequest(pending)["public_id"]?.jsonPrimitive?.content == workoutId
        }
        val existingPatch = dao.pendingAction(scope, workoutId, "planning_workout_patch")
        val baseRevision = existingPatch?.let(::queuedRequest)
            ?.get("base_revision")?.jsonPrimitive?.intOrNull ?: workout.revision
        val payload = workoutPatchPayload(baseRevision, normalizedName, normalizedNotes, orderedExercises, orderedSets)
        val now = Instant.now().toString()
        database.withTransaction {
            dao.deletePlanSets(scope, workoutId)
            dao.deletePlanExercises(scope, workoutId)
            dao.upsertPlanExercises(orderedExercises)
            dao.upsertPlanSets(orderedSets)
            dao.upsertPlanWorkouts(
                listOf(workout.copy(
                    name = normalizedName,
                    notes = normalizedNotes,
                    revision = if (pendingCreate == null && existingPatch == null) workout.revision + 1 else workout.revision,
                    syncStatus = "pending",
                    updatedAt = now,
                )),
            )
            dao.upsertPlans(listOf(plan.copy(
                revision = if (pendingCreate == null && existingPatch == null) plan.revision + 1 else plan.revision,
                syncStatus = "pending",
                updatedAt = now,
            )))
            when {
                pendingCreate != null -> {
                    val createPayload = JsonObject(payload.toMutableMap().apply {
                        remove("base_revision")
                        this["base_revision"] = queuedRequest(pendingCreate).getValue("base_revision")
                        this["public_id"] = JsonPrimitive(workoutId)
                    }).toString()
                    dao.updatePendingEntity(pendingCreate.withUpdatedPayload(createPayload))
                }
                existingPatch != null -> dao.updatePendingEntity(existingPatch.withUpdatedPayload(payload.toString()))
                else -> enqueue(scope, "planning_workout_patch", workoutId, UUID.randomUUID().toString(), payload.toString())
            }
        }
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    suspend fun resolvePlanningConflictKeepRemote(scope: String, entityId: String) {
        val conflict = dao.planningConflict(scope, entityId)
        if (conflict?.entityType == "schedule" || conflict?.entityType == "package") {
            val remote = try {
                api.plannedWorkout(entityId)
            } catch (failure: AppFailure) {
                if (failure.serverCode == "not_found") null else throw failure
            }
            database.withTransaction {
                dao.deletePendingForEntity(scope, entityId)
                dao.deletePlanningConflict(scope, entityId)
                if (remote == null) dao.deletePlanned(scope, entityId)
                else dao.upsertPlanned(listOf(remote.toEntity(scope)))
            }
            return
        }
        val workout = dao.planWorkout(scope, entityId)
        val planId = workout?.planPublicId ?: entityId
        val remote = api.plan(planId)
        val parts = remote.toPlanParts(scope)
        database.withTransaction {
            dao.deletePendingForEntity(scope, entityId)
            dao.deletePlanningConflict(scope, entityId)
            dao.replacePlan(parts.plan, parts.workouts, parts.exercises, parts.sets)
        }
    }

    suspend fun retryPlanningConflict(scope: String, entityId: String) {
        val pending = dao.queuedActions(scope, 100).firstOrNull { it.entityId == entityId && it.status == "conflict" }
            ?: return
        val remoteRevision = when (pending.actionType) {
            "planning_plan_patch", "planning_workout_create" -> api.plan(pending.entityId).revision
            "planning_workout_patch" -> api.planWorkout(pending.entityId).revision
            "planning_schedule_patch", "planning_cancel_schedule" -> api.plannedWorkout(pending.entityId).revision
            else -> throw AppFailure(
                AppErrorCode.SUBMISSION_CONFLICT,
                "Esta operación no puede reintentarse sin elegir la versión remota.",
                false,
            )
        }
        val original = api.json.parseToJsonElement(pending.payloadJson) as? JsonObject
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "La operación local no puede recuperarse.", false)
        val rebasedPayload = JsonObject(original.toMutableMap().apply {
            this["base_revision"] = JsonPrimitive(remoteRevision)
        }).toString()
        val localWorkout = dao.planWorkout(scope, entityId)
        val planId = localWorkout?.planPublicId ?: entityId
        database.withTransaction {
            dao.updatePendingEntity(
                pending.copy(
                    idempotencyKey = UUID.randomUUID().toString(),
                    payloadJson = rebasedPayload,
                    payloadHash = CanonicalJson.sha256(api.json.parseToJsonElement(rebasedPayload)),
                    status = "pending",
                    attemptCount = 0,
                    notBeforeEpochMs = 0,
                    lastErrorCode = null,
                ),
            )
            dao.deletePlanningConflict(scope, entityId)
            localWorkout?.let { dao.upsertPlanWorkouts(listOf(it.copy(syncStatus = "pending"))) }
            dao.plan(scope, planId)?.let { dao.upsertPlans(listOf(it.copy(syncStatus = "pending"))) }
            dao.planned(scope, entityId)?.let { dao.upsertPlanned(listOf(it.copy(status = "locally_pending"))) }
        }
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    suspend fun duplicatePlanningConflict(scope: String, entityId: String): String {
        val conflict = dao.planningConflict(scope, entityId)
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "El conflicto ya no está disponible.", false)
        val duplicatedId = when (conflict.entityType) {
            "plan" -> {
                val source = dao.plan(scope, entityId)
                    ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "La copia local de la rutina no está disponible.", false)
                duplicatePlanOffline(scope, entityId, "${source.name} (copia local)")
            }
            "workout" -> duplicateWorkoutOffline(scope, entityId)
            else -> throw AppFailure(
                AppErrorCode.VALIDATION_ERROR,
                "Este conflicto no admite duplicación.",
                false,
            )
        }
        resolvePlanningConflictKeepRemote(scope, entityId)
        return duplicatedId
    }

    private fun workoutPatchPayload(
        baseRevision: Int,
        name: String,
        notes: String?,
        exercises: List<MobilePlanExerciseEntity>,
        sets: List<MobilePlanSetEntity>,
    ): JsonObject = buildJsonObject {
        put("base_revision", baseRevision)
        put("name", name)
        val normalizedNotes = notes?.trim()?.ifBlank { null }
        if (normalizedNotes == null) put("notes", JsonNull) else put("notes", normalizedNotes)
        put("exercises", buildJsonArray {
            exercises.sortedBy { it.position }.forEach { exercise ->
                add(buildJsonObject {
                    put("id", exercise.publicId)
                    exercise.catalogExerciseId?.let { put("exercise_id", it) }
                    put("name", exercise.name)
                    exercise.notes?.let { put("notes", it) }
                    put("sets", buildJsonArray {
                        sets.filter { it.exercisePublicId == exercise.publicId }.sortedBy { it.setNumber }.forEach { set ->
                            add(buildJsonObject {
                                put("id", set.publicId)
                                set.reps?.let { put("reps", it) }
                                set.repsMin?.let { put("reps_min", it) }
                                set.repsMax?.let { put("reps_max", it) }
                                set.weightKg?.let { put("weight_kg", it) }
                                set.loadValue?.let { put("load_value", it) }
                                put("load_unit", set.loadUnit)
                                put("load_mode", set.loadMode)
                                set.loadDetailsJson?.let {
                                    put("load_details", api.json.parseToJsonElement(it))
                                }
                                set.rir?.let { put("rir", it) }
                                set.rpe?.let { put("rpe", it) }
                                set.restSeconds?.let { put("rest_seconds", it) }
                                set.durationSeconds?.let { put("duration_seconds", it) }
                                set.distanceMeters?.let { put("distance_m", it) }
                                set.notes?.let { put("notes", it) }
                            })
                        }
                    })
                })
            }
        })
    }

    suspend fun refreshHistory(scope: String, filters: HistoryFilters = HistoryFilters(), reset: Boolean = true) {
        val state = if (reset) null else dao.historyQueryState(scope, filters.cacheKey)
        if (!reset && state?.hasMore == false) return
        val response = api.history(
            cursor = state?.nextCursor,
            dateFrom = filters.dateFrom,
            dateTo = filters.dateTo,
            exercisePublicId = filters.exercisePublicId,
        )
        if (response.schemaVersion != CONTRACT_VERSION) {
            throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "El historial usa una versión incompatible.", false)
        }
        database.withTransaction {
            if (reset) dao.deleteHistoryPages(scope, filters.cacheKey)
            val start = if (reset) 0 else dao.maxHistoryPosition(scope, filters.cacheKey) + 1
            response.items.forEachIndexed { index, item ->
                val existing = dao.historySession(scope, item.publicId)
                dao.replaceHistorySession(item.toHistory(scope, existing))
                dao.upsertHistoryPages(listOf(HistoryPageEntity(scope, filters.cacheKey, item.publicId, start + index)))
            }
            dao.upsertHistoryQueryState(
                HistoryQueryStateEntity(scope, filters.cacheKey, response.nextCursor, response.hasMore, Instant.now().toString()),
            )
        }
    }

    suspend fun refreshHistoryDetail(scope: String, publicId: String) {
        val response = api.historyDetail(publicId)
        if (response.schemaVersion != CONTRACT_VERSION || response.publicId != publicId) {
            throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "El detalle de historial no corresponde a la sesión.", false)
        }
        val existing = dao.historySession(scope, publicId)
        val parts = response.toHistoryParts(scope, existing?.clientEventId ?: publicId)
        database.withTransaction { dao.replaceHistorySession(parts.session, parts.exercises, parts.sets) }
    }

    suspend fun refreshProgress(scope: String, range: String) {
        val summary = api.progressSummary(range)
        val exercises = api.progressExercises(range)
        if (summary.schemaVersion != CONTRACT_VERSION || exercises.schemaVersion != CONTRACT_VERSION ||
            summary.range != range || exercises.range != range
        ) throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "El progreso usa un contrato incompatible.", false)
        val now = Instant.now().toString()
        database.withTransaction {
            dao.upsertProgressSummary(summary.toEntity(scope, now))
            dao.deleteProgressExercises(scope, range)
            dao.upsertProgressExercises(exercises.items.map { it.toEntity(scope, range, now) })
        }
    }

    suspend fun refreshProgressExercise(scope: String, range: String, publicId: String) {
        val detail = api.progressExercise(publicId, range)
        if (detail.schemaVersion != CONTRACT_VERSION || detail.range != range || detail.exercise.publicId != publicId) {
            throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "El detalle de progreso no corresponde al ejercicio.", false)
        }
        val now = Instant.now().toString()
        database.withTransaction {
            dao.replaceProgressExercise(
                detail.exercise.toEntity(scope, range, now),
                detail.points.map { it.toEntity(scope, range, publicId) },
                detail.personalRecords.map { it.toEntity(scope, range, publicId) },
            )
        }
    }

    suspend fun restoreLocalSession(): UserProfile? {
        val local = preferences.values.first()
        tokens.bindLegacyServerIfMissing(local.serverUrl)
        val scope = local.accountScope ?: return null
        if (!local.offlineSessionEligible || local.serverUrl == null || local.deviceId.isBlank()) return null
        if (tokens.refreshToken(local.serverUrl) == null) return null
        val account = dao.account(scope) ?: return null
        if (account.scope != scope || account.serverUrl != local.serverUrl || account.deviceId != local.deviceId) return null
        return UserProfile(
            id = account.userPublicId,
            email = account.displayEmail,
            role = "offline_cache",
            timezone = account.timezone,
            createdAt = account.createdAt,
        )
    }

    suspend fun restoreOnlineSession(scope: String): UserProfile {
        val local = preferences.values.first()
        val account = dao.account(scope)
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "Falta la identidad local de la cuenta.", false)
        if (local.accountScope != scope || account.serverUrl != local.serverUrl || account.deviceId != local.deviceId) {
            throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "La sesión local no corresponde a esta cuenta y dispositivo.", false)
        }
        api.restoreSession()
        val profile = api.me()
        val expectedScope = CanonicalJson.accountScope(account.serverUrl, profile.id)
        if (expectedScope != scope) {
            throw AppFailure(AppErrorCode.REFRESH_FAILED, "La sesión restaurada no corresponde a la cuenta local.", false)
        }
        val bootstrap = api.bootstrap()
        verifyBootstrap(bootstrap)
        val remoteProfile = bootstrap.companion.profile
        val needsNegotiation = remoteProfile == null ||
            remoteProfile.protocolVersion != CONTRACT_VERSION ||
            remoteProfile.workoutSchemaVersion != CONTRACT_VERSION ||
            remoteProfile.resultSchemaVersion != CONTRACT_VERSION
        val negotiated = if (needsNegotiation) {
            api.negotiate(
                NegotiationRequest(
                    features = listOf("offline", "rest_timer", "rpe", "rir", "weight", "heart_rate_summary", "calories_summary"),
                    metrics = listOf("reps", "weight_kg", "duration_seconds", "distance_m", "rest_seconds", "rpe", "rir", "average_heart_rate_bpm", "calories_burned"),
                    limits = CompanionLimits(),
                    baseRevision = remoteProfile?.revision,
                ),
            ).also(::verifyNegotiation)
        } else null
        database.withTransaction {
            applyBootstrap(scope, bootstrap)
            negotiated?.profile?.let { dao.upsertProfile(it.toEntity(scope)) }
            dao.upsertAccount(
                account.copy(displayEmail = profile.email, timezone = profile.timezone),
            )
        }
        preferences.setOfflineSessionEligible(true)
        return profile
    }

    suspend fun downloadWorkout(scope: String, plannedId: String): String {
        var planned = dao.planned(scope, plannedId)
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "La programación no está disponible localmente.", false)
        if (planned.status in setOf("locally_pending", "syncing")) {
            synchronize(scope)
            planned = dao.planned(scope, plannedId)
                ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "La programación aún no existe en el servidor.", true)
        }
        var stalePackageId: String? = null
        dao.packageForPlanned(scope, plannedId)?.let { existing ->
            val delivery = dao.delivery(scope, existing.deliveryId)
            if (
                delivery != null && existing.revision == planned.revision &&
                existing.expiresAt?.let { Instant.parse(it).isAfter(Instant.now()) } != false
            ) {
                return existing.deliveryId
            }
            val draft = dao.draft(scope, existing.deliveryId)
            if (draft != null && draft.status !in setOf("completion_pending", "aborted_pending", "corrupt")) {
                dao.upsertPlanningConflict(
                    PlanningConflictEntity(
                        scope,
                        plannedId,
                        "package",
                        existing.revision,
                        planned.revision,
                        "package_revision_conflict:revision",
                        "${existing.title} · ${existing.scheduledForDate}",
                        "${planned.title} · ${planned.scheduledForDate}",
                        Instant.now().toString(),
                    ),
                )
                dao.upsertPlanned(listOf(planned.copy(status = "conflict")))
                throw AppFailure(
                    AppErrorCode.REVISION_CONFLICT,
                    "Hay una versión más reciente, pero el entrenamiento activo conserva su descarga original.",
                    false,
                )
            }
            stalePackageId = existing.packageId
        }
        val key = UUID.randomUUID().toString()
        val delivery = api.createDelivery(DeliveryCreateRequest(plannedWorkoutId = plannedId), key)
        val verified = api.downloadPackage(delivery.id)
        if (!delivery.packageHash.equals(verified.calculatedHash, ignoreCase = true)) {
            throw AppFailure(AppErrorCode.PACKAGE_HASH_MISMATCH, "La entrega y su package declaran hashes distintos.", false)
        }
        val now = Instant.now().toString()
        val packageEntity = WorkoutPackageEntity(
            scope, verified.value.packageId, delivery.id, verified.value.plannedWorkoutId,
            verified.value.planId, verified.value.planVersionId, verified.value.title,
            verified.value.scheduledForDate, verified.value.timezone, verified.value.revision,
            verified.value.generatedAt, verified.value.expiresAt, verified.calculatedHash, now,
        )
        val exercises = verified.value.exercises.map {
            PackageExerciseEntity(scope, verified.value.packageId, it.exerciseOrder, it.name, it.notes)
        }
        val sets = verified.value.exercises.flatMap { exercise ->
            exercise.sets.mapIndexed { index, set ->
                PackageSetEntity(
                    scope, verified.value.packageId, exercise.exerciseOrder,
                    set["set_number"]?.jsonPrimitive?.intOrNull ?: index + 1,
                    set["reps"]?.jsonPrimitive?.intOrNull,
                    set["reps_min"]?.jsonPrimitive?.intOrNull,
                    set["reps_max"]?.jsonPrimitive?.intOrNull,
                    set["duration_seconds"]?.jsonPrimitive?.intOrNull,
                    set["distance_m"]?.jsonPrimitive?.content,
                    set["rest_seconds"]?.jsonPrimitive?.intOrNull,
                    set["target"]?.toString()?.take(500),
                    set["weight_kg"]?.jsonPrimitive?.content,
                    set["load_value"]?.jsonPrimitive?.content,
                    set["load_unit"]?.jsonPrimitive?.content,
                    set["load_mode"]?.jsonPrimitive?.content,
                    set["rir"]?.jsonPrimitive?.content,
                    set["rpe"]?.jsonPrimitive?.content,
                    set["notes"]?.jsonPrimitive?.content,
                    set["load_details"]?.toString(),
                )
            }
        }
        val operationId = UUID.randomUUID().toString()
        val ack = DeliveryOperationRequest(
            clientOperationId = operationId,
            baseRevision = delivery.revision,
            receivedAt = now,
            packageHash = delivery.packageHash,
        )
        val ackKey = UUID.randomUUID().toString()
        try {
            val acknowledged = api.transition(delivery.id, "ack", ack, ackKey).toEntity(scope)
            database.withTransaction {
                dao.upsertDelivery(listOf(acknowledged))
                stalePackageId?.let { dao.deletePackage(scope, it) }
                dao.replacePackage(packageEntity, exercises, sets)
            }
        } catch (failure: AppFailure) {
            if (!failure.retryable) throw failure
            database.withTransaction {
                dao.upsertDelivery(listOf(delivery.toEntity(scope).copy(status = "acknowledged_pending", revision = delivery.revision + 1)))
                stalePackageId?.let { dao.deletePackage(scope, it) }
                dao.replacePackage(packageEntity, exercises, sets)
                enqueue(scope, "companion_ack", delivery.id, ackKey, api.json.encodeToString(ack))
            }
        }
        SyncScheduler.enqueueNow(SyncTrigger.DOWNLOAD_ACK)
        return delivery.id
    }

    suspend fun startWorkout(scope: String, deliveryId: String): WorkoutDraftEntity {
        dao.draft(scope, deliveryId)?.let { return validateRecoveredDraft(it) }
        val (savedDraft, created) = database.withTransaction {
            dao.draft(scope, deliveryId)?.let { return@withTransaction it to false }
            val delivery = dao.delivery(scope, deliveryId)
                ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "No se encontró la entrega descargada.", false)
            val packageEntity = packageForDelivery(scope, deliveryId)
            if (!delivery.packageHash.equals(packageEntity.packageHash, ignoreCase = true)) {
                throw AppFailure(
                    AppErrorCode.PACKAGE_HASH_MISMATCH,
                    "La entrega local no corresponde al package verificado.",
                    false,
                )
            }
            val now = Instant.now()
            if (packageEntity.expiresAt?.let { Instant.parse(it).isBefore(now) } == true) {
                throw AppFailure(AppErrorCode.PACKAGE_EXPIRED, "El entrenamiento descargado ya expiró.", false)
            }
            val packageSets = dao.packageSets(scope, packageEntity.packageId)
            if (packageSets.isEmpty()) {
                throw AppFailure(AppErrorCode.DRAFT_CORRUPT, "El package descargado no contiene series recuperables.", false)
            }
            val draft = WorkoutDraftEntity(
                scope, deliveryId, packageEntity.packageId, UUID.randomUUID().toString(), UUID.randomUUID().toString(),
                CONTRACT_VERSION, packageEntity.packageHash, "active", now.toString(), null, 0,
                null, null, null, delivery.lastClientSequence,
                payloadHash = CanonicalJson.sha256(JsonObject(emptyMap())),
                updatedAt = now.toString(), expiresAt = now.plus(7, ChronoUnit.DAYS).toString(), corruptReasonCode = null,
            )
            dao.upsertDraft(draft)
            packageSets.forEach {
                dao.upsertDraftSet(
                    DraftSetEntity(
                        scope, deliveryId, it.exerciseOrder, it.setNumber, it.setNumber, it.reps ?: it.repsMin ?: 1,
                        null, null, "0", null, it.durationSeconds, it.distanceMeters, it.restSeconds,
                        null, null, false, now.toString(),
                    ),
                )
            }
            val saved = draft.copy(payloadHash = draftPayloadHash(draft, dao.draftSets(scope, deliveryId)))
            dao.upsertDraft(saved)
            val operation = DeliveryOperationRequest(
                clientOperationId = UUID.randomUUID().toString(),
                baseRevision = delivery.revision,
            )
            enqueue(scope, "companion_start", deliveryId, UUID.randomUUID().toString(), api.json.encodeToString(operation))
            dao.upsertDelivery(listOf(delivery.copy(status = "started_pending", revision = delivery.revision + 1)))
            saved to true
        }
        val committedDraft = validateRecoveredDraft(savedDraft)
        if (committedDraft.status == "corrupt") {
            throw AppFailure(AppErrorCode.DRAFT_CORRUPT, "El borrador local no superó la validación de integridad.", false)
        }
        if (created) SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        return committedDraft
    }

    suspend fun saveSet(value: DraftSetEntity) {
        validateDraftSet(value, requireCompletedMetrics = false)
        database.withTransaction {
            val stored = dao.draftSet(value.accountScope, value.deliveryId, value.exerciseOrder, value.setNumber)
            dao.upsertDraftSet(
                value.copy(
                    checkpointSequence = stored?.checkpointSequence ?: value.checkpointSequence,
                    completed = stored?.completed == true || value.completed,
                    updatedAt = Instant.now().toString(),
                ),
            )
            val draft = dao.draft(value.accountScope, value.deliveryId) ?: return@withTransaction
            val status = if (draft.status in setOf("paused", "pending_sync", "completion_pending", "aborted_pending", "corrupt")) {
                draft.status
            } else {
                "saved"
            }
            val updated = draft.copy(status = status, updatedAt = Instant.now().toString())
            dao.upsertDraft(updated.copy(payloadHash = draftPayloadHash(updated, dao.draftSets(value.accountScope, value.deliveryId))))
        }
    }

    suspend fun updateDraftSummary(
        scope: String,
        deliveryId: String,
        heartRate: Int?,
        calories: String?,
        notes: String?,
    ) {
        if (heartRate != null && heartRate !in 20..250) {
            throw AppFailure(AppErrorCode.VALIDATION_ERROR, "La frecuencia cardiaca debe estar entre 20 y 250.", false)
        }
        if (calories != null && calories.isNotBlank() && calories.toBigDecimalOrNull()?.let { it.signum() >= 0 } != true) {
            throw AppFailure(AppErrorCode.VALIDATION_ERROR, "Las calorías deben ser un número no negativo.", false)
        }
        database.withTransaction {
            val draft = dao.draft(scope, deliveryId) ?: return@withTransaction
            val updated = draft.copy(
                averageHeartRateBpm = heartRate,
                caloriesBurned = calories?.takeIf { it.isNotBlank() },
                notes = notes?.take(5000),
                updatedAt = Instant.now().toString(),
            )
            dao.upsertDraft(updated.copy(payloadHash = draftPayloadHash(updated, dao.draftSets(scope, deliveryId))))
        }
    }

    fun observeDraftSets(scope: String, deliveryId: String): Flow<List<DraftSetEntity>> =
        dao.observeDraftSets(scope, deliveryId)

    suspend fun packageExercises(scope: String, packageId: String): List<PackageExerciseEntity> =
        dao.packageExercises(scope, packageId)

    fun observeDownloadedDelivery(scope: String, plannedId: String): Flow<String?> =
        dao.observePackageForPlanned(scope, plannedId).map { it?.deliveryId }

    suspend fun duplicateSet(source: DraftSetEntity) {
        database.withTransaction {
            val next = (dao.maxSetNumber(source.accountScope, source.deliveryId, source.exerciseOrder) ?: 0) + 1
            saveSet(source.copy(setNumber = next, checkpointSequence = null, completed = false, updatedAt = Instant.now().toString()))
        }
    }

    suspend fun pauseOrResume(scope: String, deliveryId: String, pause: Boolean) {
        val desiredStatus = if (pause) "paused" else "active"
        val queued = database.withTransaction {
            val draft = dao.draft(scope, deliveryId) ?: return@withTransaction false
            if (draft.status == desiredStatus) return@withTransaction false
            val sequence = draft.checkpointSequence + 1
            val request = ProgressRequest(
                clientEventId = UUID.randomUUID().toString(),
                clientSequence = sequence,
                eventType = if (pause) "paused" else "resumed",
                occurredAt = Instant.now().toString(),
                payload = JsonObject(emptyMap()),
            )
            enqueue(scope, "companion_progress", deliveryId, UUID.randomUUID().toString(), api.json.encodeToString(request))
            dao.upsertDraft(
                draft.copy(
                    status = desiredStatus,
                    pausedAt = if (pause) Instant.now().toString() else null,
                    checkpointSequence = sequence,
                    updatedAt = Instant.now().toString(),
                ),
            )
            true
        }
        if (queued) SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    suspend fun abortWorkout(scope: String, deliveryId: String) {
        val delivery = dao.delivery(scope, deliveryId) ?: return
        val operation = DeliveryOperationRequest(
            clientOperationId = UUID.randomUUID().toString(),
            baseRevision = delivery.revision,
            reasonCode = "user_cancelled",
        )
        val queued = database.withTransaction {
            val latest = dao.draft(scope, deliveryId)
            if (latest?.status == "aborted_pending" || latest?.status == "completion_pending") return@withTransaction false
            enqueue(scope, "companion_abort", deliveryId, UUID.randomUUID().toString(), api.json.encodeToString(operation))
            latest?.let {
                dao.upsertDraft(it.copy(status = "aborted_pending", updatedAt = Instant.now().toString()))
            }
            true
        }
        if (queued) SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    suspend fun checkpointSet(scope: String, deliveryId: String, set: DraftSetEntity) {
        validateDraftSet(set, requireCompletedMetrics = true)
        val queued = database.withTransaction {
            val storedSet = dao.draftSet(scope, deliveryId, set.exerciseOrder, set.setNumber) ?: return@withTransaction false
            if (storedSet.checkpointSequence != null) return@withTransaction false
            val draft = dao.draft(scope, deliveryId) ?: return@withTransaction false
            val sequence = draft.checkpointSequence + 1
            val completedSet = set.copy(
                checkpointSequence = sequence,
                completed = true,
                updatedAt = Instant.now().toString(),
            )
            val payload = kotlinx.serialization.json.buildJsonObject {
                put("exercise_order", completedSet.exerciseOrder)
                put("set_number", completedSet.setNumber)
                put("completed_reps", completedSet.reps)
                put("weight_kg", completedSet.weightKg.toBigDecimal())
                completedSet.rir?.let { put("rir", it.toBigDecimal()) }
                completedSet.rpe?.let { put("rpe", it.toBigDecimal()) }
                completedSet.restSeconds?.let { put("rest_seconds", it) }
            }
            val request = ProgressRequest(
                clientEventId = UUID.randomUUID().toString(),
                clientSequence = sequence,
                eventType = "set_completed",
                occurredAt = Instant.now().toString(),
                payload = payload,
            )
            enqueue(scope, "companion_progress", deliveryId, UUID.randomUUID().toString(), api.json.encodeToString(request))
            dao.upsertDraftSet(completedSet)
            val updatedDraft = draft.copy(checkpointSequence = sequence, status = "pending_sync", updatedAt = Instant.now().toString())
            dao.upsertDraft(updatedDraft.copy(payloadHash = draftPayloadHash(updatedDraft, dao.draftSets(scope, deliveryId))))
            true
        }
        if (queued) SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    suspend fun completeWorkout(scope: String, deliveryId: String) {
        val draft = dao.draft(scope, deliveryId)
            ?: throw AppFailure(AppErrorCode.DRAFT_CORRUPT, "No se encontró el borrador.", false)
        val delivery = dao.delivery(scope, deliveryId)
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "No se encontró la entrega.", false)
        val packageEntity = packageForDelivery(scope, deliveryId)
        val exercises = dao.packageExercises(scope, packageEntity.packageId)
        val setValues = dao.observeDraftSets(scope, deliveryId).first().filter { it.completed }
        if (setValues.isEmpty()) throw AppFailure(AppErrorCode.VALIDATION_ERROR, "Completa al menos una serie.", false)
        if (setValues.any { set ->
                set.reps !in 1..10_000 ||
                    set.weightKg.toBigDecimalOrNull()?.let { it < BigDecimal.ZERO || it > BigDecimal("2000") } != false ||
                    set.durationSeconds?.let { it !in 1..86_400 } == true
            }
        ) throw AppFailure(AppErrorCode.VALIDATION_ERROR, "Una serie completada contiene métricas fuera del contrato.", false)
        val completedAt = Instant.now()
        val result = CompletedWorkoutDto(
            schemaVersion = CONTRACT_VERSION,
            clientEventId = draft.clientEventId,
            plannedWorkoutId = packageEntity.plannedWorkoutId,
            trainingPlanId = packageEntity.planId,
            trainingPlanVersionId = packageEntity.planVersionId,
            startedAt = draft.startedAt,
            completedAt = completedAt.toString(),
            timezone = packageEntity.timezone,
            durationSeconds = maxOf(1, (completedAt.epochSecond - Instant.parse(draft.startedAt).epochSecond).toInt()),
            averageHeartRateBpm = draft.averageHeartRateBpm,
            caloriesBurned = draft.caloriesBurned?.toBigDecimalOrNull(),
            notes = draft.notes,
            exercises = exercises.mapNotNull { exercise ->
                val sets = setValues.filter { it.exerciseOrder == exercise.exerciseOrder }
                if (sets.isEmpty()) null else CompletedExerciseDto(
                    exercise.exerciseOrder, exercise.exerciseOrder, exercise.name, exercise.notes,
                    sets.map { set ->
                        CompletedSetDto(
                            set.setNumber, set.plannedSetNumber, set.weightKg.toBigDecimal(),
                            set.loadDetailsJson?.let { api.json.decodeFromString<LoadDetailsDto>(it) },
                            set.reps, set.rir?.toBigDecimal(), set.rpe?.toBigDecimal(),
                            set.restSeconds, set.durationSeconds, set.notes,
                        )
                    },
                )
            },
        )
        val request = CompletionRequest(
            clientEventId = draft.clientEventId,
            packageHash = draft.packageHash,
            baseRevision = delivery.revision,
            result = result,
        )
        val queued = database.withTransaction {
            val latest = dao.draft(scope, deliveryId)
                ?: throw AppFailure(AppErrorCode.DRAFT_CORRUPT, "No se encontró el borrador.", false)
            if (latest.status == "completion_pending") return@withTransaction false
            if (latest.status == "aborted_pending") {
                throw AppFailure(AppErrorCode.REVISION_CONFLICT, "La sesión ya está pendiente de cancelación.", false)
            }
            enqueue(scope, "companion_complete", deliveryId, UUID.randomUUID().toString(), api.json.encodeToString(request))
            dao.upsertDraft(latest.copy(status = "completion_pending", updatedAt = completedAt.toString()))
            val localHistory = result.toHistoryParts(
                scope = scope,
                title = packageEntity.title,
                source = "companion",
                syncStatus = "pending",
                publicId = draft.clientEventId,
            )
            dao.replaceHistorySession(localHistory.session, localHistory.exercises, localHistory.sets)
            dao.upsertHistoryPages(listOf(HistoryPageEntity(scope, HistoryFilters().cacheKey, draft.clientEventId, -1)))
            dao.planned(scope, packageEntity.plannedWorkoutId)?.let { planned ->
                dao.upsertPlanned(listOf(planned.copy(status = "completed", updatedAt = completedAt.toString())))
            }
            refreshLocalProgressSummaries(scope, completedAt)
            true
        }
        if (queued) SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    suspend fun synchronize(scope: String) {
        if (!syncMutex.tryLock()) {
            // Join the active run. Its Room transaction/cursor result is the shared
            // outcome; this trigger must not start a second pull immediately after it.
            syncMutex.withLock { }
            lastSyncFailure?.let { throw it }
            return
        }
        mutableSyncStatus.value = SyncStatus.SYNCING
        lastSyncFailure = null
        try {
            synchronizeLocked(scope)
            mutableSyncStatus.value = when {
                dao.conflictCount(scope) > 0 -> SyncStatus.CONFLICT
                dao.pendingCount(scope) > 0 -> SyncStatus.PENDING
                else -> SyncStatus.IDLE
            }
        } catch (failure: AppFailure) {
            lastSyncFailure = failure
            mutableSyncStatus.value = when {
                dao.conflictCount(scope) > 0 -> SyncStatus.CONFLICT
                failure.retryable || dao.pendingCount(scope) > 0 -> SyncStatus.PENDING
                else -> SyncStatus.ERROR
            }
            throw failure
        } catch (error: Exception) {
            lastSyncFailure = error
            mutableSyncStatus.value = SyncStatus.ERROR
            throw error
        } finally {
            syncMutex.unlock()
        }
    }

    suspend fun hasReadyPending(scope: String): Boolean =
        dao.queuedActions(scope, 1).firstOrNull()?.let {
            it.status == "pending" && it.notBeforeEpochMs <= System.currentTimeMillis()
        } == true

    private suspend fun synchronizeLocked(scope: String) {
        reconcileConflictedStarts(scope)
        processPending(scope)
        var state = dao.syncState(scope)
        if (state == null) {
            val bootstrap = api.bootstrap()
            verifyBootstrap(bootstrap)
            database.withTransaction { applyBootstrap(scope, bootstrap) }
            state = dao.syncState(scope)
        }
        var cursor = state?.cursor ?: return
        var pages = 0
        do {
            val response = api.pull(cursor, 100)
            database.withTransaction {
                response.changes.forEach { applyChange(scope, it) }
                val account = preferences.values.first()
                dao.upsertSyncState(
                    SyncStateEntity(scope, account.deviceId, response.nextCursor, Instant.now().toString(), response.serverTime, null),
                )
            }
            cursor = response.nextCursor
            pages++
        } while (response.hasMore && pages < 20)
        val remoteStatus = api.syncStatus()
        val account = preferences.values.first()
        if (remoteStatus.schemaVersion != CONTRACT_VERSION || remoteStatus.deviceId != account.deviceId) {
            throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "El estado de sync no corresponde a este dispositivo.", false)
        }
        if (dao.historyQueryState(scope, HistoryFilters().cacheKey) != null) runCatching {
            refreshHistory(scope)
            refreshProgress(scope, "7")
            refreshProgress(scope, "30")
        }
        runCatching { refreshPlans(scope) }
        runCatching { refreshSchedule(scope) }
        dao.account(scope)?.let { account ->
            val zone = runCatching { ZoneId.of(account.timezone) }.getOrDefault(ZoneOffset.UTC)
            val today = LocalDate.now(zone)
            runCatching { refreshHealth(scope, today, zone.id) }
            runCatching { refreshHealthProgress(scope, today.minusDays(29), today, zone.id) }
        }
        preferences.setLastSyncAt(Instant.now().toString())
    }

    suspend fun logout(scope: String, revokeDevice: Boolean) {
        if (revokeDevice) {
            val deviceId = preferences.values.first().deviceId
            api.revokeDevice(deviceId)
        } else runCatching { api.logout() }
        SyncScheduler.cancelAll()
        database.withTransaction { dao.clearAccount(scope) }
        tokens.clear()
        preferences.setOfflineSessionEligible(false)
        preferences.setAccountScope(null)
    }

    suspend fun logoutAll(scope: String) {
        api.logoutAll()
        SyncScheduler.cancelAll()
        database.withTransaction { dao.clearAccount(scope) }
        tokens.clear()
        preferences.setOfflineSessionEligible(false)
        preferences.setAccountScope(null)
    }

    suspend fun clearLocal(scope: String) {
        SyncScheduler.cancelAll()
        database.withTransaction { dao.clearAccount(scope) }
        tokens.clear()
        preferences.setOfflineSessionEligible(false)
        preferences.setAccountScope(null)
    }

    suspend fun clearConfirmedInvalidSession(scope: String) {
        if (preferences.values.first().accountScope == scope) clearLocal(scope)
    }

    suspend fun detachForServerSwitch(scope: String) {
        SyncScheduler.cancelAll()
        tokens.clear()
        preferences.setOfflineSessionEligible(false)
        preferences.setAccountScope(null)
        // Room rows are intentionally retained under their existing accountScope.
        // A later login derives a different scope from server identity + user UUID.
    }

    suspend fun discardCorruptDraft(scope: String, deliveryId: String) {
        val draft = dao.draft(scope, deliveryId) ?: return
        if (draft.status != "corrupt") {
            throw AppFailure(AppErrorCode.VALIDATION_ERROR, "Solo puede descartarse un borrador marcado como corrupto.", false)
        }
        database.withTransaction {
            dao.deletePendingForEntity(scope, deliveryId)
            dao.deleteDraft(scope, deliveryId)
        }
    }

    private suspend fun processPending(scope: String) {
        repeat(100) {
            val pending = dao.queuedActions(scope, 1).firstOrNull() ?: return
            // The local queue is strict FIFO. A conflicted or backed-off predecessor
            // blocks later START/PROGRESS/COMPLETE operations instead of letting the
            // SQL readiness filter skip over a required transition.
            if (pending.status == "conflict" || pending.notBeforeEpochMs > System.currentTimeMillis()) return
            if (pending.actionType.startsWith("planning_")) {
                markPlanningSyncStatus(scope, pending, "syncing")
            }
            if (pending.actionType.startsWith("health_")) {
                markHealthSyncStatus(scope, pending, "syncing")
            }
            try {
                when (pending.actionType) {
                    "companion_ack" -> applyTransitionAndConfirm(scope, pending, "ack")
                    "companion_start" -> applyTransitionAndConfirm(scope, pending, "start")
                    "companion_abort" -> {
                        val delivery = transitionEntity(scope, pending, "abort")
                        database.withTransaction {
                            dao.upsertDelivery(listOf(delivery))
                            dao.deleteDraft(scope, pending.entityId)
                            dao.deletePending(pending.localId)
                        }
                    }
                    "companion_progress" -> {
                        api.progress(pending.entityId, api.json.decodeFromString(pending.payloadJson), pending.idempotencyKey)
                        dao.deletePending(pending.localId)
                    }
                    "companion_complete" -> {
                        val response = api.complete(
                            pending.entityId, api.json.decodeFromString(pending.payloadJson), pending.idempotencyKey,
                        )
                        database.withTransaction {
                            dao.upsertDelivery(listOf(response.delivery.toEntity(scope)))
                            dao.upsertRecent(listOf(response.completedWorkout.toRecent(scope, "Companion")))
                            val history = response.completedWorkout.toHistoryParts(
                                scope, "Entrenamiento", "companion", "synced",
                                response.completedWorkout.id,
                            )
                            dao.replaceHistorySession(history.session, history.exercises, history.sets)
                            dao.upsertHistoryPages(listOf(HistoryPageEntity(scope, HistoryFilters().cacheKey, history.session.publicId, -1)))
                            dao.deleteDraft(scope, pending.entityId)
                            dao.deletePending(pending.localId)
                        }
                    }
                    "planning_plan_create" -> {
                        api.createPlan(api.json.decodeFromString(pending.payloadJson), pending.idempotencyKey)
                        dao.deletePending(pending.localId)
                    }
                    "planning_plan_patch" -> {
                        api.patchPlan(pending.entityId, api.json.parseToJsonElement(pending.payloadJson) as JsonObject, pending.idempotencyKey)
                        dao.deletePending(pending.localId)
                    }
                    "planning_workout_create" -> {
                        api.createPlanWorkout(pending.entityId, api.json.parseToJsonElement(pending.payloadJson) as JsonObject, pending.idempotencyKey)
                        dao.deletePending(pending.localId)
                    }
                    "planning_workout_patch" -> {
                        api.patchPlanWorkout(pending.entityId, api.json.parseToJsonElement(pending.payloadJson) as JsonObject, pending.idempotencyKey)
                        dao.deletePending(pending.localId)
                    }
                    "planning_schedule" -> {
                        val (workoutId, request) = queuedSchedule(pending)
                        val response = api.schedulePlanWorkout(workoutId, request, pending.idempotencyKey)
                        database.withTransaction {
                            dao.planned(scope, pending.entityId)?.let { local ->
                                dao.upsertPlanned(listOf(local.copy(
                                    scheduledForDate = response.scheduledForDate,
                                    timezone = response.timezone,
                                    status = response.status,
                                    revision = response.revision,
                                    updatedAt = Instant.now().toString(),
                                )))
                            }
                            dao.deletePending(pending.localId)
                        }
                    }
                    "planning_schedule_patch" -> {
                        val response = api.reschedulePlannedWorkout(
                            pending.entityId,
                            queuedRequest(pending),
                            pending.idempotencyKey,
                        )
                        database.withTransaction {
                            dao.planned(scope, pending.entityId)?.let { local ->
                                dao.upsertPlanned(listOf(local.copy(
                                    scheduledForDate = response.scheduledForDate,
                                    timezone = response.timezone,
                                    status = response.status,
                                    revision = response.revision,
                                    updatedAt = response.updatedAt,
                                )))
                            }
                            dao.deletePending(pending.localId)
                        }
                    }
                    "planning_cancel_schedule" -> {
                        api.cancelScheduledWorkout(pending.entityId, api.json.parseToJsonElement(pending.payloadJson) as JsonObject, pending.idempotencyKey)
                        database.withTransaction {
                            dao.deletePlanned(scope, pending.entityId)
                            dao.deletePending(pending.localId)
                        }
                    }
                    "health_body_create" -> {
                        val response = api.createBodyStat(queuedRequest(pending), pending.idempotencyKey)
                        database.withTransaction {
                            val hasFollowUp = rebasePendingHealthUpdateLocked(
                                scope, pending.entityId, "health_body_update", response.revision,
                            )
                            val local = dao.bodyStat(scope, pending.entityId)
                            if (hasFollowUp && local != null) {
                                dao.upsertBodyStats(listOf(local.copy(revision = response.revision, syncStatus = "pending")))
                            } else {
                                if (response.id != pending.entityId) dao.deleteBodyStat(scope, pending.entityId)
                                dao.upsertBodyStats(listOf(response.toEntity(scope)))
                            }
                            dao.deleteHealthConflict(scope, pending.entityId)
                            dao.deletePending(pending.localId)
                            recalculateLocalDayForInstantLocked(scope, local?.recordedAt ?: response.recordedAt)
                        }
                    }
                    "health_body_update" -> {
                        val response = api.patchBodyStat(pending.entityId, queuedRequest(pending), pending.idempotencyKey)
                        database.withTransaction {
                            dao.upsertBodyStats(listOf(response.toEntity(scope)))
                            dao.deleteHealthConflict(scope, pending.entityId)
                            dao.deletePending(pending.localId)
                            recalculateLocalDayForInstantLocked(scope, response.recordedAt)
                        }
                    }
                    "health_body_delete" -> {
                        api.deleteBodyStat(pending.entityId, queuedRequest(pending), pending.idempotencyKey)
                        database.withTransaction { dao.deleteHealthConflict(scope, pending.entityId); dao.deletePending(pending.localId) }
                    }
                    "health_nutrition_create" -> {
                        val response = api.createNutritionEntry(queuedRequest(pending), pending.idempotencyKey)
                        database.withTransaction {
                            val hasFollowUp = rebasePendingHealthUpdateLocked(
                                scope, pending.entityId, "health_nutrition_update", response.revision,
                            )
                            val local = dao.nutritionEntry(scope, pending.entityId)
                            if (hasFollowUp && local != null) {
                                dao.upsertNutritionEntries(listOf(local.copy(revision = response.revision, syncStatus = "pending")))
                            } else {
                                if (response.id != pending.entityId) dao.deleteNutritionEntry(scope, pending.entityId)
                                dao.upsertNutritionEntries(listOf(response.toEntity(scope)))
                            }
                            dao.deleteHealthConflict(scope, pending.entityId)
                            dao.deletePending(pending.localId)
                            val day = LocalDate.parse(local?.date ?: response.date)
                            recalculateNutritionDayLocked(scope, day)
                            recalculateLocalDayLocked(scope, day, dao.account(scope)?.timezone ?: "UTC")
                        }
                    }
                    "health_nutrition_update" -> {
                        val response = api.patchNutritionEntry(pending.entityId, queuedRequest(pending), pending.idempotencyKey)
                        database.withTransaction {
                            dao.upsertNutritionEntries(listOf(response.toEntity(scope)))
                            dao.deleteHealthConflict(scope, pending.entityId)
                            dao.deletePending(pending.localId)
                            val day = LocalDate.parse(response.date)
                            recalculateNutritionDayLocked(scope, day)
                            recalculateLocalDayLocked(scope, day, dao.account(scope)?.timezone ?: "UTC")
                        }
                    }
                    "health_nutrition_delete" -> {
                        api.deleteNutritionEntry(pending.entityId, queuedRequest(pending), pending.idempotencyKey)
                        database.withTransaction { dao.deleteHealthConflict(scope, pending.entityId); dao.deletePending(pending.localId) }
                    }
                    "health_food_create" -> {
                        val response = api.createFood(queuedRequest(pending), pending.idempotencyKey)
                        database.withTransaction {
                            if (response.id != pending.entityId) dao.deleteFood(scope, pending.entityId)
                            dao.upsertFoodCatalog(listOf(response.toEntity(scope)))
                            dao.deleteHealthConflict(scope, pending.entityId)
                            dao.deletePending(pending.localId)
                        }
                    }
                    "health_steps_create" -> {
                        val response = api.createSteps(queuedRequest(pending), pending.idempotencyKey)
                        database.withTransaction {
                            val hasFollowUp = rebasePendingHealthUpdateLocked(
                                scope, pending.entityId, "health_steps_update", response.revision,
                            )
                            val local = dao.dailyStep(scope, pending.entityId)
                            if (hasFollowUp && local != null) {
                                dao.upsertDailySteps(listOf(local.copy(revision = response.revision, syncStatus = "pending")))
                            } else {
                                if (response.id != pending.entityId) dao.deleteDailyStep(scope, pending.entityId)
                                dao.upsertDailySteps(listOf(response.toEntity(scope)))
                            }
                            dao.deleteHealthConflict(scope, pending.entityId)
                            dao.deletePending(pending.localId)
                            recalculateLocalDayLocked(scope, LocalDate.parse(local?.date ?: response.date), dao.account(scope)?.timezone ?: "UTC")
                        }
                    }
                    "health_steps_update" -> {
                        val response = api.patchSteps(pending.entityId, queuedRequest(pending), pending.idempotencyKey)
                        database.withTransaction {
                            dao.upsertDailySteps(listOf(response.toEntity(scope)))
                            dao.deleteHealthConflict(scope, pending.entityId)
                            dao.deletePending(pending.localId)
                            recalculateLocalDayLocked(scope, LocalDate.parse(response.date), dao.account(scope)?.timezone ?: "UTC")
                        }
                    }
                    "health_steps_delete" -> {
                        api.deleteSteps(pending.entityId, queuedRequest(pending), pending.idempotencyKey)
                        database.withTransaction { dao.deleteHealthConflict(scope, pending.entityId); dao.deletePending(pending.localId) }
                    }
                }
                if (pending.actionType.startsWith("planning_")) {
                    markPlanningSyncStatus(scope, pending, "synced")
                }
                if (pending.actionType.startsWith("health_") && dao.pendingActionForEntity(scope, pending.entityId) == null) {
                    markHealthSyncStatus(scope, pending, "synced")
                }
            } catch (failure: AppFailure) {
                if (
                    pending.actionType == "companion_start" &&
                    failure.code == AppErrorCode.REVISION_CONFLICT &&
                    reconcileStartedPending(scope, pending)
                ) return@repeat
                if (!failure.retryable) {
                    if (pending.actionType.startsWith("planning_")) {
                        markPlanningConflict(scope, pending, failure)
                        markPlanningSyncStatus(scope, pending, "conflict")
                    }
                    if (pending.actionType.startsWith("health_")) {
                        markHealthConflict(scope, pending, failure)
                        markHealthSyncStatus(scope, pending, "conflict")
                    }
                    dao.updatePending(pending.localId, "conflict", failure.code.name.lowercase(), Long.MAX_VALUE)
                    throw failure
                }
                val delay = failure.retryAfterSeconds?.times(1000) ?: backoffMillis(pending.attemptCount + 1)
                dao.updatePending(
                    pending.localId, "pending", failure.code.name.lowercase(), System.currentTimeMillis() + delay,
                )
                if (pending.actionType.startsWith("planning_")) {
                    markPlanningSyncStatus(scope, pending, "pending")
                }
                if (pending.actionType.startsWith("health_")) {
                    markHealthSyncStatus(scope, pending, "pending")
                }
                throw failure
            }
        }
    }

    private suspend fun markPlanningSyncStatus(scope: String, pending: PendingActionEntity, status: String) {
        when (pending.actionType) {
            "planning_plan_create", "planning_plan_patch" -> {
                dao.plan(scope, pending.entityId)?.let { dao.upsertPlans(listOf(it.copy(syncStatus = status))) }
            }
            "planning_workout_create" -> {
                dao.plan(scope, pending.entityId)?.let { dao.upsertPlans(listOf(it.copy(syncStatus = status))) }
                val workoutId = runCatching {
                    (api.json.parseToJsonElement(pending.payloadJson) as JsonObject)["public_id"]?.jsonPrimitive?.content
                }.getOrNull()
                workoutId?.let { dao.planWorkout(scope, it) }?.let {
                    dao.upsertPlanWorkouts(listOf(it.copy(syncStatus = status)))
                }
            }
            "planning_workout_patch" -> {
                val workout = dao.planWorkout(scope, pending.entityId)
                workout?.let { dao.upsertPlanWorkouts(listOf(it.copy(syncStatus = status))) }
                workout?.let { dao.plan(scope, it.planPublicId) }?.let {
                    dao.upsertPlans(listOf(it.copy(syncStatus = status)))
                }
            }
            "planning_schedule", "planning_schedule_patch", "planning_cancel_schedule" -> {
                dao.planned(scope, pending.entityId)?.let { local ->
                    val visibleStatus = when (status) {
                        "syncing" -> "syncing"
                        "conflict" -> "conflict"
                        "synced" -> if (pending.actionType == "planning_cancel_schedule") "cancelled" else "planned"
                        else -> if (pending.actionType == "planning_cancel_schedule") "cancelled" else "locally_pending"
                    }
                    dao.upsertPlanned(listOf(local.copy(status = visibleStatus)))
                }
            }
        }
    }

    private suspend fun markHealthSyncStatus(scope: String, pending: PendingActionEntity, status: String) {
        when {
            pending.actionType.startsWith("health_body_") -> dao.bodyStat(scope, pending.entityId)?.let {
                dao.upsertBodyStats(listOf(it.copy(syncStatus = status)))
            }
            pending.actionType.startsWith("health_nutrition_") -> dao.nutritionEntry(scope, pending.entityId)?.let {
                dao.upsertNutritionEntries(listOf(it.copy(syncStatus = status)))
            }
            pending.actionType.startsWith("health_food_") -> dao.food(scope, pending.entityId)?.let {
                dao.upsertFoodCatalog(listOf(it.copy(syncStatus = status)))
            }
            pending.actionType.startsWith("health_steps_") -> dao.dailyStep(scope, pending.entityId)?.let {
                dao.upsertDailySteps(listOf(it.copy(syncStatus = status)))
            }
        }
    }

    private suspend fun markHealthConflict(scope: String, pending: PendingActionEntity, failure: AppFailure) {
        val type = when {
            pending.actionType.startsWith("health_body_") -> "body_stat"
            pending.actionType.startsWith("health_nutrition_") -> "nutrition_entry"
            pending.actionType.startsWith("health_food_") -> "food"
            else -> "steps"
        }
        val localRevision = when (type) {
            "body_stat" -> dao.bodyStat(scope, pending.entityId)?.localRevision
            "nutrition_entry" -> dao.nutritionEntry(scope, pending.entityId)?.localRevision
            "steps" -> dao.dailyStep(scope, pending.entityId)?.localRevision
            else -> dao.food(scope, pending.entityId)?.revision?.toLong()
        } ?: 0
        val conflictType = when (failure.serverCode) {
            "not_found" -> "deleted_or_unavailable"
            "invalid_request", "invalid_date", "invalid_datetime", "duplicate" -> "validation_rejected"
            "session_revoked", "device_revoked" -> "access_revoked"
            else -> "revision_conflict"
        }
        dao.upsertHealthConflict(
            HealthConflictEntity(scope, pending.entityId, type, conflictType, localRevision, null, Instant.now().toString()),
        )
    }

    private suspend fun markPlanningConflict(scope: String, pending: PendingActionEntity, failure: AppFailure) {
        val localPlan = dao.plan(scope, pending.entityId)
        val localWorkout = dao.planWorkout(scope, pending.entityId)
        val localSchedule = dao.planned(scope, pending.entityId)
        val remotePlanning = runCatching {
            when {
                localPlan != null -> api.plan(pending.entityId).let { it.name to it.revision }
                localWorkout != null -> api.planWorkout(pending.entityId).let { it.name to it.revision }
                else -> null
            }
        }.getOrNull()
        val remoteSchedule = if (localSchedule != null) runCatching {
            api.plannedWorkout(pending.entityId)
        }.getOrNull() else null
        val conflictType = when {
            failure.serverCode == "resource_archived" -> "archived_remote"
            failure.serverCode == "not_found" -> "deleted_or_unavailable"
            failure.serverCode == "active_schedules" -> "schedule_date_conflict"
            pending.actionType == "planning_schedule_patch" -> "schedule_date_conflict"
            else -> "revision_conflict"
        }
        dao.upsertPlanningConflict(
            PlanningConflictEntity(
                scope,
                pending.entityId,
                when {
                    localSchedule != null -> "schedule"
                    localWorkout != null -> "workout"
                    else -> "plan"
                },
                localSchedule?.revision ?: localWorkout?.revision ?: localPlan?.revision ?: 1,
                remoteSchedule?.revision ?: remotePlanning?.second,
                if (localSchedule != null) "$conflictType:scheduled_for_date" else conflictType,
                localSchedule?.let { "${it.title} · ${it.scheduledForDate}" } ?: localWorkout?.name ?: localPlan?.name,
                remoteSchedule?.let { "${it.title} · ${it.scheduledForDate}" } ?: remotePlanning?.first,
                Instant.now().toString(),
            ),
        )
    }

    private suspend fun applyTransitionAndConfirm(scope: String, pending: PendingActionEntity, action: String) {
        val delivery = transitionEntity(scope, pending, action)
        database.withTransaction {
            dao.upsertDelivery(listOf(delivery))
            dao.deletePending(pending.localId)
        }
    }

    private suspend fun transitionEntity(scope: String, pending: PendingActionEntity, action: String): DeliveryEntity {
        val operation = api.json.decodeFromString<DeliveryOperationRequest>(pending.payloadJson)
        val response = api.transition(pending.entityId, action, operation, pending.idempotencyKey)
        return response.toEntity(scope)
    }

    private suspend fun reconcileConflictedStarts(scope: String) {
        val pending = dao.conflictedStarts(scope)
        if (pending.isEmpty()) return
        val remoteById = api.deliveries().associateBy(DeliveryDto::id)
        pending.forEach { reconcileStartedPending(scope, it, remoteById[it.entityId]) }
    }

    private suspend fun reconcileStartedPending(
        scope: String,
        pending: PendingActionEntity,
        knownRemote: DeliveryDto? = null,
    ): Boolean {
        val remote = knownRemote ?: api.deliveries().firstOrNull { it.id == pending.entityId } ?: return false
        val delivery = dao.delivery(scope, pending.entityId) ?: return false
        val storedPackage = dao.packageForDelivery(scope, pending.entityId) ?: return false
        val draft = dao.draft(scope, pending.entityId) ?: return false
        val currentDeviceId = preferences.values.first().deviceId
        val compatible = remote.status == "started" &&
            remote.id == delivery.id &&
            remote.deviceId == currentDeviceId &&
            remote.profileId == delivery.profileId &&
            remote.plannedWorkoutId == delivery.plannedWorkoutId &&
            remote.packageHash.equals(delivery.packageHash, ignoreCase = true) &&
            remote.packageHash.equals(storedPackage.packageHash, ignoreCase = true) &&
            storedPackage.packageId == draft.packageId &&
            storedPackage.packageHash.equals(draft.packageHash, ignoreCase = true)
        if (!compatible) return false
        database.withTransaction {
            dao.upsertDelivery(listOf(remote.toEntity(scope)))
            dao.deletePending(pending.localId)
        }
        validateRecoveredDraft(draft)
        return true
    }

    private suspend fun enqueue(scope: String, type: String, entityId: String, key: String, payload: String) {
        val hash = CanonicalJson.sha256(api.json.parseToJsonElement(payload))
        val existing = dao.pendingByKey(scope, key)
        if (existing != null) {
            if (existing.payloadHash != hash || existing.actionType != type || existing.entityId != entityId) {
                throw AppFailure(AppErrorCode.SUBMISSION_CONFLICT, "La clave idempotente ya pertenece a otra operación local.", false)
            }
            return
        }
        try {
            dao.insertPending(
                PendingActionEntity(
                    accountScope = scope, actionType = type, entityId = entityId,
                    idempotencyKey = key, payloadJson = payload, payloadHash = hash,
                    createdAt = Instant.now().toString(),
                ),
            )
        } catch (error: Exception) {
            val concurrent = dao.pendingByKey(scope, key)
            if (concurrent != null && concurrent.payloadHash == hash && concurrent.actionType == type && concurrent.entityId == entityId) return
            throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "No fue posible conservar la operación pendiente.", true)
        }
    }

    private fun scheduleQueuePayload(workoutId: String, request: JsonObject): JsonObject = buildJsonObject {
        put("workout_id", workoutId)
        put("request", request)
    }

    private fun queuedRequest(pending: PendingActionEntity): JsonObject {
        val root = api.json.parseToJsonElement(pending.payloadJson) as? JsonObject
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "La operación pendiente no puede recuperarse.", false)
        return root["request"] as? JsonObject ?: root
    }

    private fun queuedSchedule(pending: PendingActionEntity): Pair<String, JsonObject> {
        val root = api.json.parseToJsonElement(pending.payloadJson) as? JsonObject
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "La programación pendiente no puede recuperarse.", false)
        val request = root["request"] as? JsonObject ?: root
        val workoutId = root["workout_id"]?.jsonPrimitive?.content ?: pending.entityId
        return workoutId to request
    }

    private suspend fun rebasePendingHealthUpdateLocked(
        scope: String,
        entityId: String,
        actionType: String,
        serverRevision: Int,
    ): Boolean {
        val pending = dao.pendingAction(scope, entityId, actionType) ?: return false
        val current = api.json.parseToJsonElement(pending.payloadJson) as JsonObject
        val rebased = buildJsonObject {
            current.forEach { (key, value) ->
                if (key !in setOf("public_id", "base_revision")) put(key, value)
            }
            put("base_revision", serverRevision)
        }
        dao.updatePendingEntity(pending.withUpdatedPayload(rebased.toString()))
        return true
    }

    private fun PendingActionEntity.withUpdatedPayload(payload: String): PendingActionEntity = copy(
        idempotencyKey = if (attemptCount > 0 || lastErrorCode != null) UUID.randomUUID().toString() else idempotencyKey,
        payloadJson = payload,
        payloadHash = CanonicalJson.sha256(api.json.parseToJsonElement(payload)),
        status = "pending",
        attemptCount = 0,
        notBeforeEpochMs = 0,
        lastErrorCode = null,
    )

    private fun requireDecimal(value: String, label: String, minimum: BigDecimal, maximum: BigDecimal): BigDecimal {
        val parsed = value.toBigDecimalOrNull()
            ?: throw AppFailure(AppErrorCode.VALIDATION_ERROR, "$label no es válido.", false)
        if (parsed < minimum || parsed > maximum) {
            throw AppFailure(AppErrorCode.VALIDATION_ERROR, "$label está fuera de rango.", false)
        }
        return parsed
    }

    private fun bodyPayload(value: BodyStatEntity, creating: Boolean) = buildJsonObject {
        if (creating) put("public_id", value.publicId) else put("base_revision", value.revision)
        put("recorded_at", value.recordedAt)
        put("weight_kg", value.weightKg)
        value.bodyFatPercent?.let { put("body_fat_percent", it) }
        value.muscleMassKg?.let { put("muscle_mass_kg", it) }
        value.waterPercent?.let { put("water_percent", it) }
        value.visceralFat?.let { put("visceral_fat", it) }
        value.bmrKcal?.let { put("bmr_kcal", it) }
        value.bmi?.let { put("bmi", it) }
        value.notes?.let { put("notes", it) }
        if (creating || value.source == "user_override") put("source", value.source)
    }

    private fun nutritionPayload(value: NutritionEntryEntity, creating: Boolean) = buildJsonObject {
        if (creating) put("public_id", value.publicId) else put("base_revision", value.revision)
        put("date", value.date); put("meal_type", value.mealType); put("name", value.name)
        value.mealName?.let { put("meal_name", it) }; value.quantity?.let { put("quantity", it) }
        value.unit?.let { put("unit", it) }; value.foodId?.let { put("food_id", it) }
        value.caloriesKcal?.let { put("calories_kcal", it) }; value.proteinG?.let { put("protein_g", it) }
        value.fatG?.let { put("fat_g", it) }; value.netCarbsG?.let { put("net_carbs_g", it) }
        value.totalCarbsG?.let { put("total_carbs_g", it) }; value.fiberG?.let { put("fiber_g", it) }
        value.sugarG?.let { put("sugar_g", it) }; value.sodiumMg?.let { put("sodium_mg", it) }
        value.notes?.let { put("notes", it) }
        if (creating || value.source == "user_override") put("source", value.source)
    }

    private suspend fun coalesceHealthWrite(
        scope: String,
        createType: String,
        updateType: String,
        entityId: String,
        payload: JsonObject,
    ) {
        val create = dao.pendingAction(scope, entityId, createType)
        if (create != null && create.attemptCount == 0 && create.lastErrorCode == null) {
            dao.updatePendingEntity(create.withUpdatedPayload(payload.toString()))
            return
        }
        val update = dao.pendingAction(scope, entityId, updateType)
        if (update != null) {
            dao.updatePendingEntity(update.withUpdatedPayload(payload.toString()))
            return
        }
        enqueue(scope, if ("public_id" in payload) createType else updateType, entityId, UUID.randomUUID().toString(), payload.toString())
    }

    private suspend fun discardNeverSyncedCreate(scope: String, createType: String, entityId: String): Boolean {
        val create = dao.pendingAction(scope, entityId, createType) ?: return false
        if (create.attemptCount != 0 || create.lastErrorCode != null) return false
        dao.deletePending(create.localId)
        dao.pendingActionsByType(scope, createType.replace("create", "update"))
            .filter { it.entityId == entityId }
            .forEach { dao.deletePending(it.localId) }
        return true
    }

    private suspend fun recalculateNutritionDayLocked(scope: String, date: LocalDate) {
        val items = dao.nutritionEntries(scope, date.toString())
        fun sum(selector: (NutritionEntryEntity) -> String?): String? {
            val values = items.mapNotNull(selector).mapNotNull(String::toBigDecimalOrNull)
            return values.takeIf { it.isNotEmpty() }?.fold(BigDecimal.ZERO, BigDecimal::add)?.stripTrailingZeros()?.toPlainString()
        }
        dao.upsertNutritionDay(
            NutritionDayEntity(
                scope, date.toString(), sum { it.caloriesKcal }, sum { it.proteinG }, sum { it.fatG },
                sum { it.netCarbsG }, sum { it.totalCarbsG }, sum { it.fiberG }, sum { it.sugarG },
                sum { it.sodiumMg }, dao.nutritionDay(scope, date.toString())?.targetCaloriesKcal,
                Instant.now().toString(),
            ),
        )
    }

    private suspend fun recalculateLocalDayForInstantLocked(scope: String, recordedAt: String) {
        val zone = runCatching { ZoneId.of(dao.account(scope)?.timezone ?: "UTC") }.getOrDefault(ZoneOffset.UTC)
        val date = runCatching { Instant.parse(recordedAt).atZone(zone).toLocalDate() }.getOrElse { LocalDate.now(zone) }
        recalculateLocalDayLocked(scope, date, zone.id)
    }

    private suspend fun recalculateLocalDayLocked(scope: String, date: LocalDate, timezone: String) {
        val zone = runCatching { ZoneId.of(timezone) }.getOrDefault(ZoneOffset.UTC)
        val targetEnd = date.plusDays(1).atStartOfDay(zone).toInstant()
        val body = dao.bodyStats(scope).filter { runCatching { Instant.parse(it.recordedAt) < targetEnd }.getOrDefault(false) }.maxByOrNull { it.recordedAt }
        val exactBody = body?.let { runCatching { Instant.parse(it.recordedAt).atZone(zone).toLocalDate() == date }.getOrDefault(false) } == true
        val nutrition = dao.nutritionDay(scope, date.toString())
        val step = dao.dailyStepsForDate(scope, date.toString()).firstOrNull()
        val existing = dao.dailyHealthSummary(scope, date.toString())
        val status = when {
            listOf(body?.syncStatus, step?.syncStatus).any { it == "conflict" } -> "attention"
            listOf(body?.syncStatus, step?.syncStatus).any { it == "syncing" } -> "syncing"
            listOf(body?.syncStatus, step?.syncStatus).any { it == "pending" } || dao.nutritionEntries(scope, date.toString()).any { it.syncStatus == "pending" } -> "pending"
            else -> "synced"
        }
        dao.upsertDailyHealthSummary(
            DailyHealthSummaryEntity(
                scope, date.toString(), zone.id, body?.publicId, body?.weightKg, exactBody,
                nutrition?.caloriesKcal, nutrition?.proteinG, nutrition?.totalCarbsG ?: nutrition?.netCarbsG,
                nutrition?.fatG, nutrition?.fiberG, nutrition?.targetCaloriesKcal,
                step?.publicId, step?.steps, step?.goal,
                existing?.scheduledWorkouts ?: 0, existing?.completedWorkouts ?: 0,
                status, Instant.now().toString(),
                body?.source, step?.source,
            ),
        )
        val exactWeight = if (exactBody) body.weightKg else null
        dao.upsertHealthProgressPoints(
            listOf(
                HealthProgressPointEntity(
                    scope, date.toString(), exactWeight, step?.steps, nutrition?.caloriesKcal,
                    nutrition?.proteinG, nutrition?.totalCarbsG ?: nutrition?.netCarbsG,
                    nutrition?.fatG, Instant.now().toString(),
                    if (exactBody) body.source else null, step?.source,
                ),
            ),
        )
    }

    private suspend fun packageForDelivery(scope: String, deliveryId: String): WorkoutPackageEntity {
        return dao.packageForDelivery(scope, deliveryId)
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "Falta el package local.", false)
    }

    private fun validateDraftSet(value: DraftSetEntity, requireCompletedMetrics: Boolean) {
        val minimumReps = if (requireCompletedMetrics) 1 else 0
        if (value.reps !in minimumReps..10_000) {
            throw AppFailure(AppErrorCode.VALIDATION_ERROR, "Las repeticiones deben estar entre $minimumReps y 10 000.", false)
        }
        if (value.weightKg.toBigDecimalOrNull()?.let { it in BigDecimal.ZERO..BigDecimal("2000") } != true) {
            throw AppFailure(AppErrorCode.VALIDATION_ERROR, "La carga debe estar entre 0 y 2000 kg.", false)
        }
        if (value.rir?.toBigDecimalOrNull()?.let { it in BigDecimal.ZERO..BigDecimal.TEN } == false ||
            value.rir != null && value.rir.toBigDecimalOrNull() == null
        ) {
            throw AppFailure(AppErrorCode.VALIDATION_ERROR, "RIR debe estar entre 0 y 10.", false)
        }
        if (value.rpe?.toBigDecimalOrNull()?.let { it in BigDecimal.ONE..BigDecimal.TEN } == false ||
            value.rpe != null && value.rpe.toBigDecimalOrNull() == null
        ) {
            throw AppFailure(AppErrorCode.VALIDATION_ERROR, "RPE debe estar entre 1 y 10.", false)
        }
        if (value.durationSeconds?.let { it !in 1..86_400 } == true) {
            throw AppFailure(AppErrorCode.VALIDATION_ERROR, "La duración debe estar entre 1 y 86 400 segundos.", false)
        }
        if (value.restSeconds?.let { it !in 0..86_400 } == true) {
            throw AppFailure(AppErrorCode.VALIDATION_ERROR, "El descanso debe estar entre 0 y 86 400 segundos.", false)
        }
        if (value.distanceMeters?.toBigDecimalOrNull()?.signum()?.let { it < 0 } == true ||
            value.distanceMeters != null && value.distanceMeters.toBigDecimalOrNull() == null
        ) {
            throw AppFailure(AppErrorCode.VALIDATION_ERROR, "La distancia debe ser un número no negativo.", false)
        }
    }

    private suspend fun validateRecoveredDraft(draft: WorkoutDraftEntity): WorkoutDraftEntity {
        val candidate = repairRecoverableStartDraft(repairLegacyEmptyStartDraft(draft))
        val delivery = dao.delivery(candidate.accountScope, candidate.deliveryId)
        val pendingStart = dao.pendingStart(candidate.accountScope, candidate.deliveryId)
        val hasStartEvidence = pendingStart != null || delivery?.status in LOCAL_ACTIVE_DELIVERY_STATES
        if (candidate.status == "corrupt" && !hasStartEvidence) return candidate
        val validationCandidate = if (candidate.status == "corrupt") {
            candidate.copy(status = "active", corruptReasonCode = null)
        } else candidate
        val failure = runCatching {
            require(validationCandidate.schemaVersion == CONTRACT_VERSION) { "draft_schema_incompatible" }
            require(
                validationCandidate.status == "completion_pending" || validationCandidate.status == "aborted_pending" ||
                    !Instant.parse(validationCandidate.expiresAt).isBefore(Instant.now())
            ) { "draft_expired" }
            val storedPackage = dao.packageForDelivery(validationCandidate.accountScope, validationCandidate.deliveryId)
                ?: error("draft_package_missing")
            require(
                storedPackage.packageId == validationCandidate.packageId &&
                    storedPackage.packageHash.equals(validationCandidate.packageHash, ignoreCase = true)
            ) { "draft_package_mismatch" }
            val currentDelivery = dao.delivery(validationCandidate.accountScope, validationCandidate.deliveryId)
                ?: error("draft_delivery_missing")
            require(currentDelivery.accountScope == validationCandidate.accountScope) { "draft_account_scope_mismatch" }
            require(currentDelivery.packageHash.equals(validationCandidate.packageHash, ignoreCase = true)) { "draft_package_mismatch" }
            require(dao.packageExercises(validationCandidate.accountScope, validationCandidate.packageId).isNotEmpty()) {
                "draft_package_content_missing"
            }
            require(dao.packageSets(validationCandidate.accountScope, validationCandidate.packageId).isNotEmpty()) {
                "draft_package_content_missing"
            }
            val draftSets = dao.draftSets(validationCandidate.accountScope, validationCandidate.deliveryId)
            require(draftSets.isNotEmpty()) { "draft_sets_missing" }
            draftSets.forEach { set ->
                val weight = set.weightKg.toBigDecimalOrNull()
                require(set.accountScope == validationCandidate.accountScope && set.deliveryId == validationCandidate.deliveryId) {
                    "draft_account_scope_mismatch"
                }
                require(set.reps >= 0 && weight != null && weight.signum() >= 0) { "draft_metric_invalid" }
                require(set.rir == null || set.rir.toBigDecimalOrNull()?.let { it in BigDecimal.ZERO..BigDecimal.TEN } == true) { "draft_metric_invalid" }
                require(set.rpe == null || set.rpe.toBigDecimalOrNull()?.let { it in BigDecimal.ONE..BigDecimal.TEN } == true) { "draft_metric_invalid" }
                set.loadDetailsJson?.let { api.json.decodeFromString<LoadDetailsDto>(it) }
            }
            require(validationCandidate.payloadHash == draftPayloadHash(validationCandidate, draftSets)) {
                "draft_payload_hash_mismatch"
            }
            require(hasStartEvidence) { "draft_start_state_missing" }
            val local = preferences.values.first()
            local.accountScope?.let { require(it == validationCandidate.accountScope) { "draft_account_scope_mismatch" } }
            if (local.accountScope == validationCandidate.accountScope) {
                val account = dao.account(validationCandidate.accountScope) ?: error("draft_account_missing")
                require(account.deviceId == local.deviceId) { "draft_device_mismatch" }
                val profile = dao.localProfile(validationCandidate.accountScope) ?: error("draft_profile_missing")
                require(profile.profileId == currentDelivery.profileId) { "draft_profile_mismatch" }
            }
        }.exceptionOrNull()
        if (failure == null) {
            if (candidate.status == "corrupt") {
                val recovered = validationCandidate.copy(updatedAt = Instant.now().toString())
                dao.upsertDraft(recovered)
                if (BuildConfig.DEBUG) {
                    Log.i(
                        DRAFT_LOG_TAG,
                        "draft_validation_recovered delivery=${recovered.deliveryId} state=${recovered.status} " +
                            "code=draft_revalidated previous_code=${candidate.corruptReasonCode ?: "none"} exception=None",
                    )
                }
                return recovered
            }
            return validationCandidate
        }
        val reason = failure.message?.takeIf { it.startsWith("draft_") } ?: "draft_payload_invalid"
        if (BuildConfig.DEBUG) {
            Log.w(
                DRAFT_LOG_TAG,
                "draft_validation_failed delivery=${validationCandidate.deliveryId} state=${validationCandidate.status} code=$reason exception=${failure.javaClass.simpleName}",
            )
        }
        val isolationChanged = candidate.status != "corrupt" || candidate.corruptReasonCode != reason
        val isolated = if (isolationChanged) {
            candidate.copy(status = "corrupt", corruptReasonCode = reason, updatedAt = Instant.now().toString()).also {
                dao.upsertDraft(it)
            }
        } else {
            candidate
        }
        return repairLegacyEmptyStartDraft(isolated)
    }

    private suspend fun repairRecoverableStartDraft(draft: WorkoutDraftEntity): WorkoutDraftEntity {
        val pendingStart = dao.pendingStart(draft.accountScope, draft.deliveryId)
        val delivery = dao.delivery(draft.accountScope, draft.deliveryId) ?: return draft
        val hasStartEvidence = pendingStart != null || delivery.status in LOCAL_ACTIVE_DELIVERY_STATES
        if (!hasStartEvidence) return draft
        val storedPackage = dao.packageForDelivery(draft.accountScope, draft.deliveryId) ?: return draft
        if (storedPackage.packageId != draft.packageId ||
            !storedPackage.packageHash.equals(draft.packageHash, ignoreCase = true)
        ) return draft
        return database.withTransaction {
            var current = dao.draft(draft.accountScope, draft.deliveryId) ?: return@withTransaction draft
            val currentDelivery = dao.delivery(draft.accountScope, draft.deliveryId) ?: return@withTransaction current
            if (pendingStart != null && currentDelivery.status !in LOCAL_ACTIVE_DELIVERY_STATES) {
                val operation = runCatching {
                    api.json.decodeFromString<DeliveryOperationRequest>(pendingStart.payloadJson)
                }.getOrNull()
                dao.upsertDelivery(
                    listOf(
                        currentDelivery.copy(
                            status = "started_pending",
                            revision = maxOf(currentDelivery.revision, (operation?.baseRevision ?: currentDelivery.revision) + 1),
                            updatedAt = Instant.now().toString(),
                        ),
                    ),
                )
            }
            if (dao.draftSets(current.accountScope, current.deliveryId).isEmpty()) {
                val initialSets = dao.packageSets(current.accountScope, current.packageId)
                if (initialSets.isNotEmpty()) {
                    val now = Instant.now().toString()
                    initialSets.forEach { dao.upsertDraftSet(it.toInitialDraftSet(current.deliveryId, now)) }
                    current = current.copy(updatedAt = now)
                    current = current.copy(payloadHash = draftPayloadHash(current, dao.draftSets(current.accountScope, current.deliveryId)))
                    dao.upsertDraft(current)
                }
            }
            current
        }
    }

    private suspend fun repairLegacyEmptyStartDraft(draft: WorkoutDraftEntity): WorkoutDraftEntity {
        if (draft.status != "corrupt" || draft.corruptReasonCode != "draft_payload_hash_mismatch") return draft
        val delivery = dao.delivery(draft.accountScope, draft.deliveryId) ?: return draft
        val storedPackage = dao.packageForDelivery(draft.accountScope, draft.deliveryId) ?: return draft
        if (
            delivery.status !in setOf("started", "started_pending") ||
            storedPackage.packageId != draft.packageId ||
            storedPackage.packageHash != draft.packageHash ||
            dao.draftSets(draft.accountScope, draft.deliveryId).isNotEmpty()
        ) return draft
        val initialSets = dao.packageSets(draft.accountScope, storedPackage.packageId)
        if (initialSets.isEmpty()) return draft
        return database.withTransaction {
            val current = dao.draft(draft.accountScope, draft.deliveryId) ?: return@withTransaction draft
            if (dao.draftSets(draft.accountScope, draft.deliveryId).isNotEmpty()) return@withTransaction current
            val now = Instant.now().toString()
            initialSets.forEach { dao.upsertDraftSet(it.toInitialDraftSet(draft.deliveryId, now)) }
            val repaired = current.copy(status = "active", corruptReasonCode = null, updatedAt = now)
            repaired.copy(payloadHash = draftPayloadHash(repaired, dao.draftSets(draft.accountScope, draft.deliveryId))).also {
                dao.upsertDraft(it)
            }
        }
    }

    private fun PackageSetEntity.toInitialDraftSet(deliveryId: String, now: String) = DraftSetEntity(
        accountScope, deliveryId, exerciseOrder, setNumber, setNumber, reps ?: repsMin ?: 1,
        prescribedRir, prescribedRpe, prescribedWeightKg ?: "0", prescribedLoadDetailsJson,
        durationSeconds, distanceMeters, restSeconds, prescribedNotes, null, false, now,
    )

    private companion object {
        val LOCAL_ACTIVE_DELIVERY_STATES = setOf("started_pending", "started")
        val COMPARABLE_VOLUME_MODES = setOf(
            "direct_total", "per_side", "bar_plus_per_side", "machine_initial_total",
            "machine_initial_per_side", "machine_external_per_side_initial_total",
            "selector_stack", "dumbbell_each",
        )
    }

    private suspend fun applyBootstrap(scope: String, value: BootstrapResponse) {
        val device = value.device.deviceId
        val protectedScheduleIds = dao.queuedActions(scope, 1_000)
            .filter { it.actionType in setOf("planning_schedule", "planning_schedule_patch", "planning_cancel_schedule") }
            .mapTo(mutableSetOf(), PendingActionEntity::entityId)
        value.plannedWorkouts.forEach { remote ->
            val local = dao.planned(scope, remote.id)
            if (remote.id in protectedScheduleIds && local != null) {
                dao.upsertPlanningConflict(
                    PlanningConflictEntity(
                        scope,
                        remote.id,
                        "schedule",
                        local.revision,
                        remote.revision,
                        if (local.scheduledForDate != remote.scheduledForDate) "schedule_date_conflict:scheduled_for_date" else "revision_conflict:revision",
                        "${local.title} · ${local.scheduledForDate}",
                        "${remote.title} · ${remote.scheduledForDate}",
                        Instant.now().toString(),
                    ),
                )
                dao.upsertPlanned(listOf(local.copy(status = "conflict")))
            } else {
                dao.upsertPlanned(listOf(remote.toEntity(scope)))
            }
        }
        dao.upsertDelivery(value.companion.deliveries.map { it.toEntity(scope) })
        value.companion.profile?.let { dao.upsertProfile(it.toEntity(scope)) }
        dao.upsertRecent(value.completedWorkouts.map { it.toRecent(scope, "Servidor") })
        value.completedWorkouts.forEachIndexed { index, completed ->
            val history = completed.toHistoryParts(scope, "Entrenamiento", "server", "synced", completed.id)
            dao.replaceHistorySession(history.session, history.exercises, history.sets)
            dao.upsertHistoryPages(listOf(HistoryPageEntity(scope, HistoryFilters().cacheKey, history.session.publicId, index)))
        }
        dao.upsertHistoryQueryState(
            HistoryQueryStateEntity(
                scope, HistoryFilters().cacheKey, null,
                value.completedWorkouts.size >= 25, Instant.now().toString(),
            ),
        )
        dao.upsertSyncState(SyncStateEntity(scope, device, value.cursor, Instant.now().toString(), value.serverTime, null))
    }

    private suspend fun applyChange(scope: String, change: SyncChangeDto) {
        if (change.operation == "delete") {
            if (change.entityType == "planned_workout") dao.deletePlanned(scope, change.entityId)
            return
        }
        val payload = change.payload ?: return
        when (change.entityType) {
            "planned_workout" -> {
                val remote = api.json.decodeFromJsonElement(PlannedWorkoutDto.serializer(), payload)
                val local = dao.planned(scope, remote.id)
                val queued = dao.queuedActions(scope, 1_000).any {
                    it.entityId == remote.id &&
                        it.actionType in setOf("planning_schedule", "planning_schedule_patch", "planning_cancel_schedule")
                }
                if (local != null && queued && local.status in setOf("locally_pending", "syncing", "conflict", "cancelled")) {
                    dao.upsertPlanningConflict(
                        PlanningConflictEntity(
                            scope,
                            remote.id,
                            "schedule",
                            local.revision,
                            remote.revision,
                            if (local.scheduledForDate != remote.scheduledForDate) "schedule_date_conflict:scheduled_for_date" else "revision_conflict:revision",
                            "${local.title} · ${local.scheduledForDate}",
                            "${remote.title} · ${remote.scheduledForDate}",
                            Instant.now().toString(),
                        ),
                    )
                    dao.upsertPlanned(listOf(local.copy(status = "conflict")))
                } else {
                    dao.upsertPlanned(listOf(remote.toEntity(scope)))
                }
            }
            "completed_workout" -> {
                val completed = api.json.decodeFromJsonElement(CompletedWorkoutDto.serializer(), payload)
                dao.upsertRecent(listOf(completed.toRecent(scope, "Servidor")))
                val history = completed.toHistoryParts(scope, "Entrenamiento", "server", "synced", completed.id)
                dao.replaceHistorySession(history.session, history.exercises, history.sets)
                dao.upsertHistoryPages(listOf(HistoryPageEntity(scope, HistoryFilters().cacheKey, history.session.publicId, -1)))
            }
            "companion_delivery" -> dao.upsertDelivery(listOf(api.json.decodeFromJsonElement(DeliveryDto.serializer(), payload).toEntity(scope)))
            "companion_profile" -> dao.upsertProfile(api.json.decodeFromJsonElement(CompanionProfileDto.serializer(), payload).toEntity(scope))
            "training_plan" -> {
                val remote = api.json.decodeFromJsonElement(MobilePlanDto.serializer(), payload)
                val local = dao.plan(scope, remote.publicId)
                if (local?.syncStatus == "pending" || local?.syncStatus == "conflict") {
                    dao.upsertPlanningConflict(
                        PlanningConflictEntity(
                            scope, remote.publicId, "plan", local.revision, remote.revision,
                            "remote_revision", local.name, remote.name, Instant.now().toString(),
                        ),
                    )
                } else {
                    val parts = remote.toPlanParts(scope)
                    dao.replacePlan(parts.plan, parts.workouts, parts.exercises, parts.sets)
                }
            }
        }
    }

    private fun verifyBootstrap(value: BootstrapResponse) {
        if (value.schemaVersion != CONTRACT_VERSION || value.schemas.values.any { it != CONTRACT_VERSION }) {
            throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "El servidor publica schemas incompatibles.", false)
        }
        val required = setOf(
            "offline_sync_push", "incremental_pull", "planned_workouts", "completed_workouts",
            "companion_delivery", "capability_negotiation", "progress_checkpoints", "workout_package",
            "mobile_planning", "exercise_catalog",
        )
        if (required.any { value.capabilities[it] != true }) {
            throw AppFailure(AppErrorCode.SERVER_INCOMPATIBLE, "El servidor no ofrece todas las capacidades Android requeridas.", false)
        }
        if (value.limits.pushOperations < 1 || value.limits.pullLimit < 1) {
            throw AppFailure(AppErrorCode.SERVER_INCOMPATIBLE, "El servidor publica límites de sync inválidos.", false)
        }
    }

    private fun verifyNegotiation(value: NegotiationResponse) {
        if (value.selectedProtocolVersion != CONTRACT_VERSION ||
            value.selectedWorkoutSchemaVersion != CONTRACT_VERSION ||
            value.selectedResultSchemaVersion != CONTRACT_VERSION
        ) throw AppFailure(AppErrorCode.SERVER_INCOMPATIBLE, "No existe una versión Companion compatible.", false)
        val requiredFeatures = setOf("offline", "rpe", "rir", "weight")
        val requiredMetrics = setOf("reps", "weight_kg", "rest_seconds", "rpe", "rir")
        if (!value.acceptedFeatures.containsAll(requiredFeatures) || !value.acceptedMetrics.containsAll(requiredMetrics)) {
            throw AppFailure(AppErrorCode.SERVER_INCOMPATIBLE, "El servidor rechazó capacidades necesarias para la captura Android.", false)
        }
        if (value.effectiveLimits.maxPayloadBytes < 1 || value.effectiveLimits.maxProgressEventsPerWorkout < 1) {
            throw AppFailure(AppErrorCode.SERVER_INCOMPATIBLE, "El servidor publicó límites Companion inválidos.", false)
        }
    }

    private fun backoffMillis(attempt: Int): Long {
        val capped = min(attempt, 8)
        val base = 15_000L * (1L shl capped)
        return min(6 * 60 * 60 * 1000L, base + Random.nextLong(0, base / 4 + 1))
    }

    private fun draftPayloadHash(draft: WorkoutDraftEntity, sets: List<DraftSetEntity>): String =
        CanonicalJson.sha256(buildJsonObject {
            put("package_hash", draft.packageHash)
            put("client_submission_id", draft.clientSubmissionId)
            put("client_event_id", draft.clientEventId)
            put("started_at", draft.startedAt)
            put("average_heart_rate_bpm", draft.averageHeartRateBpm)
            put("calories_burned", draft.caloriesBurned)
            put("notes", draft.notes)
            put("sets", buildJsonArray {
                sets.sortedWith(compareBy(DraftSetEntity::exerciseOrder, DraftSetEntity::setNumber)).forEach { set ->
                    add(buildJsonObject {
                        put("exercise_order", set.exerciseOrder)
                        put("set_number", set.setNumber)
                        put("planned_set_number", set.plannedSetNumber)
                        put("reps", set.reps)
                        put("rir", set.rir)
                        put("rpe", set.rpe)
                        put("weight_kg", set.weightKg)
                        put("load_details", set.loadDetailsJson)
                        put("duration_seconds", set.durationSeconds)
                        put("distance_meters", set.distanceMeters)
                        put("rest_seconds", set.restSeconds)
                        put("notes", set.notes)
                        put("checkpoint_sequence", set.checkpointSequence)
                        put("completed", set.completed)
                    })
                }
            })
        })

    private suspend fun refreshLocalProgressSummaries(scope: String, now: Instant) {
        val sessions = dao.historySessions(scope)
        val exercises = dao.historyExercises(scope)
        val sets = dao.historySets(scope)
        listOf(7, 30, 90, 180, 365, null).forEach { days ->
            val selected = if (days == null) sessions else {
                val cutoff = now.minus(days.toLong(), ChronoUnit.DAYS)
                sessions.filter { session ->
                    runCatching { Instant.parse(session.completedAt) >= cutoff }.getOrDefault(false)
                }
            }
            val selectedIds = selected.mapTo(mutableSetOf(), HistorySessionEntity::publicId)
            val selectedExercises = exercises.filter { it.sessionPublicId in selectedIds }
            val selectedSets = sets.filter { it.sessionPublicId in selectedIds }
            val totalVolume = selected.mapNotNull { it.volumeKg?.toBigDecimalOrNull() }
                .fold(BigDecimal.ZERO, BigDecimal::add)
            val completedDays = selected.mapNotNull { session ->
                runCatching {
                    Instant.parse(session.completedAt)
                        .atZone(ZoneId.of(session.timezone))
                        .toLocalDate()
                }.getOrNull()
            }.toSet().size
            dao.upsertProgressSummary(
                ProgressSummaryEntity(
                    accountScope = scope,
                    range = days?.toString() ?: "all",
                    sessions = selected.size,
                    trainingDays = completedDays,
                    distinctExercises = selectedExercises
                        .map { it.exercisePublicId ?: it.name.trim().lowercase() }
                        .toSet().size,
                    completedSets = selectedSets.size,
                    totalReps = selectedSets.sumOf(HistorySetEntity::reps),
                    volumeKg = totalVolume.takeIf { it.signum() != 0 || selected.any { item -> item.volumeKg != null } }
                        ?.stripTrailingZeros()?.toPlainString(),
                    volumePartial = selected.any(HistorySessionEntity::volumePartial),
                    durationSeconds = selected.sumOf { it.durationSeconds ?: 0 },
                    comparisonJson = null,
                    updatedAt = now.toString(),
                ),
            )
        }
    }

    private fun PlannedWorkoutDto.toEntity(scope: String) = PlannedWorkoutEntity(
        scope, id, trainingPlanId, trainingPlanVersionId, scheduledForDate, timezone,
        status, title, revision, updatedAt, deleted, snapshot["workout_id"]?.jsonPrimitive?.content,
    )

    private fun DeliveryDto.toEntity(scope: String) = DeliveryEntity(
        scope, id, plannedWorkoutId, profileId, packageHash, status, revision,
        lastClientSequence, expiresAt, trainingSessionId, updatedAt,
    )

    private fun CompanionProfileDto.toEntity(scope: String) = LocalProfileEntity(
        scope, id, protocolVersion, workoutSchemaVersion, resultSchemaVersion, revision, lastNegotiatedAt,
    )

    private fun CompletedWorkoutDto.toRecent(scope: String, origin: String): RecentSessionEntity {
        val total = exercises.flatMap { it.sets }.mapNotNull { it.traditionalVolume() }
            .fold(BigDecimal.ZERO, BigDecimal::add)
        val safeId = id ?: clientEventId
            ?: throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "El entrenamiento no contiene un identificador.", false)
        val localClientEventId = clientEventId ?: safeId
        return RecentSessionEntity(
            scope, safeId, localClientEventId, plannedWorkoutId, "Entrenamiento",
            completedAt, durationSeconds, exercises.size, exercises.sumOf { it.sets.size },
            total.stripTrailingZeros().toPlainString(), origin, "synced",
            exercises.joinToString(", ") { it.name }.take(500),
        )
    }

    private fun MobileHistoryItemDto.toHistory(scope: String, existing: HistorySessionEntity?) = HistorySessionEntity(
        accountScope = scope,
        publicId = publicId,
        clientEventId = existing?.clientEventId ?: publicId,
        plannedWorkoutId = existing?.plannedWorkoutId,
        trainingPlanId = existing?.trainingPlanId,
        trainingPlanVersionId = existing?.trainingPlanVersionId,
        name = name,
        performedAt = performedAt,
        startedAt = existing?.startedAt,
        completedAt = completedAt,
        timezone = existing?.timezone ?: "UTC",
        durationSeconds = durationSeconds,
        exerciseCount = exerciseCount,
        setCount = setCount,
        volumeKg = volumeKg,
        volumePartial = volumePartial,
        source = source,
        syncStatus = syncStatus,
        notes = existing?.notes,
        detailCached = existing?.detailCached == true,
        updatedAt = Instant.now().toString(),
    )

    private fun MobileHistoryDetailDto.toHistoryParts(scope: String, clientEventId: String): HistoryParts {
        val session = HistorySessionEntity(
            scope, publicId, clientEventId, plannedWorkoutId, trainingPlanId, trainingPlanVersionId,
            name, performedAt, startedAt, completedAt, timezone, durationSeconds, exerciseCount,
            setCount, volumeKg, volumePartial, source, syncStatus, notes, true, Instant.now().toString(),
        )
        val exerciseRows = exercises.map {
            HistoryExerciseEntity(scope, publicId, it.exerciseOrder, it.exercisePublicId, it.name, it.notes)
        }
        val setRows = exercises.flatMap { exercise ->
            exercise.sets.map { set ->
                HistorySetEntity(
                    scope, publicId, exercise.exerciseOrder, set.setNumber, set.weightKg,
                    set.displayLoad?.value, set.displayLoad?.unit, set.loadMode, set.reps,
                    set.rir, set.rpe, set.restSeconds, set.durationSeconds, set.distanceMeters, set.notes,
                )
            }
        }
        return HistoryParts(session, exerciseRows, setRows)
    }

    private fun CompletedWorkoutDto.toHistoryParts(
        scope: String,
        title: String,
        source: String,
        syncStatus: String,
        publicId: String? = id,
    ): HistoryParts {
        val resolvedId = publicId ?: clientEventId
            ?: throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "La sesión no contiene identidad.", false)
        val eventId = clientEventId ?: resolvedId
        val sets = exercises.flatMap { it.sets }
        val volumes = sets.mapNotNull { it.traditionalVolume() }
        val session = HistorySessionEntity(
            scope, resolvedId, eventId, plannedWorkoutId, trainingPlanId, trainingPlanVersionId,
            title, completedAt, startedAt, completedAt, timezone, durationSeconds, exercises.size,
            sets.size, volumes.takeIf { it.isNotEmpty() }?.fold(BigDecimal.ZERO, BigDecimal::add)
                ?.stripTrailingZeros()?.toPlainString(),
            volumes.size != sets.size, source, syncStatus, notes, true,
            updatedAt ?: Instant.now().toString(),
        )
        val exerciseRows = exercises.map {
            HistoryExerciseEntity(scope, resolvedId, it.exerciseOrder, null, it.name, it.notes)
        }
        val setRows = exercises.flatMap { exercise ->
            exercise.sets.map { set ->
                val display = set.loadDetails?.displayTotal
                HistorySetEntity(
                    scope, resolvedId, exercise.exerciseOrder, set.setNumber,
                    set.weightKg.stripTrailingZeros().toPlainString(), display?.value, display?.unit,
                    set.loadMode(), set.reps, set.rir?.toPlainString(), set.rpe?.toPlainString(),
                    set.restSeconds, set.durationSeconds?.toString(),
                    set.loadDetails?.components?.get("distance_meters")?.value, set.notes,
                )
            }
        }
        return HistoryParts(session, exerciseRows, setRows)
    }

    private fun CompletedSetDto.loadMode(): String = loadDetails?.loadMode ?: "direct_total"

    private fun CompletedSetDto.traditionalVolume(): BigDecimal? =
        if (loadMode() in COMPARABLE_VOLUME_MODES && weightKg.signum() >= 0 && reps > 0) weightKg * reps.toBigDecimal()
        else null

    private fun ProgressSummaryDto.toEntity(scope: String, now: String) = ProgressSummaryEntity(
        scope, range, metrics.sessions, metrics.trainingDays, metrics.distinctExercises,
        metrics.completedSets, metrics.totalReps, metrics.volumeKg, metrics.volumePartial,
        metrics.durationSeconds,
        comparison?.let { kotlinx.serialization.json.Json.encodeToString(it) },
        now,
    )

    private fun ProgressExerciseDto.toEntity(scope: String, range: String, now: String) = ProgressExerciseEntity(
        scope, range, publicId, name, lastPerformedAt, sessionCount, setCount, bestLoadKg,
        bestRepetitionSet?.reps, bestRepetitionSet?.weightKg, volumeKg, volumePartial,
        loadComparable, loadModes.joinToString("|"), trend, now,
    )

    private fun ProgressPointDto.toEntity(scope: String, range: String, exerciseId: String) = ProgressPointEntity(
        scope, range, exerciseId, sessionPublicId, date, performedAt, bestLoadKg, bestReps,
        volumeKg, setCount, averageRir, averageRpe, loadComparable,
    )

    private fun PersonalRecordDto.toEntity(scope: String, range: String, exerciseId: String) = PersonalRecordEntity(
        scope, range, exerciseId, type, value, unit, date, sessionPublicId, setIndex,
    )

    private fun MobilePlanDto.toPlanEntity(scope: String, syncStatus: String) = MobilePlanEntity(
        scope, publicId, name, description, status, revision, activeVersionId, activeVersion,
        syncStatus, createdAt, updatedAt, archivedAt,
    )

    private fun MobilePlanDto.toPlanParts(scope: String): PlanningParts {
        val workoutRows = workouts.orEmpty().map {
            MobilePlanWorkoutEntity(
                scope, it.publicId, publicId, it.name, it.notes, it.position,
                it.estimatedDurationSeconds, it.revision, "synced", it.createdAt, it.updatedAt,
            )
        }
        val exerciseRows = workouts.orEmpty().flatMap { workout ->
            workout.exercises.map {
                MobilePlanExerciseEntity(
                    scope, workout.publicId, it.id, it.exerciseId, it.name, it.notes, it.exerciseOrder,
                )
            }
        }
        val setRows = workouts.orEmpty().flatMap { workout ->
            workout.exercises.flatMap { exercise ->
                exercise.sets.map {
                    MobilePlanSetEntity(
                        scope, workout.publicId, exercise.id, it.id, it.setNumber,
                        it.reps, it.repsMin, it.repsMax, it.weightKg, it.loadValue,
                        it.loadUnit, it.loadMode,
                        it.loadDetails?.let { details -> api.json.encodeToString(LoadDetailsDto.serializer(), details) },
                        it.rir, it.rpe, it.restSeconds,
                        it.durationSeconds, it.distanceMeters, it.notes,
                    )
                }
            }
        }
        return PlanningParts(toPlanEntity(scope, "synced"), workoutRows, exerciseRows, setRows)
    }

    private fun MobileBodyStatDto.toEntity(scope: String) = BodyStatEntity(
        scope, id, recordedAt, weightKg, bodyFatPercent, muscleMassKg, waterPercent,
        visceralFat, bmrKcal, bmi, notes, source, revision, revision.toLong(), "synced", createdAt, updatedAt,
    )

    private fun MobileNutritionEntryDto.toEntity(scope: String) = NutritionEntryEntity(
        scope, id, date, mealType, mealName, name, quantity, unit, foodId, caloriesKcal,
        proteinG, fatG, netCarbsG, totalCarbsG, fiberG, sugarG, sodiumMg, notes,
        dataComplete, revision, revision.toLong(), "synced", createdAt, updatedAt, source,
    )

    private fun MobileNutritionDayDto.toEntity(scope: String) = NutritionDayEntity(
        scope, date, totals.caloriesKcal, totals.proteinG, totals.fatG, totals.netCarbsG,
        totals.totalCarbsG, totals.fiberG, totals.sugarG, totals.sodiumMg, null, updatedAt,
    )

    private fun MobileFoodDto.toEntity(scope: String) = FoodCatalogEntity(
        scope, id, name, name.lowercase(), brand, servingSizeG, servingLabel, caloriesPer100g,
        proteinGPer100g, fatGPer100g, carbsGPer100g, netCarbsGPer100g, fiberGPer100g,
        sodiumMgPer100g, notes, custom, archived, dataComplete, revision, "synced", updatedAt,
    )

    private fun MobileStepDto.toEntity(scope: String) = DailyStepEntity(
        scope, id, date, steps, source, goal, revision, revision.toLong(), "synced", createdAt, updatedAt,
    )

    private fun JsonObject.optionalText(key: String): String? =
        this[key]?.takeUnless { it is JsonNull }?.jsonPrimitive?.content

    private fun MobileHealthTodayDto.toEntity(scope: String): DailyHealthSummaryEntity {
        val totals = nutrition.totals
        return DailyHealthSummaryEntity(
            scope, date, timezone, weight?.id, weight?.weightKg, weightIsExactDate,
            totals.optionalText("calories_kcal"), totals.optionalText("protein_g"),
            totals.optionalText("carbohydrate_g"), totals.optionalText("fat_g"),
            totals.optionalText("fiber_g"), null, steps.entryId, steps.value, steps.goal,
            training.scheduled, training.completed, "synced", updatedAt, weight?.source, steps.source,
        )
    }

    private fun MobileHealthPointDto.toEntity(scope: String) = HealthProgressPointEntity(
        scope, date, weightKg, steps, caloriesKcal, proteinG, carbohydrateG, fatG, Instant.now().toString(),
        weightSource, stepsSource,
    )

}
