package io.healthtracker.companion.core.planning

import java.math.BigDecimal
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.YearMonth

internal fun reorderedIds(ids: List<String>, id: String, delta: Int): List<String>? {
    val values = ids.toMutableList()
    val from = values.indexOf(id)
    val to = from + delta
    if (from < 0 || to !in values.indices) return null
    val moved = values.removeAt(from)
    values.add(to, moved)
    return values
}

internal fun planningDateRange(anchor: LocalDate, month: Boolean): ClosedRange<LocalDate> {
    val first = if (month) YearMonth.from(anchor).atDay(1) else anchor.with(DayOfWeek.MONDAY)
    val last = if (month) YearMonth.from(anchor).atEndOfMonth() else first.plusDays(6)
    return first..last
}

internal fun planningMonthGrid(anchor: LocalDate): List<LocalDate> {
    val month = YearMonth.from(anchor)
    val first = month.atDay(1).with(DayOfWeek.MONDAY)
    val last = month.atEndOfMonth().with(java.time.temporal.TemporalAdjusters.nextOrSame(DayOfWeek.SUNDAY))
    return (0L..java.time.temporal.ChronoUnit.DAYS.between(first, last)).map(first::plusDays)
}

internal fun shiftedPlanningAnchor(anchor: LocalDate, month: Boolean, delta: Long): LocalDate =
    if (month) {
        val target = YearMonth.from(anchor).plusMonths(delta)
        target.atDay(anchor.dayOfMonth.coerceAtMost(target.lengthOfMonth()))
    } else {
        anchor.plusWeeks(delta)
    }

internal fun protectLocalPlanningState(syncStatus: String?, hasQueuedPlanningWork: Boolean): Boolean =
    hasQueuedPlanningWork && syncStatus in setOf("pending", "conflict")

internal fun validPrescription(
    reps: String,
    load: String,
    rir: String,
    rpe: String,
    rest: String,
): Boolean =
    (reps.isBlank() || reps.toIntOrNull()?.let { it > 0 } == true) &&
        (load.isBlank() || load.toBigDecimalOrNull()?.signum()?.let { it >= 0 } == true) &&
        (rir.isBlank() || rir.toBigDecimalOrNull()?.let { it in BigDecimal.ZERO..BigDecimal("20") } == true) &&
        (rpe.isBlank() || rpe.toBigDecimalOrNull()?.let { it in BigDecimal.ZERO..BigDecimal.TEN } == true) &&
        (rest.isBlank() || rest.toIntOrNull()?.let { it in 0..86400 } == true)
