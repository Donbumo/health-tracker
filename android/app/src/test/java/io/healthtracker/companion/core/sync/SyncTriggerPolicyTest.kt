package io.healthtracker.companion.core.sync

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SyncTriggerPolicyTest {
    @Test fun ambientTriggersAreCoalescedWithinMinimumInterval() {
        assertTrue(shouldEnqueueSync(SyncTrigger.FOREGROUND, Long.MIN_VALUE, 1_000, 5_000))
        assertFalse(shouldEnqueueSync(SyncTrigger.CONNECTIVITY_RECOVERED, 1_000, 4_000, 5_000))
        assertTrue(shouldEnqueueSync(SyncTrigger.CONNECTIVITY_RECOVERED, 1_000, 6_000, 5_000))
    }

    @Test fun durableOperationTriggersAreNeverDroppedByAmbientThrottle() {
        assertTrue(shouldEnqueueSync(SyncTrigger.PENDING_OPERATION, 1_000, 1_001, 5_000))
        assertTrue(shouldEnqueueSync(SyncTrigger.DOWNLOAD_ACK, 1_000, 1_001, 5_000))
    }
}
