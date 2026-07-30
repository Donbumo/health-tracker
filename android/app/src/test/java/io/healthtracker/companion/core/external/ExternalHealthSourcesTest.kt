package io.healthtracker.companion.core.external

import java.math.BigDecimal
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ExternalHealthSourcesTest {
    private val reconciler = ExternalMeasurementReconciler()

    @Test fun registryDeclaresAllInitialSourcesWithStableIds() {
        val sources = ExternalSourceRegistry().defaults()
        assertEquals(
            setOf("manual", "health_connect_generic", "health_connect_confirmed_scale", "health_connect_confirmed_xiaomi_s400", "xiaomi_s400_ble_experimental"),
            sources.mapTo(mutableSetOf()) { it.id },
        )
        assertTrue(sources.first { it.id == "xiaomi_s400_ble_experimental" }.experimental)
        assertFalse(sources.first { it.id == "manual" }.experimental)
    }

    @Test fun registryKeepsBleLocalAndDoesNotClaimWeightCapability() {
        val ble = ExternalSourceRegistry().defaults().first { it.id == "xiaomi_s400_ble_experimental" }
        assertEquals(ExternalSourceSyncState.LOCAL_ONLY, ble.syncState)
        assertFalse(ExternalSourceCapability.WEIGHT in ble.capabilities)
        assertFalse("weight_kg" in ble.supportedMetrics)
    }

    @Test fun healthConnectRecordIdIsAnExactDuplicate() {
        val decision = reconciler.reconcile(measurement(recordId = "r1"), measurement(id = "b", recordId = "r1"))
        assertEquals(ReconciliationResult.EXACT_DUPLICATE, decision.result)
        assertTrue(decision.mayAutoReconcile)
    }

    @Test fun clientRecordIdIsAnExactDuplicate() {
        val decision = reconciler.reconcile(measurement(clientRecordId = "c1"), measurement(id = "b", clientRecordId = "c1"))
        assertEquals(ReconciliationResult.EXACT_DUPLICATE, decision.result)
    }

    @Test fun sameConfirmedDeviceAndRoundedValueIsProbable() {
        val left = measurement(fingerprint = "scale-a", confirmed = true, value = "70.00")
        val right = measurement(id = "b", fingerprint = "scale-a", confirmed = true, value = "70.04", seconds = 20)
        val decision = reconciler.reconcile(left, right)
        assertEquals(ReconciliationResult.PROBABLE_DUPLICATE, decision.result)
        assertFalse(decision.mayAutoReconcile)
    }

    @Test fun temporalProximityWithoutIdentityIsOnlyPossible() {
        val decision = reconciler.reconcile(measurement(), measurement(id = "b", seconds = 120, value = "70.03"))
        assertEquals(ReconciliationResult.POSSIBLE_DUPLICATE, decision.result)
        assertFalse(decision.mayAutoReconcile)
    }

    @Test fun matchingContentWithoutConfirmedIdentityStillRequiresReview() {
        val left = measurement(id = "shared")
        val right = measurement(id = "shared", source = "manual")
        val decision = reconciler.reconcile(left, right)
        assertEquals(ReconciliationResult.POSSIBLE_DUPLICATE, decision.result)
        assertFalse(decision.mayAutoReconcile)
    }

    @Test fun farMeasurementsAreDistinct() {
        assertEquals(ReconciliationResult.DISTINCT, reconciler.reconcile(measurement(), measurement(id = "b", seconds = 1_000)).result)
    }

    @Test fun differentMetricsAreDistinctEvenAtSameTime() {
        assertEquals(ReconciliationResult.DISTINCT, reconciler.reconcile(measurement(), measurement(id = "b", metric = "body_fat_percent")).result)
    }

    @Test fun userOverrideIsNeverAutoMerged() {
        val decision = reconciler.reconcile(measurement(userOverride = true), measurement(id = "b", recordId = "r1"))
        assertEquals(ReconciliationResult.UNRESOLVED, decision.result)
        assertFalse(decision.mayAutoReconcile)
    }

    @Test fun detachedMeasurementStaysDetached() {
        assertEquals(ReconciliationResult.USER_DETACHED, reconciler.reconcile(measurement(detached = true), measurement(id = "b")).result)
    }

    @Test fun twoConfirmedDevicesAreNotExactDuplicatesWithoutStrongIdentity() {
        val decision = reconciler.reconcile(
            measurement(fingerprint = "scale-a", confirmed = true),
            measurement(id = "b", fingerprint = "scale-b", confirmed = true, seconds = 10),
        )
        assertNotEquals(ReconciliationResult.EXACT_DUPLICATE, decision.result)
        assertFalse(decision.mayAutoReconcile)
    }

    @Test fun healthConnectArrivingMinutesLaterPreservesBothForReview() {
        val decision = reconciler.reconcile(measurement(source = "manual"), measurement(id = "b", source = "health_connect_generic", seconds = 240))
        assertEquals(ReconciliationResult.POSSIBLE_DUPLICATE, decision.result)
    }

    @Test fun fingerprintsAreStableShortAndDoNotRevealInput() {
        val first = shortFingerprint("private.package.name")
        assertEquals(first, shortFingerprint("private.package.name"))
        assertEquals(24, first.length)
        assertFalse(first.contains("private"))
        assertNotEquals(first, shortFingerprint("other.package.name"))
    }

    private fun measurement(
        id: String = "a",
        source: String = "health_connect_generic",
        metric: String = "weight_kg",
        value: String = "70.00",
        seconds: Long = 0,
        fingerprint: String? = null,
        confirmed: Boolean = false,
        recordId: String? = null,
        clientRecordId: String? = null,
        userOverride: Boolean = false,
        detached: Boolean = false,
    ) = ExternalMeasurement(
        id = id,
        sourceId = source,
        metricType = metric,
        observedAt = Instant.parse("2026-07-28T12:00:00Z").plusSeconds(seconds),
        zoneOffset = "Z",
        canonicalValue = BigDecimal(value),
        precision = 2,
        identity = ExternalSourceIdentity(source, fingerprint, if (confirmed) ExternalSourceIdentityQuality.USER_CONFIRMED else ExternalSourceIdentityQuality.WEAK, confirmed),
        recordId = recordId,
        clientRecordId = clientRecordId,
        contentFingerprint = if (recordId != null) "content-$recordId" else "content-$id",
        userOverride = userOverride,
        detached = detached,
    )
}
