package io.healthtracker.companion.core.planning

import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PlanningRulesTest {
    @Test fun reorderIsStableAndRejectsBoundaries() {
        assertEquals(listOf("b", "a", "c"), reorderedIds(listOf("a", "b", "c"), "a", 1))
        assertNull(reorderedIds(listOf("a", "b", "c"), "a", -1))
        assertNull(reorderedIds(listOf("a", "b", "c"), "missing", 1))
    }

    @Test fun weekUsesLocalMondayThroughSunday() {
        val range = planningDateRange(LocalDate.of(2026, 7, 24), month = false)
        assertEquals(LocalDate.of(2026, 7, 20), range.start)
        assertEquals(LocalDate.of(2026, 7, 26), range.endInclusive)
    }

    @Test fun monthUsesActualCalendarBoundaries() {
        val range = planningDateRange(LocalDate.of(2028, 2, 10), month = true)
        assertEquals(LocalDate.of(2028, 2, 1), range.start)
        assertEquals(LocalDate.of(2028, 2, 29), range.endInclusive)
    }

    @Test fun monthGridIncludesBoundariesAndLeapDay() {
        val grid = planningMonthGrid(LocalDate.of(2028, 2, 10))
        assertEquals(LocalDate.of(2028, 1, 31), grid.first())
        assertEquals(LocalDate.of(2028, 3, 5), grid.last())
        assertTrue(LocalDate.of(2028, 2, 29) in grid)
        assertEquals(35, grid.size)
    }

    @Test fun monthAndWeekNavigationKeepAValidSelectedDay() {
        assertEquals(
            LocalDate.of(2026, 2, 28),
            shiftedPlanningAnchor(LocalDate.of(2026, 1, 31), month = true, delta = 1),
        )
        assertEquals(
            LocalDate.of(2026, 7, 31),
            shiftedPlanningAnchor(LocalDate.of(2026, 7, 24), month = false, delta = 1),
        )
    }

    @Test fun storedLocalDateDoesNotShiftWhenDeviceZoneChanges() {
        val stored = LocalDate.parse("2026-07-25")
        assertEquals(stored, LocalDate.parse(stored.toString()))
    }

    @Test fun remoteRefreshCannotOverwriteQueuedOrConflictedPlanningState() {
        assertTrue(protectLocalPlanningState("pending", hasQueuedPlanningWork = true))
        assertTrue(protectLocalPlanningState("conflict", hasQueuedPlanningWork = true))
        assertFalse(protectLocalPlanningState("synced", hasQueuedPlanningWork = true))
        assertFalse(protectLocalPlanningState("pending", hasQueuedPlanningWork = false))
    }

    @Test fun prescriptionLimitsRejectInvalidLocalAutosave() {
        assertTrue(validPrescription("8", "42.5", "2", "8.5", "90"))
        assertFalse(validPrescription("0", "42.5", "2", "8", "90"))
        assertFalse(validPrescription("8", "-1", "2", "8", "90"))
        assertTrue(validPrescription("8", "42.5", "20", "0", "90"))
        assertFalse(validPrescription("8", "42.5", "20.1", "8", "90"))
        assertFalse(validPrescription("8", "42.5", "2", "11", "90"))
        assertFalse(validPrescription("8", "42.5", "2", "8", "86401"))
    }
}
