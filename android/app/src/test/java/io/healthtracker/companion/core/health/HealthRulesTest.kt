package io.healthtracker.companion.core.health

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HealthRulesTest {
    @Test fun exactPoundConversionUsesCanonicalKilograms() {
        assertEquals("70", canonicalWeightKg("154.323583529", "lb"))
        assertEquals("154.32", displayWeight("70", "lb"))
        assertEquals("70", canonicalEditedWeight(displayWeight("70", "lb")!!, "lb", "70"))
    }

    @Test fun invalidWeightsAndUnitsAreRejectedBesideTheField() {
        assertNull(canonicalWeightKg("", "kg"))
        assertNull(canonicalWeightKg("0", "kg"))
        assertNull(canonicalWeightKg("70", "stone"))
        assertNull(displayWeight("70", "stone"))
    }

    @Test fun incompleteMacrosOnlySumAvailableValues() {
        assertEquals("12.5", availableMacroTotal(listOf("10", null, "2.5", "invalid")))
        assertNull(availableMacroTotal(listOf(null, "invalid")))
    }

    @Test fun chartAccessibilityHandlesZeroOneAndMultiplePoints() {
        assertEquals("Peso: sin datos", healthChartDescription("Peso", emptyList(), "kg"))
        assertEquals("Peso: 1 puntos, de 70.0 a 70.0 kg", healthChartDescription("Peso", listOf(70f), "kg"))
        assertEquals("Pasos: 3 puntos, de 1000.0 a 5000.0 pasos", healthChartDescription("Pasos", listOf(1000f, 5000f, 3000f), "pasos"))
    }
}
