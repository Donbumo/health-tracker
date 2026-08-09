package io.healthtracker.companion.core.medical

import java.math.BigDecimal
import java.math.RoundingMode

data class MedicalConversion(
    val value: BigDecimal,
    val canonicalUnit: String,
    val factor: BigDecimal,
    val precision: Int,
    val version: String = "medical-units-v1",
)

object MedicalRules {
    private data class UnitRule(val unit: String, val factor: BigDecimal, val precision: Int)
    private val conversions = mapOf(
        "kg" to UnitRule("g", BigDecimal("1000"), 6),
        "g" to UnitRule("g", BigDecimal.ONE, 6),
        "mg" to UnitRule("g", BigDecimal("0.001"), 9),
        "l" to UnitRule("mL", BigDecimal("1000"), 6),
        "ml" to UnitRule("mL", BigDecimal.ONE, 6),
        "g/l" to UnitRule("mg/L", BigDecimal("1000"), 6),
        "mg/l" to UnitRule("mg/L", BigDecimal.ONE, 6),
        "°c" to UnitRule("°C", BigDecimal.ONE, 4),
    )

    fun decimalOrNull(value: String?): BigDecimal? {
        if (value.isNullOrBlank() || value in setOf("NaN", "Infinity", "+Infinity", "-Infinity")) return null
        return value.toBigDecimalOrNull()
    }

    fun derivedRangeStatus(valueType: String, value: String?, lower: String?, upper: String?, comparator: String): String {
        if (valueType != "numeric" || comparator !in setOf("equal", "none")) return "not_computable"
        val number = decimalOrNull(value) ?: return "not_computable"
        val low = decimalOrNull(lower); val high = decimalOrNull(upper)
        if (low != null && number < low) return "below_reported_range"
        if (high != null && number > high) return "above_reported_range"
        return if (low != null || high != null) "within_reported_range" else "not_computable"
    }

    fun convert(value: String, unit: String): MedicalConversion? {
        val number = decimalOrNull(value) ?: return null
        val rule = conversions[unit.trim().lowercase()] ?: return null
        return MedicalConversion(number.multiply(rule.factor).setScale(rule.precision, RoundingMode.HALF_EVEN)
            .stripTrailingZeros(), rule.unit, rule.factor, rule.precision)
    }

    fun comparable(leftUnit: String?, rightUnit: String?, leftMethod: String?, rightMethod: String?): Boolean {
        if (!leftMethod.orEmpty().trim().equals(rightMethod.orEmpty().trim(), ignoreCase = true)) return false
        if (leftUnit.orEmpty().equals(rightUnit.orEmpty(), ignoreCase = true)) return true
        val left = conversions[leftUnit.orEmpty().trim().lowercase()] ?: return false
        val right = conversions[rightUnit.orEmpty().trim().lowercase()] ?: return false
        return left.unit == right.unit
    }
}
