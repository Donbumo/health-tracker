package io.healthtracker.companion.core.load

import io.healthtracker.companion.core.model.LoadDetailsDto
import io.healthtracker.companion.core.model.WeightComponentDto
import java.math.BigDecimal
import java.math.MathContext
import java.math.RoundingMode
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.put

enum class LoadMode(val components: List<String>) {
    DIRECT_TOTAL(listOf("direct_total")),
    PER_SIDE(listOf("per_side")),
    BAR_PLUS_PER_SIDE(listOf("bar", "per_side")),
    MACHINE_INITIAL_TOTAL(listOf("initial_total", "added_total")),
    MACHINE_INITIAL_PER_SIDE(listOf("initial_per_side", "external_per_side")),
    MACHINE_EXTERNAL_PER_SIDE_INITIAL_TOTAL(listOf("initial_total", "external_per_side")),
    SELECTOR_STACK(listOf("selector_stack")),
    DUMBBELL_EACH(listOf("dumbbell_each")),
    BODYWEIGHT(listOf("bodyweight")),
    BODYWEIGHT_PLUS(listOf("bodyweight", "added_total")),
    ASSISTANCE(listOf("bodyweight", "assistance")),
    DURATION_DISTANCE(listOf("duration_seconds", "distance_meters"));

    val wireName: String get() = name.lowercase()

    companion object {
        fun fromWire(value: String): LoadMode = entries.firstOrNull { it.wireName == value }
            ?: throw LoadValidationException("Modo de carga desconocido.")
    }
}

data class ComponentInput(val value: BigDecimal, val unit: String)
data class LoadPreview(val weightKg: BigDecimal, val totalKg: BigDecimal, val totalLb: BigDecimal, val details: LoadDetailsDto)
class LoadValidationException(message: String) : IllegalArgumentException(message)

object LoadCalculator {
    val lbToKg = BigDecimal("0.45359237")
    private val maxWeight = BigDecimal("2000")

    fun calculate(mode: LoadMode, displayUnit: String, components: Map<String, ComponentInput>): LoadPreview {
        if (displayUnit !in setOf("kg", "lb")) throw LoadValidationException("Unidad no compatible.")
        if (components.keys != mode.components.toSet()) throw LoadValidationException("Faltan componentes o existen componentes extra.")
        components.forEach { (name, input) -> validateComponent(name, input) }
        val kg = components.mapValues { (name, input) ->
            if (name in setOf("duration_seconds", "distance_meters")) input.value else toKg(input.value, input.unit)
        }
        val warnings = mutableListOf<String>()
        val totalKg = when (mode) {
            LoadMode.DIRECT_TOTAL -> kg.getValue("direct_total")
            LoadMode.PER_SIDE -> kg.getValue("per_side").multiply(TWO, PYTHON_DECIMAL_CONTEXT)
            LoadMode.BAR_PLUS_PER_SIDE -> kg.getValue("bar").add(kg.getValue("per_side").multiply(TWO, PYTHON_DECIMAL_CONTEXT), PYTHON_DECIMAL_CONTEXT)
            LoadMode.MACHINE_INITIAL_TOTAL -> kg.getValue("initial_total").add(kg.getValue("added_total"), PYTHON_DECIMAL_CONTEXT)
            LoadMode.MACHINE_INITIAL_PER_SIDE -> kg.getValue("initial_per_side").add(kg.getValue("external_per_side"), PYTHON_DECIMAL_CONTEXT).multiply(TWO, PYTHON_DECIMAL_CONTEXT)
            LoadMode.MACHINE_EXTERNAL_PER_SIDE_INITIAL_TOTAL -> kg.getValue("initial_total").add(kg.getValue("external_per_side").multiply(TWO, PYTHON_DECIMAL_CONTEXT), PYTHON_DECIMAL_CONTEXT)
            LoadMode.SELECTOR_STACK -> kg.getValue("selector_stack")
            LoadMode.DUMBBELL_EACH -> kg.getValue("dumbbell_each").multiply(TWO, PYTHON_DECIMAL_CONTEXT)
            LoadMode.BODYWEIGHT -> kg.getValue("bodyweight")
            LoadMode.BODYWEIGHT_PLUS -> kg.getValue("bodyweight").add(kg.getValue("added_total"), PYTHON_DECIMAL_CONTEXT)
            LoadMode.ASSISTANCE -> {
                warnings += "assistance_is_subtracted_from_bodyweight"
                kg.getValue("bodyweight").subtract(kg.getValue("assistance"), PYTHON_DECIMAL_CONTEXT).max(BigDecimal.ZERO)
            }
            LoadMode.DURATION_DISTANCE -> {
                warnings += "duration_distance_has_no_normalized_weight"
                BigDecimal.ZERO
            }
        }
        if (totalKg > maxWeight) throw LoadValidationException("La carga normalizada supera 2000 kg.")
        val totalLb = totalKg.divide(lbToKg, PYTHON_DECIMAL_CONTEXT)
        val componentDtos = components.mapValues { (_, value) ->
            WeightComponentDto(decimalText(value.value), value.unit)
        }
        val originalInput = buildJsonObject {
            put("unit", displayUnit)
            put("components", buildJsonObject {
                componentDtos.forEach { (name, component) ->
                    put(name, buildJsonObject {
                        put("value", component.value)
                        put("unit", component.unit)
                    })
                }
            })
        }
        val displayValue = if (displayUnit == "kg") totalKg else totalLb
        val details = LoadDetailsDto(
            loadMode = mode.wireName,
            originalInput = originalInput,
            originalUnit = displayUnit,
            components = componentDtos,
            normalizedTotalKg = decimalText(totalKg),
            calculatedTotalLb = decimalText(totalLb),
            displayTotal = WeightComponentDto(decimalText(displayValue), displayUnit),
            bodyweightKg = kg["bodyweight"]?.let { JsonPrimitive(decimalText(it)) } ?: JsonNull,
            assistance = componentDtos["assistance"]?.let { component ->
                buildJsonObject {
                    put("value", component.value)
                    put("unit", component.unit)
                }
            } ?: JsonNull,
            warnings = warnings.takeIf { it.isNotEmpty() },
        )
        return LoadPreview(
            weightKg = totalKg.setScale(2, RoundingMode.HALF_UP),
            totalKg = totalKg,
            totalLb = totalLb,
            details = details,
        )
    }

    private fun validateComponent(name: String, input: ComponentInput) {
        if (input.value.signum() < 0) throw LoadValidationException("$name no puede ser negativo.")
        val expectedUnit = when (name) {
            "duration_seconds" -> "s"
            "distance_meters" -> "m"
            else -> null
        }
        if (expectedUnit != null && input.unit != expectedUnit) throw LoadValidationException("$name debe usar $expectedUnit.")
        if (expectedUnit == null && input.unit !in setOf("kg", "lb")) throw LoadValidationException("$name debe usar kg o lb.")
        val maximum = when (name) {
            "duration_seconds" -> BigDecimal("604800")
            "distance_meters" -> BigDecimal("10000000")
            else -> maxWeight
        }
        if (input.value > maximum) throw LoadValidationException("$name supera el máximo permitido.")
    }

    private fun toKg(value: BigDecimal, unit: String): BigDecimal = when (unit) {
        "kg" -> value
        "lb" -> value.multiply(lbToKg, PYTHON_DECIMAL_CONTEXT)
        else -> throw LoadValidationException("Unidad no compatible.")
    }

    private fun decimalText(value: BigDecimal): String = value.stripTrailingZeros().toPlainString().let {
        if (it == "-0") "0" else it
    }

    private val TWO = BigDecimal("2")
    private val PYTHON_DECIMAL_CONTEXT = MathContext(28, RoundingMode.HALF_EVEN)
}
