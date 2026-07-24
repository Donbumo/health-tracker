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
import io.healthtracker.companion.core.security.SecureTokenStore
import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDate
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
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive

data class LoginOutcome(val accountScope: String, val profile: UserProfile)

private const val DRAFT_LOG_TAG = "HealthTrackerDraft"

class CompanionRepository(
    private val database: CompanionDatabase,
    private val preferences: PreferenceStore,
    private val tokens: SecureTokenStore,
    private val api: ApiClient,
) {
    private val dao = database.companionDao()
    private val syncMutex = Mutex()
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

    fun observeActiveDraft(scope: String): Flow<WorkoutDraftEntity?> = dao.observeActiveDraft(scope).map { draft ->
        draft?.let { validateRecoveredDraft(it) }
    }
    fun observePendingCount(scope: String): Flow<Int> = dao.observePendingCount(scope)
    fun observeConflictCount(scope: String): Flow<Int> = dao.observeConflictCount(scope)
    fun observeHistory(scope: String, limit: Int = 30, offset: Int = 0): Flow<List<RecentSessionEntity>> =
        dao.observeRecent(scope, limit, offset)

    suspend fun restoreLocalSession(): UserProfile? {
        val local = preferences.values.first()
        val scope = local.accountScope ?: return null
        if (!local.offlineSessionEligible || local.serverUrl == null || local.deviceId.isBlank()) return null
        if (tokens.refreshToken() == null) return null
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
            throw AppFailure(AppErrorCode.UNAUTHORIZED, "La sesión restaurada no corresponde a la cuenta local.", false)
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
        dao.packageForPlanned(scope, plannedId)?.let { existing ->
            val delivery = dao.delivery(scope, existing.deliveryId)
            if (delivery != null && existing.expiresAt?.let { Instant.parse(it).isAfter(Instant.now()) } != false) {
                return existing.deliveryId
            }
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
                dao.replacePackage(packageEntity, exercises, sets)
            }
        } catch (failure: AppFailure) {
            if (!failure.retryable) throw failure
            database.withTransaction {
                dao.upsertDelivery(listOf(delivery.toEntity(scope).copy(status = "acknowledged_pending", revision = delivery.revision + 1)))
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

    suspend fun clearConfirmedInvalidSession(scope: String) = clearLocal(scope)

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
        for (pending in dao.queuedActions(scope, 100)) {
            // The local queue is strict FIFO. A conflicted or backed-off predecessor
            // blocks later START/PROGRESS/COMPLETE operations instead of letting the
            // SQL readiness filter skip over a required transition.
            if (pending.status == "conflict" || pending.notBeforeEpochMs > System.currentTimeMillis()) return
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
                            dao.deleteDraft(scope, pending.entityId)
                            dao.deletePending(pending.localId)
                        }
                    }
                }
            } catch (failure: AppFailure) {
                if (
                    pending.actionType == "companion_start" &&
                    failure.code == AppErrorCode.REVISION_CONFLICT &&
                    reconcileStartedPending(scope, pending)
                ) continue
                if (!failure.retryable) {
                    dao.updatePending(pending.localId, "conflict", failure.code.name.lowercase(), Long.MAX_VALUE)
                    throw failure
                }
                val delay = failure.retryAfterSeconds?.times(1000) ?: backoffMillis(pending.attemptCount + 1)
                dao.updatePending(
                    pending.localId, "pending", failure.code.name.lowercase(), System.currentTimeMillis() + delay,
                )
                throw failure
            }
        }
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
        null, null, "0", null, durationSeconds, distanceMeters, restSeconds,
        null, null, false, now,
    )

    private companion object {
        val LOCAL_ACTIVE_DELIVERY_STATES = setOf("started_pending", "started")
    }

    private suspend fun applyBootstrap(scope: String, value: BootstrapResponse) {
        val device = value.device.deviceId
        dao.upsertPlanned(value.plannedWorkouts.map { it.toEntity(scope) })
        dao.upsertDelivery(value.companion.deliveries.map { it.toEntity(scope) })
        value.companion.profile?.let { dao.upsertProfile(it.toEntity(scope)) }
        dao.upsertRecent(value.completedWorkouts.map { it.toRecent(scope, "Servidor") })
        dao.upsertSyncState(SyncStateEntity(scope, device, value.cursor, Instant.now().toString(), value.serverTime, null))
    }

    private suspend fun applyChange(scope: String, change: SyncChangeDto) {
        if (change.operation == "delete") {
            if (change.entityType == "planned_workout") dao.deletePlanned(scope, change.entityId)
            return
        }
        val payload = change.payload ?: return
        when (change.entityType) {
            "planned_workout" -> dao.upsertPlanned(listOf(api.json.decodeFromJsonElement(PlannedWorkoutDto.serializer(), payload).toEntity(scope)))
            "completed_workout" -> dao.upsertRecent(listOf(api.json.decodeFromJsonElement(CompletedWorkoutDto.serializer(), payload).toRecent(scope, "Servidor")))
            "companion_delivery" -> dao.upsertDelivery(listOf(api.json.decodeFromJsonElement(DeliveryDto.serializer(), payload).toEntity(scope)))
            "companion_profile" -> dao.upsertProfile(api.json.decodeFromJsonElement(CompanionProfileDto.serializer(), payload).toEntity(scope))
        }
    }

    private fun verifyBootstrap(value: BootstrapResponse) {
        if (value.schemaVersion != CONTRACT_VERSION || value.schemas.values.any { it != CONTRACT_VERSION }) {
            throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "El servidor publica schemas incompatibles.", false)
        }
        val required = setOf(
            "offline_sync_push", "incremental_pull", "planned_workouts", "completed_workouts",
            "companion_delivery", "capability_negotiation", "progress_checkpoints", "workout_package",
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

    private fun PlannedWorkoutDto.toEntity(scope: String) = PlannedWorkoutEntity(
        scope, id, trainingPlanId, trainingPlanVersionId, scheduledForDate, timezone,
        status, title, revision, updatedAt, deleted,
    )

    private fun DeliveryDto.toEntity(scope: String) = DeliveryEntity(
        scope, id, plannedWorkoutId, profileId, packageHash, status, revision,
        lastClientSequence, expiresAt, trainingSessionId, updatedAt,
    )

    private fun CompanionProfileDto.toEntity(scope: String) = LocalProfileEntity(
        scope, id, protocolVersion, workoutSchemaVersion, resultSchemaVersion, revision, lastNegotiatedAt,
    )

    private fun CompletedWorkoutDto.toRecent(scope: String, origin: String): RecentSessionEntity {
        val total = exercises.flatMap { it.sets }.fold(BigDecimal.ZERO) { acc, set -> acc + set.weightKg }
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
}
