package io.healthtracker.companion.core.sync

import kotlinx.coroutines.CancellationException
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Test

class CancellationTest {
    @Test fun cancellationIsNeverConvertedIntoRetryOrFailure() {
        val cancellation = CancellationException("qa-cancelled")
        val thrown = assertThrows(CancellationException::class.java) {
            cancellation.rethrowIfCancellation()
        }
        assertSame(cancellation, thrown)
    }

    @Test fun ordinaryFailuresRemainAvailableForSanitizedMapping() {
        IllegalStateException("qa-failure").rethrowIfCancellation()
    }
}
