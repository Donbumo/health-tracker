package io.healthtracker.companion.core.healthconnect

import android.content.Context
import android.content.Intent
import androidx.activity.result.contract.ActivityResultContract
import io.healthtracker.companion.core.database.HealthConnectSettingsEntity
import io.healthtracker.companion.core.database.HealthConnectSyncStateEntity
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HealthConnectSyncCoordinatorTest {
    private val now = Instant.parse("2026-07-26T12:00:00Z")
    private val clock = Clock.fixed(now, ZoneOffset.UTC)

    @Test fun healthConnectUnavailableDoesNothing() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.gateway.availability = HealthConnectAvailability.UNAVAILABLE_PROVIDER
        fixture.coordinator.sync(SCOPE, true)
        assertEquals(0, fixture.gateway.readCalls)
    }

    @Test fun providerUpdateRequiredDoesNothing() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.gateway.availability = HealthConnectAvailability.UPDATE_REQUIRED
        fixture.coordinator.sync(SCOPE, true)
        assertEquals(0, fixture.gateway.readCalls)
    }

    @Test fun partialPermissionsImportOnlyGrantedTypes() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT, HealthConnectRecordType.BODY_FAT)
        fixture.gateway.granted = setOf("read:weight")
        fixture.gateway.pages[HealthConnectRecordType.WEIGHT] = listOf(weight("w1"))
        fixture.coordinator.sync(SCOPE, true)
        assertEquals(listOf(HealthConnectRecordType.WEIGHT), fixture.gateway.readTypes)
    }

    @Test fun revokedPermissionDuringImportIsSanitized() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.gateway.readFailure = HealthConnectGatewayException("permission_revoked", false)
        fixture.coordinator.sync(SCOPE, true)
        assertEquals("permission_revoked", fixture.store.errors[HealthConnectRecordType.WEIGHT])
    }

    @Test fun firstWeightImportPersistsLocally() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.gateway.pages[HealthConnectRecordType.WEIGHT] = listOf(weight("w1"))
        assertEquals(1, fixture.coordinator.sync(SCOPE, true).imported)
        assertTrue(fixture.store.records.containsKey("$SCOPE:weight:w1"))
    }

    @Test fun repeatedWeightDoesNotDuplicate() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.gateway.pages[HealthConnectRecordType.WEIGHT] = listOf(weight("w1"))
        fixture.coordinator.sync(SCOPE, true)
        fixture.store.states.clear()
        fixture.coordinator.sync(SCOPE, true)
        assertEquals(1, fixture.store.records.size)
    }

    @Test fun updatedWeightKeepsStableLocalUuid() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.gateway.pages[HealthConnectRecordType.WEIGHT] = listOf(weight("w1", 70.0))
        fixture.coordinator.sync(SCOPE, true)
        val first = fixture.store.localIds.getValue("$SCOPE:weight:w1")
        fixture.store.states.clear()
        fixture.gateway.pages[HealthConnectRecordType.WEIGHT] = listOf(weight("w1", 71.0))
        fixture.coordinator.sync(SCOPE, true)
        assertEquals(first, fixture.store.localIds.getValue("$SCOPE:weight:w1"))
    }

    @Test fun bodyFatValidAndInvalidAreDistinguished() = runTest {
        val fixture = fixture(HealthConnectRecordType.BODY_FAT)
        fixture.gateway.pages[HealthConnectRecordType.BODY_FAT] = listOf(bodyFat("f1", 20.0), bodyFat("f2", 101.0))
        val result = fixture.coordinator.sync(SCOPE, true)
        assertEquals(1, result.imported)
        assertEquals(1, result.skipped)
    }

    @Test fun leanBodyMassNeverMapsToMuscleMass() = runTest {
        val fixture = fixture(HealthConnectRecordType.LEAN_BODY_MASS)
        fixture.coordinator.sync(SCOPE, true)
        assertFalse(HealthConnectRecordType.LEAN_BODY_MASS.importSupported)
        assertEquals(0, fixture.gateway.readCalls)
    }

    @Test fun stepsUseAggregateInsteadOfRawRead() = runTest {
        val fixture = fixture(HealthConnectRecordType.STEPS)
        fixture.gateway.aggregates = listOf(DailyStepsAggregate("2026-07-26", 7000))
        fixture.coordinator.sync(SCOPE, true)
        assertEquals(1, fixture.gateway.aggregateCalls)
        assertEquals(0, fixture.gateway.readCalls)
    }

    @Test fun multipleStepOriginsStillProduceOneDailyTotal() = runTest {
        val fixture = fixture(HealthConnectRecordType.STEPS)
        fixture.gateway.aggregates = listOf(DailyStepsAggregate("2026-07-26", 7000))
        fixture.coordinator.sync(SCOPE, true)
        assertEquals(1, fixture.store.steps.size)
        assertEquals(7000L, fixture.store.steps["$SCOPE:2026-07-26"])
    }

    @Test fun syntheticDataOriginIsKeptOpaque() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.gateway.pages[HealthConnectRecordType.WEIGHT] = listOf(weight("w1", origin = "opaque.synthetic.origin"))
        fixture.coordinator.sync(SCOPE, true)
        assertEquals("opaque.synthetic.origin", fixture.store.origins["$SCOPE:weight:w1"])
    }

    @Test fun dayAggregationUsesAccountTimezone() = runTest {
        val fixture = fixture(HealthConnectRecordType.STEPS, zone = ZoneId.of("America/Mexico_City"))
        fixture.gateway.aggregates = listOf(DailyStepsAggregate("2026-07-26", 1))
        fixture.coordinator.sync(SCOPE, true)
        assertEquals("America/Mexico_City", fixture.gateway.lastZone?.id)
    }

    @Test fun incompleteNutritionIsSkippedWithoutInventingName() = runTest {
        val fixture = fixture(HealthConnectRecordType.NUTRITION)
        fixture.gateway.pages[HealthConnectRecordType.NUTRITION] = listOf(nutrition("n1", name = null))
        assertEquals(1, fixture.coordinator.sync(SCOPE, true).skipped)
    }

    @Test fun repeatedNutritionRecordIsDeduplicated() = runTest {
        val fixture = fixture(HealthConnectRecordType.NUTRITION)
        fixture.gateway.pages[HealthConnectRecordType.NUTRITION] = listOf(nutrition("n1"), nutrition("n1"))
        fixture.coordinator.sync(SCOPE, true)
        assertEquals(1, fixture.store.records.size)
    }

    @Test fun normalChangesTokenAdvancesAfterPersistence() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.store.seedState(HealthConnectRecordType.WEIGHT, "old")
        fixture.gateway.changePages["old"] = HealthConnectChangesPage(listOf(HealthConnectChange.Upsert(weight("w1"))), "next", false, false)
        fixture.coordinator.sync(SCOPE, true)
        assertEquals("next", fixture.store.states.getValue(HealthConnectRecordType.WEIGHT).token)
    }

    @Test fun expiredTokenTriggersFullReconciliation() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.store.seedState(HealthConnectRecordType.WEIGHT, "expired")
        fixture.gateway.changePages["expired"] = HealthConnectChangesPage(emptyList(), "ignored", false, true)
        fixture.gateway.pages[HealthConnectRecordType.WEIGHT] = listOf(weight("w1"))
        fixture.coordinator.sync(SCOPE, true)
        assertEquals(1, fixture.gateway.readCalls)
        assertEquals("token-weight", fixture.store.states.getValue(HealthConnectRecordType.WEIGHT).token)
    }

    @Test fun expiredTokenRereadsAtMostThirtyDaysWithDedupe() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.store.seedState(HealthConnectRecordType.WEIGHT, "expired")
        fixture.gateway.changePages["expired"] = HealthConnectChangesPage(emptyList(), "ignored", false, true)
        fixture.gateway.pages[HealthConnectRecordType.WEIGHT] = listOf(weight("w1"), weight("w1"))
        fixture.coordinator.sync(SCOPE, true)
        assertEquals(Instant.parse("2026-06-27T00:00:00Z"), fixture.gateway.lastReadStart)
        assertEquals(1, fixture.store.records.size)
    }

    @Test fun remoteDeletionRemovesImportedRecord() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.store.records["$SCOPE:weight:w1"] = weight("w1")
        fixture.store.seedState(HealthConnectRecordType.WEIGHT, "old")
        fixture.gateway.changePages["old"] = HealthConnectChangesPage(listOf(HealthConnectChange.Delete("w1")), "next", false, false)
        fixture.coordinator.sync(SCOPE, true)
        assertFalse(fixture.store.records.containsKey("$SCOPE:weight:w1"))
    }

    @Test fun detachedRecordSurvivesRemoteDeletion() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.store.records["$SCOPE:weight:w1"] = weight("w1")
        fixture.store.detached += "$SCOPE:weight:w1"
        fixture.store.seedState(HealthConnectRecordType.WEIGHT, "old")
        fixture.gateway.changePages["old"] = HealthConnectChangesPage(listOf(HealthConnectChange.Delete("w1")), "next", false, false)
        fixture.coordinator.sync(SCOPE, true)
        assertTrue(fixture.store.records.containsKey("$SCOPE:weight:w1"))
    }

    @Test fun transactionFailureDoesNotAdvanceToken() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.store.seedState(HealthConnectRecordType.WEIGHT, "old")
        fixture.store.failApply = true
        fixture.gateway.changePages["old"] = HealthConnectChangesPage(listOf(HealthConnectChange.Upsert(weight("w1"))), "next", false, false)
        runCatching { fixture.coordinator.sync(SCOPE, true) }
        assertEquals("old", fixture.store.states.getValue(HealthConnectRecordType.WEIGHT).token)
    }

    @Test fun processDeathResumesFromPersistedToken() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.store.seedState(HealthConnectRecordType.WEIGHT, "persisted")
        fixture.gateway.changePages["persisted"] = HealthConnectChangesPage(emptyList(), "next", false, false)
        newCoordinator(fixture).sync(SCOPE, true)
        assertEquals(0, fixture.gateway.readCalls)
        assertEquals("next", fixture.store.states.getValue(HealthConnectRecordType.WEIGHT).token)
    }

    @Test fun accountScopesNeverShareLedger() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.gateway.pages[HealthConnectRecordType.WEIGHT] = listOf(weight("w1"))
        fixture.coordinator.sync(SCOPE, true)
        fixture.store.states.clear()
        fixture.coordinator.sync("other-scope", true)
        assertNotEquals(fixture.store.localIds["$SCOPE:weight:w1"], fixture.store.localIds["other-scope:weight:w1"])
    }

    @Test fun workerAndManualSyncAreSingleFlight() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.gateway.delayReads = true
        fixture.gateway.pages[HealthConnectRecordType.WEIGHT] = listOf(weight("w1"))
        val first = async { fixture.coordinator.sync(SCOPE, true) }
        val second = async { fixture.coordinator.sync(SCOPE, true) }
        first.await(); second.await()
        assertEquals(1, fixture.gateway.maxConcurrentReads)
    }

    @Test fun missingBackgroundPermissionFallsBackToForegroundOnly() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.coordinator.sync(SCOPE, false)
        assertEquals(0, fixture.gateway.readCalls)
        fixture.gateway.pages[HealthConnectRecordType.WEIGHT] = listOf(weight("w1"))
        fixture.coordinator.sync(SCOPE, true)
        assertEquals(1, fixture.gateway.readCalls)
    }

    @Test fun pausedIntegrationDoesNotRead() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT, paused = true)
        fixture.coordinator.sync(SCOPE, true)
        assertEquals(0, fixture.gateway.readCalls)
    }

    @Test fun disconnectedIntegrationDoesNotReadOrRevoke() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT, enabled = false)
        fixture.coordinator.sync(SCOPE, true)
        assertEquals(0, fixture.gateway.readCalls)
        assertEquals(0, fixture.gateway.revokeCalls)
    }

    @Test fun selectiveDeletePreservesManualAndDetachedCopies() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.store.records["$SCOPE:weight:imported"] = weight("imported")
        fixture.store.manual += "$SCOPE:manual"
        fixture.store.detached += "$SCOPE:weight:imported"
        fixture.store.deleteImported(SCOPE)
        assertTrue("$SCOPE:manual" in fixture.store.manual)
        assertTrue(fixture.store.records.containsKey("$SCOPE:weight:imported"))
    }

    @Test fun importedChangesTriggerServerQueueOnce() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.gateway.pages[HealthConnectRecordType.WEIGHT] = listOf(weight("w1"))
        fixture.coordinator.sync(SCOPE, true)
        assertEquals(1, fixture.serverQueueCalls())
    }

    @Test fun todayAndProgressCanObserveLocalApplyImmediately() = runTest {
        val fixture = fixture(HealthConnectRecordType.STEPS)
        fixture.gateway.aggregates = listOf(DailyStepsAggregate("2026-07-26", 4321))
        fixture.coordinator.sync(SCOPE, true)
        assertEquals(4321L, fixture.store.steps["$SCOPE:2026-07-26"])
    }

    @Test fun observingStateDoesNotFetchAgain() = runTest {
        val fixture = fixture(HealthConnectRecordType.WEIGHT)
        fixture.gateway.pages[HealthConnectRecordType.WEIGHT] = listOf(weight("w1"))
        fixture.coordinator.sync(SCOPE, true)
        val calls = fixture.gateway.readCalls
        repeat(5) { fixture.store.states[HealthConnectRecordType.WEIGHT] }
        assertEquals(calls, fixture.gateway.readCalls)
    }

    private fun fixture(
        vararg types: HealthConnectRecordType,
        zone: ZoneId = ZoneOffset.UTC,
        paused: Boolean = false,
        enabled: Boolean = true,
    ): Fixture {
        val gateway = FakeGateway().apply {
            granted = types.mapTo(mutableSetOf()) { "read:${it.storageValue}" }
        }
        val store = FakeStore(types.toSet(), paused, enabled)
        var serverQueue = 0
        val coordinator = HealthConnectSyncCoordinator(gateway, store, { zone }, { serverQueue++ }, clock)
        return Fixture(gateway, store, coordinator) { serverQueue }
    }

    private fun newCoordinator(fixture: Fixture) = HealthConnectSyncCoordinator(
        fixture.gateway, fixture.store, { ZoneOffset.UTC }, {}, clock,
    )

    private fun weight(id: String, kg: Double = 70.0, origin: String = "qa.origin") = HealthConnectWeight(
        metadata(id, origin), Instant.parse("2026-07-26T08:00:00Z"), "Z", kg,
    )

    private fun bodyFat(id: String, percent: Double) = HealthConnectBodyFat(
        metadata(id), Instant.parse("2026-07-26T08:00:00Z"), "Z", percent,
    )

    private fun nutrition(id: String, name: String? = "Avena QA") = HealthConnectNutrition(
        metadata(id), Instant.parse("2026-07-26T08:00:00Z"), Instant.parse("2026-07-26T08:15:00Z"),
        "Z", "Z", "breakfast", name, 300.0, 12.0, 7.0, 48.0, 6.0, null, null,
    )

    private fun metadata(id: String, origin: String = "qa.origin") = HealthConnectMetadata(
        id, null, null, origin, now,
    )

    private data class Fixture(
        val gateway: FakeGateway,
        val store: FakeStore,
        val coordinator: HealthConnectSyncCoordinator,
        val serverQueueCalls: () -> Int,
    )

    private class FakeGateway : HealthConnectGateway {
        var availability = HealthConnectAvailability.AVAILABLE
        var granted: Set<String> = emptySet()
        var aggregates: List<DailyStepsAggregate> = emptyList()
        val pages = mutableMapOf<HealthConnectRecordType, List<HealthConnectRecord>>()
        val changePages = mutableMapOf<String, HealthConnectChangesPage>()
        val readTypes = mutableListOf<HealthConnectRecordType>()
        var readCalls = 0
        var aggregateCalls = 0
        var revokeCalls = 0
        var readFailure: HealthConnectGatewayException? = null
        var lastReadStart: Instant? = null
        var lastZone: ZoneId? = null
        var delayReads = false
        var concurrentReads = 0
        var maxConcurrentReads = 0

        override fun availability() = availability
        override fun permissionRequestContract() = object : ActivityResultContract<Set<String>, Set<String>>() {
            override fun createIntent(context: Context, input: Set<String>) = Intent()
            override fun parseResult(resultCode: Int, intent: Intent?) = emptySet<String>()
        }
        override fun permissionsFor(types: Set<HealthConnectRecordType>, includeBackground: Boolean) = buildSet {
            types.forEach { add("read:${it.storageValue}") }
            if (includeBackground) add("read:background")
        }
        override suspend fun grantedPermissions() = granted
        override fun manageAccessIntent() = Intent()
        override fun providerIntent() = Intent()
        override fun backgroundReadAvailable() = true
        override suspend fun readPage(type: HealthConnectRecordType, start: Instant, end: Instant, pageToken: String?): HealthConnectPage {
            readFailure?.let { throw it }
            readCalls++; readTypes += type; lastReadStart = start
            concurrentReads++; maxConcurrentReads = maxOf(maxConcurrentReads, concurrentReads)
            if (delayReads) delay(10)
            concurrentReads--
            return HealthConnectPage(pages[type].orEmpty(), null)
        }
        override suspend fun aggregateDailySteps(startDate: String, endDateExclusive: String, zoneId: ZoneId): List<DailyStepsAggregate> {
            aggregateCalls++; lastZone = zoneId
            return aggregates
        }
        override suspend fun changesToken(type: HealthConnectRecordType) = "token-${type.storageValue}"
        override suspend fun changes(token: String) = changePages[token] ?: HealthConnectChangesPage(emptyList(), "$token-next", false, false)
    }

    private inner class FakeStore(
        types: Set<HealthConnectRecordType>,
        paused: Boolean,
        enabled: Boolean,
    ) : HealthConnectSyncStorage {
        private val settings = mutableMapOf<String, HealthConnectSettingsEntity>()
        val states = mutableMapOf<HealthConnectRecordType, HealthConnectSyncStateEntity>()
        val records = mutableMapOf<String, HealthConnectRecord>()
        val localIds = mutableMapOf<String, String>()
        val origins = mutableMapOf<String, String>()
        val steps = mutableMapOf<String, Long?>()
        val detached = mutableSetOf<String>()
        val manual = mutableSetOf<String>()
        val errors = mutableMapOf<HealthConnectRecordType, String>()
        var failApply = false
        private val selected = types
        private val defaultPaused = paused
        private val defaultEnabled = enabled

        override suspend fun ensureSettings(scope: String, availability: HealthConnectAvailability) = settings.getOrPut(scope) {
            HealthConnectSettingsEntity(scope, defaultEnabled, defaultPaused, HealthConnectStore.encodeTypes(selected), 30, 0, availability.name.lowercase(), now.toString())
        }
        override suspend fun updateAvailability(scope: String, availability: HealthConnectAvailability) { ensureSettings(scope, availability) }
        override suspend fun persistPermissions(scope: String, selected: Set<HealthConnectRecordType>, granted: Set<HealthConnectRecordType>, backgroundGranted: Boolean) = HealthConnectPermissionUpdate(0, emptySet())
        override suspend fun syncState(scope: String, type: HealthConnectRecordType) = states[type]
        override suspend fun markSyncing(scope: String, type: HealthConnectRecordType, generation: Long, now: Instant) = Unit
        override suspend fun markError(scope: String, type: HealthConnectRecordType, generation: Long, code: String) { errors[type] = code }
        override suspend fun applyRecords(scope: String, type: HealthConnectRecordType, records: List<HealthConnectRecord>, runMarker: String, generation: Long, nextToken: String?): HealthConnectImportResult {
            if (failApply) error("transaction_failed")
            var imported = 0; var skipped = 0
            records.forEach { record ->
                if (record is HealthConnectBodyFat && record.percentage !in 0.0..100.0 || record is HealthConnectNutrition && record.name == null) { skipped++; return@forEach }
                val key = "$scope:${type.storageValue}:${record.metadata.id}"
                val changed = recordsFingerprint(records = record) != recordsFingerprint(records = this.records[key])
                if (changed) imported++
                this.records[key] = record
                localIds.putIfAbsent(key, java.util.UUID.randomUUID().toString())
                origins[key] = record.metadata.dataOrigin
            }
            nextToken?.let { seedState(type, it) }
            return HealthConnectImportResult(imported, skipped = skipped)
        }
        override suspend fun applyChanges(scope: String, type: HealthConnectRecordType, changes: List<HealthConnectChange>, nextToken: String, runMarker: String, generation: Long): HealthConnectImportResult {
            if (failApply) error("transaction_failed")
            var imported = 0; var deletedCount = 0
            changes.forEach { change -> when (change) {
                is HealthConnectChange.Upsert -> {
                    val key = "$scope:${type.storageValue}:${change.record.metadata.id}"
                    records[key] = change.record; localIds.putIfAbsent(key, java.util.UUID.randomUUID().toString()); imported++
                }
                is HealthConnectChange.Delete -> {
                    val key = "$scope:${type.storageValue}:${change.recordId}"
                    if (key !in detached && records.remove(key) != null) deletedCount++
                }
            } }
            seedState(type, nextToken)
            return HealthConnectImportResult(imported, deletedCount)
        }
        override suspend fun applyStepAggregates(scope: String, values: List<DailyStepsAggregate>, zoneId: ZoneId, runMarker: String, generation: Long, nextToken: String?): HealthConnectImportResult {
            values.forEach { steps["$scope:${it.date}"] = it.steps }
            nextToken?.let { seedState(HealthConnectRecordType.STEPS, it) }
            return HealthConnectImportResult(imported = values.count { it.steps != null })
        }
        override suspend fun completeFullReconciliation(scope: String, type: HealthConnectRecordType, windowStart: Instant, runMarker: String, token: String, generation: Long): HealthConnectImportResult {
            seedState(type, token)
            return HealthConnectImportResult()
        }
        fun seedState(type: HealthConnectRecordType, token: String) {
            states[type] = HealthConnectSyncStateEntity(SCOPE, type.storageValue, token, now.toString(), now.toString(), null, type.storageValue, 0, "connected", now.toString(), now.toString(), 0, 0, null)
        }
        fun deleteImported(scope: String) {
            records.keys.filter { it.startsWith("$scope:") && it !in detached }.forEach(records::remove)
        }
        private fun recordsFingerprint(records: HealthConnectRecord?) = records?.toString()
    }

    private companion object { const val SCOPE = "account-scope-qa" }
}
