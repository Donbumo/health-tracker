package io.healthtracker.companion.ui

import io.healthtracker.companion.core.config.ThemePreference
import io.healthtracker.companion.core.load.LoadMode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UiFormattersTest {

    @Test
    fun chartScaleHandlesEmptySingleEqualAndMultipleValues() {
        assertNull(chartScale(emptyList()))
        assertEquals(1f, chartScale(listOf(5f))?.span)
        assertEquals(1f, chartScale(listOf(5f, 5f))?.span)
        assertEquals(7f, chartScale(listOf(3f, 10f))?.span)
    }
    @Test fun internalStatusesBecomeHumanText() {
        assertEquals("Guardado; sincronización pendiente", humanDraftStatus("pending_sync"))
        assertEquals("Requiere intervención", humanSyncStatus("conflict"))
        assertEquals("Estado no disponible", humanWorkoutStatus("unexpected_internal_code"))
    }

    @Test fun datesAndDurationsAreReadableWithoutExposingRawInvalidValues() {
        assertFalse(readableDate("2026-07-20").contains("T"))
        assertEquals("Fecha no disponible", readableInstant("not-a-date"))
        assertEquals("1 h 31 min", humanDuration(5_460))
    }

    @Test fun decimalDraftPreservesInvalidInputForVisibleValidation() {
        assertEquals("12..x", decimalDraft("12..x"))
        assertEquals("12.5", decimalDraft("12,5"))
        assertTrue(decimalDraft("123456", 4).length == 4)
    }

    @Test fun visualEnumsNeverExposeWireNames() {
        assertEquals("Barra más carga por lado", humanLoadMode(LoadMode.BAR_PLUS_PER_SIDE))
        assertEquals("Carga externa por lado", humanComponent("external_per_side"))
        assertEquals("Sistema", humanTheme(ThemePreference.SYSTEM))
    }

    @Test fun durationOrDistanceDraftUsesItsContractualEditor() {
        assertEquals(LoadMode.DURATION_DISTANCE, initialLoadMode(null, 600, null))
        assertEquals(LoadMode.DURATION_DISTANCE, initialLoadMode(null, null, "5000"))
        assertEquals(LoadMode.BODYWEIGHT, initialLoadMode("bodyweight", null, null))
    }

    @Test fun offlineAndActiveAutosaveStatesUseExplicitHumanCopy() {
        assertEquals("Guardando…", autosaveStatusText(AutosaveUiState.SAVING))
        assertEquals("Guardado", autosaveStatusText(AutosaveUiState.SAVED))
        assertEquals("Guardado en este dispositivo", autosaveStatusText(AutosaveUiState.SAVED_LOCAL))
    }

    @Test fun isolatedDraftReasonsAreSanitizedAndSpecific() {
        assertEquals("Package local ausente", humanDraftIsolationReason("draft_package_missing"))
        assertEquals(
            "El borrador pertenece a otro dispositivo",
            humanDraftIsolationReason("draft_device_mismatch"),
        )
        assertEquals("Integridad local no verificable", humanDraftIsolationReason("unexpected_internal_detail"))
    }
}
