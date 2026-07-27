package io.healthtracker.companion.core.healthconnect

import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class HealthConnectSyncCoordinator(
    private val gateway: HealthConnectGateway,
    private val store: HealthConnectSyncStorage,
    private val accountZone: suspend (String) -> ZoneId,
    private val onServerQueueReady: () -> Unit,
    private val clock: Clock = Clock.systemUTC(),
) {
    private val mutex = Mutex()

    suspend fun sync(accountScope: String, foreground: Boolean): HealthConnectImportResult = mutex.withLock {
        val availability = gateway.availability()
        store.updateAvailability(accountScope, availability)
        if (availability != HealthConnectAvailability.AVAILABLE) return HealthConnectImportResult()
        val settings = store.ensureSettings(accountScope, availability)
        if (!settings.enabled || settings.paused) return HealthConnectImportResult()

        val selected = HealthConnectStore.decodeTypes(settings.selectedTypes)
        val grantedPermissions = gateway.grantedPermissions()
        val grantedTypes = selected.filterTo(mutableSetOf()) { type ->
            gateway.permissionsFor(setOf(type)).all { it in grantedPermissions }
        }
        val backgroundPermission = gateway.permissionsFor(emptySet(), includeBackground = true).firstOrNull()
        val backgroundGranted = gateway.backgroundReadAvailable() && backgroundPermission != null && backgroundPermission in grantedPermissions
        val permissionUpdate = store.persistPermissions(accountScope, selected, grantedTypes, backgroundGranted)
        if (!foreground && !backgroundGranted) return HealthConnectImportResult()

        val now = clock.instant()
        val zone = runCatching { accountZone(accountScope) }.getOrDefault(ZoneOffset.UTC)
        var total = HealthConnectImportResult()
        selected.sortedBy { it.ordinal }.forEach { type ->
            if (!type.importSupported || type !in grantedTypes) return@forEach
            try {
                store.markSyncing(accountScope, type, permissionUpdate.generation, now)
                val result = synchronizeType(accountScope, type, settings.initialLookbackDays, zone, permissionUpdate.generation, now)
                total += result
            } catch (failure: HealthConnectGatewayException) {
                store.markError(accountScope, type, permissionUpdate.generation, failure.sanitizedCode)
                if (failure.sanitizedCode == "permission_revoked") {
                    val current = gateway.grantedPermissions()
                    val stillGranted = selected.filterTo(mutableSetOf()) { selectedType ->
                        gateway.permissionsFor(setOf(selectedType)).all { it in current }
                    }
                    store.persistPermissions(accountScope, selected, stillGranted, backgroundGranted)
                }
            }
        }
        if (total.imported + total.deleted > 0) onServerQueueReady()
        total
    }

    private suspend fun synchronizeType(
        scope: String,
        type: HealthConnectRecordType,
        lookbackDays: Int,
        zone: ZoneId,
        generation: Long,
        now: Instant,
    ): HealthConnectImportResult {
        val state = store.syncState(scope, type)
        val token = state?.token?.takeIf { state.permissionGeneration == generation }
        return if (token == null) {
            fullReconciliation(scope, type, lookbackDays, zone, generation, now)
        } else {
            incremental(scope, type, token, lookbackDays, zone, generation, now)
        }
    }

    private suspend fun fullReconciliation(
        scope: String,
        type: HealthConnectRecordType,
        lookbackDays: Int,
        zone: ZoneId,
        generation: Long,
        now: Instant,
    ): HealthConnectImportResult {
        val safeDays = lookbackDays.coerceIn(1, 30)
        val marker = now.toString()
        val startDate = now.atZone(zone).toLocalDate().minusDays((safeDays - 1).toLong())
        val start = startDate.atStartOfDay(zone).toInstant()
        var result = HealthConnectImportResult()
        if (type == HealthConnectRecordType.STEPS) {
            result += store.applyStepAggregates(
                scope,
                gateway.aggregateDailySteps(startDate.toString(), now.atZone(zone).toLocalDate().plusDays(1).toString(), zone),
                zone,
                marker,
                generation,
            )
        } else {
            var pageToken: String? = null
            var pages = 0
            do {
                val page = gateway.readPage(type, start, now, pageToken)
                result += store.applyRecords(scope, type, page.records, marker, generation)
                pageToken = page.nextPageToken
                pages++
            } while (pageToken != null && pages < MAX_PAGES)
            if (pageToken != null) throw HealthConnectGatewayException("page_limit", retryable = true)
        }
        val newToken = gateway.changesToken(type)
        result += store.completeFullReconciliation(scope, type, start, marker, newToken, generation)
        return result
    }

    private suspend fun incremental(
        scope: String,
        type: HealthConnectRecordType,
        initialToken: String,
        lookbackDays: Int,
        zone: ZoneId,
        generation: Long,
        now: Instant,
    ): HealthConnectImportResult {
        var token = initialToken
        var pages = 0
        var result = HealthConnectImportResult()
        var stepToken: String? = null
        var stepChanged = false
        do {
            val page = gateway.changes(token)
            if (page.tokenExpired) return fullReconciliation(scope, type, lookbackDays, zone, generation, now)
            if (type == HealthConnectRecordType.STEPS) {
                stepToken = page.nextToken
                stepChanged = stepChanged || page.changes.isNotEmpty()
            } else {
                result += store.applyChanges(scope, type, page.changes, page.nextToken, now.toString(), generation)
            }
            token = page.nextToken
            pages++
            if (!page.hasMore) break
        } while (pages < MAX_PAGES)
        if (pages >= MAX_PAGES) throw HealthConnectGatewayException("page_limit", retryable = true)
        if (type == HealthConnectRecordType.STEPS && stepToken != null) {
            val fallback = now.atZone(zone).toLocalDate().minusDays((lookbackDays.coerceIn(1, 30) - 1).toLong())
            result += store.applyStepAggregates(
                scope,
                if (stepChanged) {
                    gateway.aggregateDailySteps(
                        fallback.toString(),
                        now.atZone(zone).toLocalDate().plusDays(1).toString(),
                        zone,
                    )
                } else {
                    emptyList()
                },
                zone,
                now.toString(),
                generation,
                stepToken,
            )
        }
        return result
    }

    private operator fun HealthConnectImportResult.plus(other: HealthConnectImportResult) = HealthConnectImportResult(
        imported + other.imported,
        deleted + other.deleted,
        skipped + other.skipped,
    )

    private companion object { const val MAX_PAGES = 100 }
}
