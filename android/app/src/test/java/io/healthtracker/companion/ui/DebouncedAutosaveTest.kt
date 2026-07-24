package io.healthtracker.companion.ui

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class DebouncedAutosaveTest {
    @Test fun rapidTypingPersistsOnlyLatestValueAfterDebounce() = runTest {
        val saved = mutableListOf<String>()
        val autosave = DebouncedAutosave(this, debounceMillis = 400, persist = saved::add)

        autosave.submit("qa-set", "1")
        advanceTimeBy(200)
        autosave.submit("qa-set", "12")
        advanceTimeBy(399)
        assertEquals(emptyList<String>(), saved)
        advanceUntilIdle()

        assertEquals(listOf("12"), saved)
        assertFalse(autosave.hasPending())
    }

    @Test fun lifecycleFlushPersistsLatestValueImmediately() = runTest {
        val saved = mutableListOf<String>()
        val autosave = DebouncedAutosave(this, debounceMillis = 400, persist = saved::add)
        autosave.submit("qa-set", "offline-draft")

        autosave.flush()

        assertEquals(listOf("offline-draft"), saved)
        assertFalse(autosave.hasPending())
    }
}
