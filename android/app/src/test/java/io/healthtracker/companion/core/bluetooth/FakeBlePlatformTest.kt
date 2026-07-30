package io.healthtracker.companion.core.bluetooth

import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FakeBlePlatformTest {
    private val candidate = BleDeviceCandidate("session-1", "Dispositivo QA", "abcdef123456", emptySet(), null, -40)

    @Test fun deviceWithoutBleIsDistinctFromBluetoothDisabled() {
        val environment = FakeBleEnvironment(BleEnvironmentState.DEVICE_WITHOUT_BLE)
        assertEquals(BleEnvironmentState.DEVICE_WITHOUT_BLE, environment.state())
        environment.current = BleEnvironmentState.BLUETOOTH_DISABLED
        assertEquals(BleEnvironmentState.BLUETOOTH_DISABLED, environment.state())
    }

    @Test fun deniedAndRevokedPermissionAreObservableWithoutSessionState() {
        val permission = FakeBlePermissionController(BlePermissionState.DENIED)
        assertEquals(BlePermissionState.DENIED, permission.state())
        permission.current = BlePermissionState.DENIED_PERMANENTLY
        assertEquals(BlePermissionState.DENIED_PERMANENTLY, permission.state())
    }

    @Test fun selectingAListedCandidateStopsScanExactlyOnce() {
        val session = FakeBleScanSession()
        session.publish(listOf(candidate))
        assertEquals(candidate, session.select("session-1"))
        assertEquals(1, session.cancelCount)
        session.cancel()
        assertEquals(1, session.cancelCount)
    }

    @Test fun selectingCandidateOutsideShownSetIsRejectedAndScanContinues() {
        val session = FakeBleScanSession()
        session.publish(listOf(candidate))
        assertNull(session.select("not-shown"))
        assertEquals(0, session.cancelCount)
    }

    @Test fun scanCancellationIsTerminal() {
        val session = FakeBleScanSession()
        session.cancel()
        session.publish(listOf(candidate))
        assertNull(session.select(candidate.sessionDeviceId))
    }

    @Test fun fakeGattClosesAfterSuccessfulUse() = runTest {
        val client = FakeBleGattClient()
        client.connect(candidate).use { assertEquals(BleGattState.DISCOVERED, it.inspect().state) }
        assertTrue(client.lastConnection!!.closed)
    }

    @Test fun fakeGattClosesAfterFailureState() = runTest {
        val client = FakeBleGattClient(BleGattInspection(BleGattState.ERROR_RECOVERABLE, null, emptyList(), "fixture_error"))
        client.connect(candidate).use { assertEquals("fixture_error", it.inspect().resultCode) }
        assertTrue(client.lastConnection!!.closed)
    }

    @Test fun notifyAndIndicateSnapshotsStayStructural() {
        val service = BleGattServiceSnapshot(
            "00000000-0000-4000-8000-000000000001",
            listOf(BleGattCharacteristicSnapshot("00000000-0000-4000-8000-000000000002", setOf("notify", "indicate"), 1)),
        )
        assertTrue("notify" in service.characteristics.single().properties)
        assertTrue("indicate" in service.characteristics.single().properties)
        assertEquals(0, service.characteristics.single().maximumObservedSize)
    }

    @Test fun permissionSetNeverIncludesAdvertise() {
        assertFalse("advertise" in FakeBlePermissionController().requiredPermissions())
    }
}
