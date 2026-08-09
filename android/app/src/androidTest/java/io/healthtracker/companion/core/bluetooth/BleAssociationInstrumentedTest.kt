package io.healthtracker.companion.core.bluetooth

import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class BleAssociationInstrumentedTest {
    @Test fun fakeAssociationRequiresAnExplicitSingleDeviceRequest() = runBlocking {
        val manager = FakeBleAssociationManager()
        val result = manager.request(BleAssociationRequest(modelLabel = "Dispositivo QA ficticio", singleDevice = true))

        assertTrue(manager.supported())
        assertEquals(BleAssociationState.ASSOCIATED, result.state)
        assertEquals(1L, result.systemAssociationId)
    }
}
