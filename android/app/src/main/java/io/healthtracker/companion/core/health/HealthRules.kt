package io.healthtracker.companion.core.health

import java.math.BigDecimal
import java.math.RoundingMode

private val poundsToKilograms = BigDecimal("0.45359237")

internal fun canonicalWeightKg(value: String, unit: String): String? {
    val parsed = value.toBigDecimalOrNull() ?: return null
    if (parsed <= BigDecimal.ZERO || unit !in setOf("kg", "lb")) return null
    val kilograms = if (unit == "lb") parsed.multiply(poundsToKilograms) else parsed
    return kilograms.setScale(3, RoundingMode.HALF_UP).stripTrailingZeros().toPlainString()
}

internal fun displayWeight(canonicalKg: String, unit: String): String? {
    val kilograms = canonicalKg.toBigDecimalOrNull() ?: return null
    if (unit !in setOf("kg", "lb")) return null
    val displayed = if (unit == "lb") kilograms.divide(poundsToKilograms, 2, RoundingMode.HALF_UP) else kilograms.setScale(2, RoundingMode.HALF_UP)
    return displayed.stripTrailingZeros().toPlainString()
}

internal fun canonicalEditedWeight(value: String, unit: String, originalCanonicalKg: String): String? =
    if (value == displayWeight(originalCanonicalKg, unit)) originalCanonicalKg
    else canonicalWeightKg(value, unit)

internal fun availableMacroTotal(values: List<String?>): String? {
    val available = values.mapNotNull { it?.toBigDecimalOrNull() }
    return available.takeIf { it.isNotEmpty() }
        ?.fold(BigDecimal.ZERO, BigDecimal::add)
        ?.stripTrailingZeros()
        ?.toPlainString()
}

internal fun healthChartDescription(title: String, values: List<Float>, unit: String): String =
    if (values.isEmpty()) "$title: sin datos"
    else "$title: ${values.size} puntos, de ${values.min()} a ${values.max()} $unit"
