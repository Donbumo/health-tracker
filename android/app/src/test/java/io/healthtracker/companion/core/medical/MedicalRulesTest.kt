package io.healthtracker.companion.core.medical

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MedicalRulesTest {
    @Test fun rejectsNonFiniteAndKeepsTextOutsideNumericDerivation() {
        assertNull(MedicalRules.decimalOrNull("NaN"))
        assertNull(MedicalRules.decimalOrNull("Infinity"))
        assertEquals("not_computable", MedicalRules.derivedRangeStatus("text", null, "1", "2", "equal"))
        assertEquals("not_computable", MedicalRules.derivedRangeStatus("numeric", "3", "1", "2", "less_than"))
    }

    @Test fun derivedRangeIsOnlyMechanicalAgainstReportedBounds() {
        assertEquals("below_reported_range", MedicalRules.derivedRangeStatus("numeric", "0.9", "1", "2", "equal"))
        assertEquals("within_reported_range", MedicalRules.derivedRangeStatus("numeric", "1.5", "1", "2", "equal"))
        assertEquals("above_reported_range", MedicalRules.derivedRangeStatus("numeric", "2.1", "1", "2", "none"))
    }

    @Test fun conversionIsSmallVersionedAndMethodAware() {
        val converted = MedicalRules.convert("0.095", "g/L")!!
        assertEquals("95", converted.value.toPlainString())
        assertEquals("mg/L", converted.canonicalUnit)
        assertEquals("medical-units-v1", converted.version)
        assertTrue(MedicalRules.comparable("g/L", "mg/L", "QA-A", "qa-a"))
        assertFalse(MedicalRules.comparable("g/L", "mg/L", "QA-A", "QA-B"))
        assertNull(MedicalRules.convert("5", "mmol/L"))
    }
}
