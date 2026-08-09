package io.healthtracker.companion.core.bluetooth

import android.Manifest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class BlePermissionResolutionTest {
    @Test fun api31UsesScanAndConnectOnly() {
        assertEquals(setOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT), requiredBlePermissionsFor(31))
        assertFalse(Manifest.permission.BLUETOOTH_ADVERTISE in requiredBlePermissionsFor(31))
    }

    @Test fun api26To30UsesLocationForBleScan() {
        listOf(26, 27, 28, 29, 30).forEach { api ->
            assertEquals(setOf(Manifest.permission.ACCESS_FINE_LOCATION), requiredBlePermissionsFor(api))
        }
    }
}
