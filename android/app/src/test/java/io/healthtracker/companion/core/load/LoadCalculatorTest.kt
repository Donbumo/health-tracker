package io.healthtracker.companion.core.load

import java.math.BigDecimal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class LoadCalculatorTest {
    @Test fun press397Lb() {
        val result = LoadCalculator.calculate(
            LoadMode.MACHINE_EXTERNAL_PER_SIDE_INITIAL_TOTAL, "lb",
            mapOf("initial_total" to lb("167"), "external_per_side" to lb("115")),
        )
        assertEquals(BigDecimal("180.08"), result.weightKg)
        assertEquals("397", result.details.displayTotal.value)
    }

    @Test fun shoulderPress144Lb() {
        val result = LoadCalculator.calculate(
            LoadMode.MACHINE_INITIAL_PER_SIDE, "lb",
            mapOf("initial_per_side" to lb("27"), "external_per_side" to lb("45")),
        )
        assertEquals(BigDecimal("65.32"), result.weightKg)
        assertEquals("144", result.details.calculatedTotalLb)
    }

    @Test fun tBarRow82Lb() {
        val result = LoadCalculator.calculate(
            LoadMode.MACHINE_INITIAL_TOTAL, "lb",
            mapOf("initial_total" to lb("37"), "added_total" to lb("45")),
        )
        assertEquals(BigDecimal("37.19"), result.weightKg)
    }

    @Test fun mixedKgAndLbAreConvertedOnce() {
        val result = LoadCalculator.calculate(
            LoadMode.BAR_PLUS_PER_SIDE, "kg",
            mapOf("bar" to kg("20"), "per_side" to lb("45")),
        )
        assertEquals(BigDecimal("60.82"), result.weightKg)
        assertEquals("lb", result.details.components.getValue("per_side").unit)
    }

    @Test fun everyModeHasExpectedFormula() {
        val cases = mapOf(
            LoadMode.DIRECT_TOTAL to mapOf("direct_total" to kg("10")),
            LoadMode.PER_SIDE to mapOf("per_side" to kg("10")),
            LoadMode.BAR_PLUS_PER_SIDE to mapOf("bar" to kg("20"), "per_side" to kg("10")),
            LoadMode.MACHINE_INITIAL_TOTAL to mapOf("initial_total" to kg("20"), "added_total" to kg("10")),
            LoadMode.MACHINE_INITIAL_PER_SIDE to mapOf("initial_per_side" to kg("20"), "external_per_side" to kg("10")),
            LoadMode.MACHINE_EXTERNAL_PER_SIDE_INITIAL_TOTAL to mapOf("initial_total" to kg("20"), "external_per_side" to kg("10")),
            LoadMode.SELECTOR_STACK to mapOf("selector_stack" to kg("10")),
            LoadMode.DUMBBELL_EACH to mapOf("dumbbell_each" to kg("10")),
            LoadMode.BODYWEIGHT to mapOf("bodyweight" to kg("80")),
            LoadMode.BODYWEIGHT_PLUS to mapOf("bodyweight" to kg("80"), "added_total" to kg("10")),
            LoadMode.ASSISTANCE to mapOf("bodyweight" to kg("80"), "assistance" to kg("20")),
            LoadMode.DURATION_DISTANCE to mapOf(
                "duration_seconds" to ComponentInput(BigDecimal("600"), "s"),
                "distance_meters" to ComponentInput(BigDecimal("2000"), "m"),
            ),
        )
        cases.forEach { (mode, components) ->
            val result = LoadCalculator.calculate(mode, "kg", components)
            assertEquals("1.0", result.details.calculationVersion)
        }
        assertEquals(BigDecimal("0.00"), LoadCalculator.calculate(LoadMode.DURATION_DISTANCE, "kg", cases.getValue(LoadMode.DURATION_DISTANCE)).weightKg)
    }

    @Test fun assistanceNeverBecomesNegative() {
        val result = LoadCalculator.calculate(
            LoadMode.ASSISTANCE, "kg", mapOf("bodyweight" to kg("60"), "assistance" to kg("70")),
        )
        assertEquals(BigDecimal("0.00"), result.weightKg)
        assertEquals(listOf("assistance_is_subtracted_from_bodyweight"), result.details.warnings)
    }

    @Test fun zeroAndDecimalsAreAccepted() {
        val result = LoadCalculator.calculate(LoadMode.DIRECT_TOTAL, "kg", mapOf("direct_total" to kg("0.125")))
        assertEquals(BigDecimal("0.13"), result.weightKg)
    }

    @Test fun negativesExtraComponentsAndUnknownModesAreRejected() {
        assertThrows(LoadValidationException::class.java) {
            LoadCalculator.calculate(LoadMode.DIRECT_TOTAL, "kg", mapOf("direct_total" to kg("-1")))
        }
        assertThrows(LoadValidationException::class.java) {
            LoadCalculator.calculate(LoadMode.DIRECT_TOTAL, "kg", mapOf("direct_total" to kg("1"), "bar" to kg("1")))
        }
        assertThrows(LoadValidationException::class.java) { LoadMode.fromWire("invented") }
    }

    private fun kg(value: String) = ComponentInput(BigDecimal(value), "kg")
    private fun lb(value: String) = ComponentInput(BigDecimal(value), "lb")
}
