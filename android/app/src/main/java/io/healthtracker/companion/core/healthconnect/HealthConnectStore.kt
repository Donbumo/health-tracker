package io.healthtracker.companion.core.healthconnect

import androidx.room.withTransaction
import io.healthtracker.companion.core.database.BodyStatEntity
import io.healthtracker.companion.core.database.CompanionDatabase
import io.healthtracker.companion.core.database.DailyHealthSummaryEntity
import io.healthtracker.companion.core.database.DailyStepEntity
import io.healthtracker.companion.core.database.HealthConnectPermissionStateEntity
import io.healthtracker.companion.core.database.HealthConnectRecordLedgerEntity
import io.healthtracker.companion.core.database.HealthConnectSettingsEntity
import io.healthtracker.companion.core.database.HealthConnectSyncStateEntity
import io.healthtracker.companion.core.database.HealthProgressPointEntity
import io.healthtracker.companion.core.database.NutritionDayEntity
import io.healthtracker.companion.core.database.NutritionEntryEntity
import io.healthtracker.companion.core.database.PendingActionEntity
import io.healthtracker.companion.core.network.CanonicalJson
import java.math.BigDecimal
import java.math.RoundingMode
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZoneOffset
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

data class HealthConnectPermissionUpdate(val generation: Long, val changedTypes: Set<HealthConnectRecordType>)
data class HealthConnectImportResult(val imported: Int = 0, val deleted: Int = 0, val skipped: Int = 0)

interface HealthConnectSyncStorage {
    suspend fun ensureSettings(scope: String, availability: HealthConnectAvailability): HealthConnectSettingsEntity
    suspend fun updateAvailability(scope: String, availability: HealthConnectAvailability)
    suspend fun persistPermissions(scope: String, selected: Set<HealthConnectRecordType>, granted: Set<HealthConnectRecordType>, backgroundGranted: Boolean): HealthConnectPermissionUpdate
    suspend fun syncState(scope: String, type: HealthConnectRecordType): HealthConnectSyncStateEntity?
    suspend fun markSyncing(scope: String, type: HealthConnectRecordType, generation: Long, now: Instant)
    suspend fun markError(scope: String, type: HealthConnectRecordType, generation: Long, code: String)
    suspend fun applyRecords(scope: String, type: HealthConnectRecordType, records: List<HealthConnectRecord>, runMarker: String, generation: Long, nextToken: String? = null): HealthConnectImportResult
    suspend fun applyChanges(scope: String, type: HealthConnectRecordType, changes: List<HealthConnectChange>, nextToken: String, runMarker: String, generation: Long): HealthConnectImportResult
    suspend fun applyStepAggregates(scope: String, values: List<DailyStepsAggregate>, zoneId: ZoneId, runMarker: String, generation: Long, nextToken: String? = null): HealthConnectImportResult
    suspend fun completeFullReconciliation(scope: String, type: HealthConnectRecordType, windowStart: Instant, runMarker: String, token: String, generation: Long): HealthConnectImportResult
}

class HealthConnectStore(private val database: CompanionDatabase) : HealthConnectSyncStorage {
    private val dao = database.companionDao()

    fun observeSettings(scope: String): Flow<HealthConnectSettingsEntity?> = dao.observeHealthConnectSettings(scope)
    fun observePermissions(scope: String): Flow<List<HealthConnectPermissionStateEntity>> = dao.observeHealthConnectPermissions(scope)
    fun observeSyncStates(scope: String): Flow<List<HealthConnectSyncStateEntity>> = dao.observeHealthConnectSyncStates(scope)

    override suspend fun ensureSettings(scope: String, availability: HealthConnectAvailability): HealthConnectSettingsEntity {
        val existing = dao.healthConnectSettings(scope)
        if (existing != null) return existing
        val created = HealthConnectSettingsEntity(
            accountScope = scope,
            enabled = false,
            paused = false,
            selectedTypes = encodeTypes(HealthConnectRecordType.defaults),
            initialLookbackDays = 30,
            permissionGeneration = 0,
            lastAvailability = availability.storageValue(),
            updatedAt = Instant.now().toString(),
        )
        dao.upsertHealthConnectSettings(created)
        return created
    }

    suspend fun settings(scope: String): HealthConnectSettingsEntity? = dao.healthConnectSettings(scope)

    suspend fun isRecordImported(scope: String, type: HealthConnectRecordType, recordId: String): Boolean =
        dao.healthConnectLedger(scope, type.storageValue, recordId)?.state == "active"

    suspend fun setEnabled(scope: String, enabled: Boolean, paused: Boolean = false) {
        val now = Instant.now().toString()
        val current = ensureSettings(scope, HealthConnectAvailability.UNAVAILABLE_PROVIDER)
        dao.upsertHealthConnectSettings(current.copy(enabled = enabled, paused = paused, updatedAt = now))
    }

    suspend fun setPaused(scope: String, paused: Boolean) {
        val current = dao.healthConnectSettings(scope) ?: return
        dao.upsertHealthConnectSettings(current.copy(paused = paused, updatedAt = Instant.now().toString()))
    }

    suspend fun setSelectedTypes(scope: String, selected: Set<HealthConnectRecordType>) {
        val current = dao.healthConnectSettings(scope) ?: return
        val old = decodeTypes(current.selectedTypes)
        val changed = old union selected subtract (old intersect selected)
        val generation = if (changed.isEmpty()) current.permissionGeneration else current.permissionGeneration + 1
        database.withTransaction {
            dao.upsertHealthConnectSettings(
                current.copy(
                    selectedTypes = encodeTypes(selected),
                    permissionGeneration = generation,
                    updatedAt = Instant.now().toString(),
                ),
            )
            HealthConnectRecordType.entries.forEach { type ->
                dao.healthConnectSyncState(scope, type.storageValue)?.let { state ->
                    val affected = type in changed
                    dao.upsertHealthConnectSyncState(
                        state.copy(
                            token = if (affected) null else state.token,
                            tokenCreatedAt = if (affected) null else state.tokenCreatedAt,
                            permissionGeneration = generation,
                            state = if (affected) "selection_changed" else state.state,
                        ),
                    )
                }
            }
        }
    }

    override suspend fun updateAvailability(scope: String, availability: HealthConnectAvailability) {
        val current = ensureSettings(scope, availability)
        dao.upsertHealthConnectSettings(
            current.copy(lastAvailability = availability.storageValue(), updatedAt = Instant.now().toString()),
        )
    }

    override suspend fun persistPermissions(
        scope: String,
        selected: Set<HealthConnectRecordType>,
        granted: Set<HealthConnectRecordType>,
        backgroundGranted: Boolean,
    ): HealthConnectPermissionUpdate {
        val now = Instant.now().toString()
        val currentSettings = dao.healthConnectSettings(scope) ?: error("health_connect_settings_missing")
        val previous = dao.healthConnectPermissions(scope).associateBy { it.recordType }
        val changed = HealthConnectRecordType.entries.filterTo(mutableSetOf()) { type ->
            previous[type.storageValue]?.granted != (type in granted)
        }
        val generation = if (changed.isEmpty()) currentSettings.permissionGeneration else currentSettings.permissionGeneration + 1
        database.withTransaction {
            dao.upsertHealthConnectPermissions(
                HealthConnectRecordType.entries.map { type ->
                    HealthConnectPermissionStateEntity(
                        scope,
                        type.storageValue,
                        type in selected,
                        type in granted,
                        backgroundGranted,
                        now,
                        if (type in selected && type !in granted) "access_missing" else null,
                    )
                },
            )
            dao.upsertHealthConnectSettings(currentSettings.copy(permissionGeneration = generation, updatedAt = now))
            HealthConnectRecordType.entries.forEach { type ->
                dao.healthConnectSyncState(scope, type.storageValue)?.let { state ->
                    val affected = type in changed
                    dao.upsertHealthConnectSyncState(
                        state.copy(
                            token = if (affected) null else state.token,
                            tokenCreatedAt = if (affected) null else state.tokenCreatedAt,
                            permissionGeneration = generation,
                            state = if (!affected) state.state else if (type in granted) "permission_changed" else "access_revoked",
                            lastErrorCode = if (!affected) state.lastErrorCode else if (type in granted) null else "permission_revoked",
                        ),
                    )
                }
            }
        }
        return HealthConnectPermissionUpdate(generation, changed)
    }

    override suspend fun syncState(scope: String, type: HealthConnectRecordType): HealthConnectSyncStateEntity? =
        dao.healthConnectSyncState(scope, type.storageValue)

    override suspend fun markSyncing(scope: String, type: HealthConnectRecordType, generation: Long, now: Instant) {
        val current = dao.healthConnectSyncState(scope, type.storageValue)
        dao.upsertHealthConnectSyncState(
            (current ?: emptySyncState(scope, type, generation)).copy(
                state = "syncing",
                lastAttemptAt = now.toString(),
                lastErrorCode = null,
                permissionGeneration = generation,
            ),
        )
    }

    override suspend fun markError(scope: String, type: HealthConnectRecordType, generation: Long, code: String) {
        val current = dao.healthConnectSyncState(scope, type.storageValue)
        dao.upsertHealthConnectSyncState(
            (current ?: emptySyncState(scope, type, generation)).copy(
                state = if (code == "permission_revoked") "access_revoked" else "error_recoverable",
                lastErrorCode = code,
                permissionGeneration = generation,
            ),
        )
    }

    override suspend fun applyRecords(
        scope: String,
        type: HealthConnectRecordType,
        records: List<HealthConnectRecord>,
        runMarker: String,
        generation: Long,
        nextToken: String?,
    ): HealthConnectImportResult = database.withTransaction {
        var imported = 0
        var deleted = 0
        var skipped = 0
        records.forEach { record ->
            val previous = dao.healthConnectLedger(scope, type.storageValue, record.metadata.id)
            if (upsertRecordLocked(scope, type, record, runMarker)) {
                imported++
            } else {
                val current = dao.healthConnectLedger(scope, type.storageValue, record.metadata.id)
                if (previous?.localResourceUuid != null && current?.localResourceUuid == null && current?.state in setOf("invalid", "unrepresentable")) {
                    deleted++
                } else {
                    skipped++
                }
            }
        }
        if (nextToken != null) advanceTokenLocked(scope, type, nextToken, generation, imported, deleted, runMarker)
        HealthConnectImportResult(imported = imported, deleted = deleted, skipped = skipped)
    }

    override suspend fun applyChanges(
        scope: String,
        type: HealthConnectRecordType,
        changes: List<HealthConnectChange>,
        nextToken: String,
        runMarker: String,
        generation: Long,
    ): HealthConnectImportResult = database.withTransaction {
        var imported = 0
        var deleted = 0
        var skipped = 0
        changes.forEach { change ->
            when (change) {
                is HealthConnectChange.Upsert -> {
                    val previous = dao.healthConnectLedger(scope, type.storageValue, change.record.metadata.id)
                    if (upsertRecordLocked(scope, type, change.record, runMarker)) {
                        imported++
                    } else {
                        val current = dao.healthConnectLedger(scope, type.storageValue, change.record.metadata.id)
                        if (previous?.localResourceUuid != null && current?.localResourceUuid == null && current?.state in setOf("invalid", "unrepresentable")) {
                            deleted++
                        } else {
                            skipped++
                        }
                    }
                }
                is HealthConnectChange.Delete -> if (deleteRecordLocked(scope, type, change.recordId, runMarker)) deleted++ else skipped++
            }
        }
        advanceTokenLocked(scope, type, nextToken, generation, imported, deleted, runMarker)
        HealthConnectImportResult(imported, deleted, skipped)
    }

    override suspend fun applyStepAggregates(
        scope: String,
        values: List<DailyStepsAggregate>,
        zoneId: ZoneId,
        runMarker: String,
        generation: Long,
        nextToken: String?,
    ): HealthConnectImportResult = database.withTransaction {
        var imported = 0
        var deleted = 0
        values.forEach { aggregate ->
            val logicalId = stepLogicalId(aggregate.date, zoneId.id)
            if (aggregate.steps == null) {
                if (deleteRecordLocked(scope, HealthConnectRecordType.STEPS, logicalId, runMarker)) deleted++
            } else if (upsertStepsLocked(scope, aggregate, zoneId, logicalId, runMarker)) {
                imported++
            }
        }
        if (nextToken != null) advanceTokenLocked(scope, HealthConnectRecordType.STEPS, nextToken, generation, imported, deleted, runMarker)
        HealthConnectImportResult(imported, deleted)
    }

    override suspend fun completeFullReconciliation(
        scope: String,
        type: HealthConnectRecordType,
        windowStart: Instant,
        runMarker: String,
        token: String,
        generation: Long,
    ): HealthConnectImportResult = database.withTransaction {
        var deleted = 0
        dao.activeHealthConnectLedgersSince(scope, type.storageValue, windowStart.toString())
            .filter { it.lastSeenAt != runMarker }
            .forEach { if (deleteRecordLocked(scope, type, it.healthConnectRecordId, runMarker)) deleted++ }
        val current = dao.healthConnectSyncState(scope, type.storageValue)
        dao.upsertHealthConnectSyncState(
            (current ?: emptySyncState(scope, type, generation)).copy(
                token = token,
                tokenCreatedAt = runMarker,
                lastSuccessfulReadAt = runMarker,
                lastFullReconciliationAt = runMarker,
                permissionGeneration = generation,
                state = "connected",
                lastImportedAt = runMarker,
                deletedCount = (current?.deletedCount ?: 0) + deleted,
                lastErrorCode = null,
            ),
        )
        HealthConnectImportResult(deleted = deleted)
    }

    suspend fun deleteImported(scope: String): HealthConnectImportResult = database.withTransaction {
        var deleted = 0
        dao.activeHealthConnectLedgers(scope).forEach { ledger ->
            val type = HealthConnectRecordType.fromStorage(ledger.recordType) ?: return@forEach
            if (deleteRecordLocked(scope, type, ledger.healthConnectRecordId, Instant.now().toString())) deleted++
        }
        HealthConnectImportResult(deleted = deleted)
    }

    suspend fun detachUserOverride(scope: String, resourceId: String) {
        dao.detachHealthConnectLedgers(scope, resourceId, Instant.now().toString())
    }

    private suspend fun upsertRecordLocked(
        scope: String,
        type: HealthConnectRecordType,
        record: HealthConnectRecord,
        marker: String,
    ): Boolean {
        val existingLedger = dao.healthConnectLedger(scope, type.storageValue, record.metadata.id)
        if (existingLedger?.detachedByUser == true) {
            dao.upsertHealthConnectLedger(listOf(existingLedger.copy(lastSeenAt = marker, state = "detached")))
            return false
        }
        return when (record) {
            is HealthConnectWeight -> upsertWeightLocked(scope, record, existingLedger, marker)
            is HealthConnectBodyFat -> upsertBodyFatLocked(scope, record, existingLedger, marker)
            is HealthConnectNutrition -> upsertNutritionLocked(scope, record, existingLedger, marker)
            is HealthConnectLeanBodyMass, is HealthConnectBodyWaterMass -> {
                dao.upsertHealthConnectLedger(listOf(record.toLedger(scope, type, existingLedger, null, marker, "unsupported_mapping", fingerprint(record))))
                false
            }
        }
    }

    private suspend fun upsertWeightLocked(
        scope: String,
        record: HealthConnectWeight,
        ledger: HealthConnectRecordLedgerEntity?,
        marker: String,
    ): Boolean {
        val content = fingerprint(record)
        if (!record.kilograms.isFinite() || record.kilograms !in 0.001..1000.0) {
            if (ledger?.localResourceUuid != null) {
                deleteRecordLocked(scope, HealthConnectRecordType.WEIGHT, record.metadata.id, marker)
            }
            dao.upsertHealthConnectLedger(listOf(record.toLedger(scope, HealthConnectRecordType.WEIGHT, ledger, null, marker, "invalid", content)))
            return false
        }
        val id = ledger?.localResourceUuid ?: UUID.randomUUID().toString()
        val existing = dao.bodyStat(scope, id)
        val weight = decimal(record.kilograms, 3)
        val now = marker
        if (existing?.source == "user_override") {
            dao.upsertHealthConnectLedger(
                listOf(record.toLedger(scope, HealthConnectRecordType.WEIGHT, ledger, null, marker, "detached", content).copy(detachedByUser = true)),
            )
            return false
        }
        val changed = ledger?.contentFingerprint != content || existing == null || existing.weightKg != weight
        if (!changed) {
            dao.upsertHealthConnectLedger(listOf(record.toLedger(scope, HealthConnectRecordType.WEIGHT, ledger, id, marker, "active", content)))
            return false
        }
        val entity = (existing ?: BodyStatEntity(
            scope, id, record.startTime.toString(), weight, null, null, null, null, null, null,
            null, "health_connect", 0, 1, "pending", now, now, record.zoneOffset,
        )).copy(
            recordedAt = record.startTime.toString(),
            weightKg = weight,
            source = "health_connect",
            sourceZoneOffset = record.zoneOffset,
            localRevision = (existing?.localRevision ?: 0) + 1,
            syncStatus = "pending",
            updatedAt = now,
        )
        dao.upsertBodyStats(listOf(entity))
        dao.upsertHealthConnectLedger(listOf(record.toLedger(scope, HealthConnectRecordType.WEIGHT, ledger, id, marker, "active", content)))
        if (changed) enqueueBodyLocked(scope, entity, id)
        recalculateDayForInstantLocked(scope, entity.recordedAt)
        return changed
    }

    private suspend fun upsertBodyFatLocked(
        scope: String,
        record: HealthConnectBodyFat,
        ledger: HealthConnectRecordLedgerEntity?,
        marker: String,
    ): Boolean {
        val content = fingerprint(record)
        if (!record.percentage.isFinite() || record.percentage !in 0.0..100.0) {
            if (ledger?.localResourceUuid != null) {
                deleteRecordLocked(scope, HealthConnectRecordType.BODY_FAT, record.metadata.id, marker)
            }
            dao.upsertHealthConnectLedger(listOf(record.toLedger(scope, HealthConnectRecordType.BODY_FAT, ledger, null, marker, "invalid", content)))
            return false
        }
        val body = ledger?.localResourceUuid?.let { dao.bodyStat(scope, it) }
            ?: dao.healthConnectBodyStatAtOrigin(scope, record.startTime.toString(), record.metadata.dataOrigin)
        if (body == null || body.source != "health_connect") {
            dao.upsertHealthConnectLedger(listOf(record.toLedger(scope, HealthConnectRecordType.BODY_FAT, ledger, null, marker, "unrepresentable", content)))
            return false
        }
        val percentage = decimal(record.percentage, 3)
        val changed = ledger?.contentFingerprint != content || body.bodyFatPercent != percentage
        if (!changed) {
            dao.upsertHealthConnectLedger(listOf(record.toLedger(scope, HealthConnectRecordType.BODY_FAT, ledger, body.publicId, marker, "active", content)))
            return false
        }
        val updated = body.copy(
            bodyFatPercent = percentage,
            localRevision = body.localRevision + 1,
            syncStatus = "pending",
            updatedAt = marker,
        )
        dao.upsertBodyStats(listOf(updated))
        dao.upsertHealthConnectLedger(listOf(record.toLedger(scope, HealthConnectRecordType.BODY_FAT, ledger, body.publicId, marker, "active", content)))
        if (changed) enqueueBodyLocked(scope, updated, body.publicId)
        recalculateDayForInstantLocked(scope, body.recordedAt)
        return changed
    }

    private suspend fun upsertNutritionLocked(
        scope: String,
        record: HealthConnectNutrition,
        ledger: HealthConnectRecordLedgerEntity?,
        marker: String,
    ): Boolean {
        val zone = record.zoneOffset?.let { runCatching { ZoneOffset.of(it) }.getOrNull() }
            ?: runCatching { ZoneId.of(dao.account(scope)?.timezone ?: "UTC") }.getOrDefault(ZoneOffset.UTC)
        val startDate = record.startTime.atZone(zone).toLocalDate()
        val endDate = record.endTime.minusNanos(1).atZone(zone).toLocalDate()
        val name = record.name?.trim()?.takeIf { it.isNotEmpty() }?.take(200)
        val content = fingerprint(record)
        val nutrients = listOf(
            record.caloriesKcal, record.proteinGrams, record.fatGrams, record.carbohydrateGrams,
            record.fiberGrams, record.sugarGrams, record.sodiumMilligrams,
        )
        if (record.mealType == null || name == null || startDate != endDate || nutrients.all { it == null } || nutrients.any { it != null && (!it.isFinite() || it < 0) }) {
            if (ledger?.localResourceUuid != null) {
                deleteRecordLocked(scope, HealthConnectRecordType.NUTRITION, record.metadata.id, marker)
            }
            dao.upsertHealthConnectLedger(listOf(record.toLedger(scope, HealthConnectRecordType.NUTRITION, ledger, null, marker, "unrepresentable", content)))
            return false
        }
        val id = ledger?.localResourceUuid ?: UUID.randomUUID().toString()
        val existing = dao.nutritionEntry(scope, id)
        if (existing?.source == "user_override") {
            dao.upsertHealthConnectLedger(listOf(record.toLedger(scope, HealthConnectRecordType.NUTRITION, ledger, null, marker, "detached", content).copy(detachedByUser = true)))
            return false
        }
        val entity = NutritionEntryEntity(
            accountScope = scope,
            publicId = id,
            date = startDate.toString(),
            mealType = record.mealType,
            mealName = null,
            name = name,
            quantity = null,
            unit = null,
            foodId = null,
            caloriesKcal = record.caloriesKcal?.let { decimal(it, 3) },
            proteinG = record.proteinGrams?.let { decimal(it, 3) },
            fatG = record.fatGrams?.let { decimal(it, 3) },
            netCarbsG = null,
            totalCarbsG = record.carbohydrateGrams?.let { decimal(it, 3) },
            fiberG = record.fiberGrams?.let { decimal(it, 3) },
            sugarG = record.sugarGrams?.let { decimal(it, 3) },
            sodiumMg = record.sodiumMilligrams?.let { decimal(it, 3) },
            notes = null,
            dataComplete = listOf(record.caloriesKcal, record.proteinGrams, record.fatGrams, record.carbohydrateGrams).all { it != null },
            revision = existing?.revision ?: 0,
            localRevision = (existing?.localRevision ?: 0) + 1,
            syncStatus = "pending",
            createdAt = existing?.createdAt ?: marker,
            updatedAt = marker,
            source = "health_connect",
        )
        val changed = ledger?.contentFingerprint != content || existing == null
        if (!changed) {
            dao.upsertHealthConnectLedger(listOf(record.toLedger(scope, HealthConnectRecordType.NUTRITION, ledger, id, marker, "active", content)))
            return false
        }
        dao.upsertNutritionEntries(listOf(entity))
        dao.upsertHealthConnectLedger(listOf(record.toLedger(scope, HealthConnectRecordType.NUTRITION, ledger, id, marker, "active", content)))
        if (changed) enqueueNutritionLocked(scope, entity, id)
        recalculateNutritionDayLocked(scope, startDate)
        recalculateDayLocked(scope, startDate)
        return changed
    }

    private suspend fun upsertStepsLocked(
        scope: String,
        aggregate: DailyStepsAggregate,
        zoneId: ZoneId,
        logicalId: String,
        marker: String,
    ): Boolean {
        val count = aggregate.steps ?: return false
        if (count !in 0..10_000_000L) return false
        val ledger = dao.healthConnectLedger(scope, HealthConnectRecordType.STEPS.storageValue, logicalId)
        val id = ledger?.localResourceUuid ?: UUID.randomUUID().toString()
        val existing = dao.dailyStepBySource(scope, aggregate.date, "health_connect_aggregate")
        val fingerprint = sha256("${aggregate.date}|$count|${zoneId.id}")
        val changed = ledger?.contentFingerprint != fingerprint || existing == null || existing.steps != count
        if (!changed) {
            dao.upsertHealthConnectLedger(
                listOf(
                    ledger.copy(
                        lastModifiedTime = marker,
                        lastSeenAt = marker,
                        sourceStartTime = LocalDate.parse(aggregate.date).atStartOfDay(zoneId).toInstant().toString(),
                        sourceEndTime = aggregate.date,
                    ),
                ),
            )
            return false
        }
        val entity = DailyStepEntity(
            scope, id, aggregate.date, count, "health_connect_aggregate", existing?.goal,
            existing?.revision ?: 0, (existing?.localRevision ?: 0) + 1, "pending",
            existing?.createdAt ?: marker, marker,
        )
        dao.upsertDailySteps(listOf(entity))
        dao.upsertHealthConnectLedger(
            listOf(
                HealthConnectRecordLedgerEntity(
                    scope, HealthConnectRecordType.STEPS.storageValue, logicalId, null, "aggregate",
                    id, id, marker, null, fingerprint, ledger?.importedAt ?: marker, marker,
                    "active", false, null,
                    LocalDate.parse(aggregate.date).atStartOfDay(zoneId).toInstant().toString(), aggregate.date,
                ),
            ),
        )
        if (changed) enqueueStepsLocked(scope, entity, id)
        recalculateDayLocked(scope, LocalDate.parse(aggregate.date))
        return changed
    }

    private suspend fun deleteRecordLocked(
        scope: String,
        type: HealthConnectRecordType,
        recordId: String,
        marker: String,
    ): Boolean {
        val ledger = dao.healthConnectLedger(scope, type.storageValue, recordId) ?: return false
        if (ledger.state == "deleted" || ledger.state == "source_deleted_detached") return false
        if (ledger.detachedByUser || ledger.state == "detached") {
            dao.upsertHealthConnectLedger(listOf(ledger.copy(state = "source_deleted_detached", deletedAt = marker, lastSeenAt = marker, localResourceUuid = null)))
            return false
        }
        val resourceId = ledger.localResourceUuid
        if (type == HealthConnectRecordType.BODY_FAT) {
            resourceId?.let { id ->
                dao.bodyStat(scope, id)?.let { body ->
                    if (body.bodyFatPercent != null) {
                        val updated = body.copy(
                            bodyFatPercent = null,
                            localRevision = body.localRevision + 1,
                            syncStatus = "pending",
                            updatedAt = marker,
                        )
                        dao.upsertBodyStats(listOf(updated))
                        enqueueBodyLocked(scope, updated, id)
                        recalculateDayForInstantLocked(scope, updated.recordedAt)
                    }
                }
            }
            dao.upsertHealthConnectLedger(
                listOf(ledger.copy(state = "deleted", deletedAt = marker, lastSeenAt = marker, localResourceUuid = null)),
            )
            return true
        }
        if (resourceId != null) {
            when (type) {
                HealthConnectRecordType.WEIGHT -> dao.bodyStat(scope, resourceId)?.let { body ->
                    deletePendingOrQueueDeleteLocked(scope, resourceId, body.revision, "health_body")
                    dao.deleteBodyStat(scope, resourceId)
                    recalculateDayForInstantLocked(scope, body.recordedAt)
                }
                HealthConnectRecordType.NUTRITION -> dao.nutritionEntry(scope, resourceId)?.let { nutrition ->
                    deletePendingOrQueueDeleteLocked(scope, resourceId, nutrition.revision, "health_nutrition")
                    dao.deleteNutritionEntry(scope, resourceId)
                    val date = LocalDate.parse(nutrition.date)
                    recalculateNutritionDayLocked(scope, date)
                    recalculateDayLocked(scope, date)
                }
                HealthConnectRecordType.STEPS -> dao.dailyStep(scope, resourceId)?.let { steps ->
                    deletePendingOrQueueDeleteLocked(scope, resourceId, steps.revision, "health_steps")
                    dao.deleteDailyStep(scope, resourceId)
                    recalculateDayLocked(scope, LocalDate.parse(steps.date))
                }
                else -> Unit
            }
            dao.healthConnectLedgersForResource(scope, resourceId).forEach { related ->
                dao.upsertHealthConnectLedger(listOf(related.copy(state = "deleted", deletedAt = marker, lastSeenAt = marker, localResourceUuid = null)))
            }
        } else {
            dao.upsertHealthConnectLedger(listOf(ledger.copy(state = "deleted", deletedAt = marker, lastSeenAt = marker)))
        }
        return true
    }

    private suspend fun enqueueBodyLocked(scope: String, value: BodyStatEntity, clientEventId: String) {
        val payload = buildJsonObject {
            if (value.revision == 0) put("public_id", value.publicId) else put("base_revision", value.revision)
            put("client_event_id", clientEventId)
            put("recorded_at", value.recordedAt)
            put("weight_kg", value.weightKg)
            value.bodyFatPercent?.let { put("body_fat_percent", it) } ?: put("body_fat_percent", JsonNull)
            if (value.revision == 0) put("source", "health_connect")
        }
        enqueueResourceLocked(scope, value.publicId, value.revision, "health_body", payload)
    }

    private suspend fun enqueueNutritionLocked(scope: String, value: NutritionEntryEntity, clientEventId: String) {
        val payload = buildJsonObject {
            if (value.revision == 0) put("public_id", value.publicId) else put("base_revision", value.revision)
            put("client_event_id", clientEventId)
            put("date", value.date); put("meal_type", value.mealType); put("name", value.name)
            value.caloriesKcal?.let { put("calories_kcal", it) } ?: put("calories_kcal", JsonNull)
            value.proteinG?.let { put("protein_g", it) } ?: put("protein_g", JsonNull)
            value.fatG?.let { put("fat_g", it) } ?: put("fat_g", JsonNull)
            value.totalCarbsG?.let { put("total_carbs_g", it) } ?: put("total_carbs_g", JsonNull)
            value.fiberG?.let { put("fiber_g", it) } ?: put("fiber_g", JsonNull)
            value.sugarG?.let { put("sugar_g", it) } ?: put("sugar_g", JsonNull)
            value.sodiumMg?.let { put("sodium_mg", it) } ?: put("sodium_mg", JsonNull)
            if (value.revision == 0 || value.source == "user_override") put("source", value.source)
        }
        enqueueResourceLocked(scope, value.publicId, value.revision, "health_nutrition", payload)
    }

    private suspend fun enqueueStepsLocked(scope: String, value: DailyStepEntity, clientEventId: String) {
        val payload = buildJsonObject {
            if (value.revision == 0) put("public_id", value.publicId) else put("base_revision", value.revision)
            put("client_event_id", clientEventId)
            put("date", value.date); put("steps", value.steps)
            if (value.revision == 0) put("source", "health_connect_aggregate")
        }
        enqueueResourceLocked(scope, value.publicId, value.revision, "health_steps", payload)
    }

    private suspend fun enqueueResourceLocked(scope: String, entityId: String, revision: Int, prefix: String, payload: JsonObject) {
        val createType = "${prefix}_create"
        val updateType = "${prefix}_update"
        val existingCreate = dao.pendingAction(scope, entityId, createType)
        if (existingCreate != null && existingCreate.attemptCount == 0 && existingCreate.lastErrorCode == null) {
            val payloadText = payload.toString()
            val payloadHash = CanonicalJson.sha256(payload)
            dao.updatePendingEntity(existingCreate.copy(payloadJson = payloadText, payloadHash = payloadHash))
            return
        }
        val actionType = if (revision == 0 && existingCreate == null) createType else updateType
        val effectivePayload = if (actionType == updateType && revision == 0) asDeferredUpdatePayload(payload) else payload
        val payloadText = effectivePayload.toString()
        val payloadHash = CanonicalJson.sha256(effectivePayload)
        dao.pendingAction(scope, entityId, actionType)?.let {
            val idempotencyKey = if (it.attemptCount > 0 || it.lastErrorCode != null) {
                stableIdempotencyKey(scope, entityId, actionType, payloadHash)
            } else {
                it.idempotencyKey
            }
            dao.updatePendingEntity(
                it.copy(
                    idempotencyKey = idempotencyKey,
                    payloadJson = payloadText,
                    payloadHash = payloadHash,
                    status = "pending",
                    attemptCount = 0,
                    notBeforeEpochMs = 0,
                    lastErrorCode = null,
                ),
            )
            return
        }
        val key = stableIdempotencyKey(scope, entityId, actionType, payloadHash)
        if (dao.pendingByKey(scope, key) == null) {
            dao.insertPending(PendingActionEntity(accountScope = scope, actionType = actionType, entityId = entityId, idempotencyKey = key, payloadJson = payloadText, payloadHash = payloadHash, createdAt = Instant.now().toString()))
        }
    }

    private fun asDeferredUpdatePayload(payload: JsonObject): JsonObject = buildJsonObject {
        payload.forEach { (key, value) ->
            if (key !in setOf("public_id", "source", "base_revision")) put(key, value)
        }
        put("base_revision", 0)
    }

    private suspend fun deletePendingOrQueueDeleteLocked(scope: String, entityId: String, revision: Int, prefix: String) {
        val create = dao.pendingAction(scope, entityId, "${prefix}_create")
        if (revision == 0 && create != null && create.attemptCount == 0) {
            dao.deletePendingForEntity(scope, entityId)
            return
        }
        val payload = buildJsonObject { put("base_revision", revision) }
        val type = "${prefix}_delete"
        val hash = CanonicalJson.sha256(payload)
        val key = stableIdempotencyKey(scope, entityId, type, hash)
        if (dao.pendingByKey(scope, key) == null) {
            dao.insertPending(PendingActionEntity(accountScope = scope, actionType = type, entityId = entityId, idempotencyKey = key, payloadJson = payload.toString(), payloadHash = hash, createdAt = Instant.now().toString()))
        }
    }

    private suspend fun recalculateNutritionDayLocked(scope: String, date: LocalDate) {
        val items = dao.nutritionEntries(scope, date.toString())
        fun sum(selector: (NutritionEntryEntity) -> String?): String? = items.mapNotNull(selector)
            .mapNotNull(String::toBigDecimalOrNull).takeIf { it.isNotEmpty() }
            ?.fold(BigDecimal.ZERO, BigDecimal::add)?.stripTrailingZeros()?.toPlainString()
        dao.upsertNutritionDay(
            NutritionDayEntity(
                scope, date.toString(), sum { it.caloriesKcal }, sum { it.proteinG }, sum { it.fatG },
                sum { it.netCarbsG }, sum { it.totalCarbsG }, sum { it.fiberG }, sum { it.sugarG },
                sum { it.sodiumMg }, dao.nutritionDay(scope, date.toString())?.targetCaloriesKcal, Instant.now().toString(),
            ),
        )
    }

    private suspend fun recalculateDayForInstantLocked(scope: String, instant: String) {
        val zone = accountZone(scope)
        recalculateDayLocked(scope, Instant.parse(instant).atZone(zone).toLocalDate())
    }

    private suspend fun recalculateDayLocked(scope: String, date: LocalDate) {
        val zone = accountZone(scope)
        val end = date.plusDays(1).atStartOfDay(zone).toInstant()
        val body = dao.bodyStats(scope)
            .filter { runCatching { Instant.parse(it.recordedAt) < end }.getOrDefault(false) }
            .maxWithOrNull(
                compareBy<BodyStatEntity> { it.recordedAt }
                    .thenBy { if (it.source == "manual" || it.source == "user_override") 1 else 0 }
                    .thenBy { it.publicId },
            )
        val exact = body?.let { Instant.parse(it.recordedAt).atZone(zone).toLocalDate() == date } == true
        val nutrition = dao.nutritionDay(scope, date.toString())
        val steps = dao.dailyStepsForDate(scope, date.toString()).firstOrNull()
        val old = dao.dailyHealthSummary(scope, date.toString())
        val nutritionEntries = dao.nutritionEntries(scope, date.toString())
        val status = when {
            listOf(body?.syncStatus, steps?.syncStatus).any { it == "conflict" } -> "attention"
            listOf(body?.syncStatus, steps?.syncStatus).any { it == "syncing" } -> "syncing"
            listOf(body?.syncStatus, steps?.syncStatus).any { it == "pending" } || nutritionEntries.any { it.syncStatus == "pending" } -> "pending"
            else -> "synced"
        }
        val now = Instant.now().toString()
        dao.upsertDailyHealthSummary(
            DailyHealthSummaryEntity(
                scope, date.toString(), zone.id, body?.publicId, body?.weightKg, exact,
                nutrition?.caloriesKcal, nutrition?.proteinG, nutrition?.totalCarbsG ?: nutrition?.netCarbsG,
                nutrition?.fatG, nutrition?.fiberG, nutrition?.targetCaloriesKcal,
                steps?.publicId, steps?.steps, steps?.goal,
                old?.scheduledWorkouts ?: 0, old?.completedWorkouts ?: 0, status, now,
                body?.source, steps?.source,
            ),
        )
        dao.upsertHealthProgressPoints(
            listOf(
                HealthProgressPointEntity(
                    scope, date.toString(), if (exact) body.weightKg else null, steps?.steps,
                    nutrition?.caloriesKcal, nutrition?.proteinG, nutrition?.totalCarbsG ?: nutrition?.netCarbsG,
                    nutrition?.fatG, now, if (exact) body.source else null, steps?.source,
                ),
            ),
        )
    }

    private suspend fun accountZone(scope: String): ZoneId =
        runCatching { ZoneId.of(dao.account(scope)?.timezone ?: "UTC") }.getOrDefault(ZoneOffset.UTC)

    private suspend fun advanceTokenLocked(
        scope: String,
        type: HealthConnectRecordType,
        token: String,
        generation: Long,
        imported: Int,
        deleted: Int,
        marker: String,
    ) {
        val current = dao.healthConnectSyncState(scope, type.storageValue)
        dao.upsertHealthConnectSyncState(
            (current ?: emptySyncState(scope, type, generation)).copy(
                token = token,
                tokenCreatedAt = current?.tokenCreatedAt ?: marker,
                lastSuccessfulReadAt = marker,
                permissionGeneration = generation,
                state = "connected",
                lastImportedAt = if (imported + deleted > 0) marker else current?.lastImportedAt,
                importedCount = (current?.importedCount ?: 0) + imported,
                deletedCount = (current?.deletedCount ?: 0) + deleted,
                lastErrorCode = null,
            ),
        )
    }

    private fun emptySyncState(scope: String, type: HealthConnectRecordType, generation: Long) =
        HealthConnectSyncStateEntity(scope, type.storageValue, null, null, null, null, type.storageValue, generation, "idle", null, null, 0, 0, null)

    private fun HealthConnectRecord.toLedger(
        scope: String,
        type: HealthConnectRecordType,
        previous: HealthConnectRecordLedgerEntity?,
        resourceId: String?,
        marker: String,
        state: String,
        fingerprint: String,
    ) = HealthConnectRecordLedgerEntity(
        accountScope = scope,
        recordType = type.storageValue,
        healthConnectRecordId = metadata.id,
        clientRecordId = metadata.clientRecordId,
        dataOrigin = metadata.dataOrigin,
        localResourceUuid = resourceId,
        serverResourceUuid = resourceId,
        lastModifiedTime = metadata.lastModifiedTime.toString(),
        clientRecordVersion = metadata.clientRecordVersion,
        contentFingerprint = fingerprint,
        importedAt = previous?.importedAt ?: marker,
        lastSeenAt = marker,
        state = state,
        detachedByUser = previous?.detachedByUser ?: false,
        deletedAt = null,
        sourceStartTime = startTime.toString(),
        sourceEndTime = endTime?.toString(),
    )

    private fun fingerprint(record: HealthConnectRecord): String = sha256(
        when (record) {
            is HealthConnectWeight -> "weight|${record.startTime}|${record.kilograms}|${record.zoneOffset.orEmpty()}"
            is HealthConnectBodyFat -> "fat|${record.startTime}|${record.percentage}|${record.zoneOffset.orEmpty()}"
            is HealthConnectLeanBodyMass -> "lean|${record.startTime}|${record.kilograms}|${record.zoneOffset.orEmpty()}"
            is HealthConnectBodyWaterMass -> "water|${record.startTime}|${record.kilograms}|${record.zoneOffset.orEmpty()}"
            is HealthConnectNutrition -> listOf(
                "nutrition", record.startTime, record.endTime, record.zoneOffset, record.mealType, record.name,
                record.caloriesKcal, record.proteinGrams, record.fatGrams, record.carbohydrateGrams,
                record.fiberGrams, record.sugarGrams, record.sodiumMilligrams,
            ).joinToString("|")
        },
    )

    companion object {
        fun encodeTypes(types: Set<HealthConnectRecordType>): String = types.sortedBy { it.ordinal }.joinToString(",") { it.storageValue }
        fun decodeTypes(value: String): Set<HealthConnectRecordType> = value.split(',').mapNotNull(HealthConnectRecordType::fromStorage).toSet()
        fun stepLogicalId(date: String, zoneId: String): String = "aggregate:${sha256("$date|$zoneId").take(24)}"
        private fun stableIdempotencyKey(scope: String, entity: String, action: String, hash: String): String =
            UUID.nameUUIDFromBytes("$scope|$entity|$action|$hash".toByteArray(StandardCharsets.UTF_8)).toString()
        private fun decimal(value: Double, scale: Int): String = BigDecimal.valueOf(value).setScale(scale, RoundingMode.HALF_UP).stripTrailingZeros().toPlainString()
        private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
            .digest(value.toByteArray(StandardCharsets.UTF_8)).joinToString("") { "%02x".format(it) }
        private fun HealthConnectAvailability.storageValue(): String = name.lowercase()
    }
}
