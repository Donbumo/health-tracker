package io.healthtracker.companion.core.healthconnect

import android.content.Context
import android.content.Intent
import androidx.activity.result.contract.ActivityResultContract
import java.time.Instant
import java.time.ZoneId
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HealthConnectScaleDiagnosticTest {
    private val now = Instant.parse("2026-07-28T12:00:00Z")

    @Test fun unavailableHealthConnectReturnsHumanState() = runTest {
        val fixture = fixture().apply { gateway.available = HealthConnectAvailability.UNAVAILABLE_PROVIDER }
        assertEquals(ScaleDiagnosticStatus.HEALTH_CONNECT_UNAVAILABLE, fixture.service.inspect("scope", now).status)
    }

    @Test fun missingBodyPermissionDoesNotReadAnyRecords() = runTest {
        val fixture = fixture(granted = setOf("read:weight"))
        val result = fixture.service.inspect("scope", now)
        assertEquals(ScaleDiagnosticStatus.PERMISSION_REQUIRED, result.status)
        assertEquals(setOf("body_fat"), result.missingPermissions)
        assertEquals(0, fixture.gateway.readCalls)
    }

    @Test fun noCompatibleDataIsReported() = runTest {
        val result = fixture().service.inspect("scope", now)
        assertEquals(ScaleDiagnosticStatus.NO_COMPATIBLE_MEASUREMENTS, result.status)
    }

    @Test fun weightWithoutFatIsReportedWithoutValue() = runTest {
        val fixture = fixture()
        fixture.gateway.records[HealthConnectRecordType.WEIGHT] = listOf(weight("record-private", 73.125, "private.package"))
        val result = fixture.service.inspect("scope", now)
        assertEquals(ScaleDiagnosticStatus.WEIGHT_FOUND, result.status)
        assertEquals(setOf("weight"), result.foundTypes)
        assertFalse(result.toString().contains("73.125"))
        assertFalse(result.toString().contains("record-private"))
        assertFalse(result.toString().contains("private.package"))
        assertTrue(ScaleDiagnosticStatus.ORIGIN_UNCERTAIN in result.notices)
    }

    @Test fun weightAndFatAreReportedAsTypesOnly() = runTest {
        val fixture = fixture()
        fixture.gateway.records[HealthConnectRecordType.WEIGHT] = listOf(weight("w1", 70.0, "origin.one"))
        fixture.gateway.records[HealthConnectRecordType.BODY_FAT] = listOf(bodyFat("f1", 20.0, "origin.one"))
        val result = fixture.service.inspect("scope", now)
        assertEquals(ScaleDiagnosticStatus.WEIGHT_AND_BODY_FAT_FOUND, result.status)
        assertTrue(result.humanSummary().contains("peso y grasa corporal"))
        assertEquals(2, result.recordCount)
    }

    @Test fun multipleOriginsRemainGenericAndDistinct() = runTest {
        val fixture = fixture()
        fixture.gateway.records[HealthConnectRecordType.WEIGHT] = listOf(
            weight("w1", 70.0, "origin.one"),
            weight("w2", 71.0, "origin.two"),
        )
        val result = fixture.service.inspect("scope", now)
        assertEquals(ScaleDiagnosticStatus.MULTIPLE_ORIGINS, result.status)
        assertEquals(2, result.originCount)
        assertTrue(result.origins.all { it.safeLabel == "Aplicación de salud" })
        assertEquals(2, fixture.observedOrigins.size)
    }

    @Test fun importedAndNotImportedCountsUseLedgerIdentity() = runTest {
        val fixture = fixture(importedIds = setOf("w1"))
        fixture.gateway.records[HealthConnectRecordType.WEIGHT] = listOf(weight("w1"), weight("w2"))
        val result = fixture.service.inspect("scope", now)
        assertEquals(1, result.importedCount)
        assertEquals(1, result.notImportedCount)
    }

    @Test fun allImportedAddsAlreadyImportedNotice() = runTest {
        val fixture = fixture(importedIds = setOf("w1"))
        fixture.gateway.records[HealthConnectRecordType.WEIGHT] = listOf(weight("w1"))
        val result = fixture.service.inspect("scope", now)
        assertEquals(ScaleDiagnosticStatus.ALREADY_IMPORTED, result.status)
        assertTrue(result.humanSummary().contains("ya están importados"))
    }

    @Test fun providerFailureIsSanitized() = runTest {
        val fixture = fixture()
        fixture.gateway.failure = IllegalArgumentException("private.package record=70.0")
        val result = fixture.service.inspect("scope", now)
        assertEquals("provider_error", result.errorCode)
        assertFalse(result.toString().contains("private.package"))
    }

    private fun fixture(
        granted: Set<String> = setOf("read:weight", "read:body_fat"),
        importedIds: Set<String> = emptySet(),
    ): Fixture {
        val gateway = FakeGateway().apply { this.granted = granted }
        val observed = mutableListOf<String>()
        val service = HealthConnectScaleDiagnosticService(
            gateway,
            { _, _, id -> id in importedIds },
            { _, origin -> observed += origin },
        )
        return Fixture(gateway, service, observed)
    }

    private fun weight(id: String, kg: Double = 70.0, origin: String = "fixture.origin") = HealthConnectWeight(
        metadata(id, origin), now.minusSeconds(60), "Z", kg,
    )

    private fun bodyFat(id: String, value: Double, origin: String) = HealthConnectBodyFat(
        metadata(id, origin), now.minusSeconds(60), "Z", value,
    )

    private fun metadata(id: String, origin: String) = HealthConnectMetadata(id, null, null, origin, now)

    private data class Fixture(
        val gateway: FakeGateway,
        val service: HealthConnectScaleDiagnosticService,
        val observedOrigins: MutableList<String>,
    )

    private class FakeGateway : HealthConnectGateway {
        var available = HealthConnectAvailability.AVAILABLE
        var granted = setOf("read:weight", "read:body_fat")
        var failure: Exception? = null
        var readCalls = 0
        val records = mutableMapOf<HealthConnectRecordType, List<HealthConnectRecord>>()
        override fun availability() = available
        override fun permissionRequestContract() = object : ActivityResultContract<Set<String>, Set<String>>() {
            override fun createIntent(context: Context, input: Set<String>) = Intent()
            override fun parseResult(resultCode: Int, intent: Intent?) = emptySet<String>()
        }
        override fun permissionsFor(types: Set<HealthConnectRecordType>, includeBackground: Boolean) = types.mapTo(mutableSetOf()) { "read:${it.storageValue}" }
        override suspend fun grantedPermissions() = granted
        override fun manageAccessIntent() = Intent()
        override fun providerIntent() = Intent()
        override fun backgroundReadAvailable() = false
        override suspend fun readPage(type: HealthConnectRecordType, start: Instant, end: Instant, pageToken: String?): HealthConnectPage {
            readCalls++
            failure?.let { throw it }
            return HealthConnectPage(records[type].orEmpty(), null)
        }
        override suspend fun aggregateDailySteps(startDate: String, endDateExclusive: String, zoneId: ZoneId) = emptyList<DailyStepsAggregate>()
        override suspend fun changesToken(type: HealthConnectRecordType) = "unused"
        override suspend fun changes(token: String) = HealthConnectChangesPage(emptyList(), token, false, false)
    }
}
