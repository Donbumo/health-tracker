package io.healthtracker.companion.ui

import io.healthtracker.companion.core.config.ThemePreference
import io.healthtracker.companion.core.load.LoadMode
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.util.Locale

internal data class ChartScale(val minimum: Float, val maximum: Float, val span: Float)

internal fun chartScale(values: List<Float>): ChartScale? {
    val finite = values.filter(Float::isFinite)
    if (finite.isEmpty()) return null
    val minimum = finite.min()
    val maximum = finite.max()
    return ChartScale(minimum, maximum, (maximum - minimum).takeIf { it > 0f } ?: 1f)
}

private val displayLocale = Locale.forLanguageTag("es-MX")
private val dateFormatter = DateTimeFormatter.ofPattern("d MMM yyyy", displayLocale)
private val dateTimeFormatter = DateTimeFormatter.ofPattern("d MMM yyyy, HH:mm", displayLocale)

internal fun readableDate(value: String): String = try {
    LocalDate.parse(value).format(dateFormatter)
} catch (_: DateTimeParseException) {
    "Fecha no disponible"
}

internal fun readableInstant(value: String?): String {
    if (value.isNullOrBlank()) return "Todavía no se ha sincronizado"
    return try {
        dateTimeFormatter.format(Instant.parse(value).atZone(ZoneId.systemDefault()))
    } catch (_: DateTimeParseException) {
        "Fecha no disponible"
    }
}

internal fun humanDraftStatus(status: String): String = when (status) {
    "active" -> "Activo"
    "paused" -> "En pausa"
    "saved" -> "Guardado localmente"
    "pending_sync" -> "Guardado; sincronización pendiente"
    "completion_pending" -> "Finalización pendiente"
    "aborted_pending" -> "Cancelación pendiente"
    "corrupt" -> "Requiere intervención"
    else -> "Estado no disponible"
}

internal fun humanDraftIsolationReason(code: String?): String = when (code) {
    "draft_schema_incompatible" -> "Versión de borrador incompatible"
    "draft_expired" -> "El borrador local expiró"
    "draft_package_missing" -> "Package local ausente"
    "draft_package_mismatch" -> "Identidad o hash del package no coincide"
    "draft_delivery_missing" -> "Delivery local ausente"
    "draft_package_content_missing" -> "Contenido estructural del package ausente"
    "draft_sets_missing" -> "Series locales ausentes"
    "draft_metric_invalid" -> "Métrica local inválida"
    "draft_payload_hash_mismatch" -> "Integridad del borrador no coincide"
    "draft_start_state_missing" -> "No existe evidencia local o remota del inicio"
    "draft_account_missing" -> "Cuenta local ausente"
    "draft_account_scope_mismatch" -> "El borrador pertenece a otro ámbito de cuenta"
    "draft_device_mismatch" -> "El borrador pertenece a otro dispositivo"
    "draft_profile_missing" -> "Perfil Companion local ausente"
    "draft_profile_mismatch" -> "El borrador pertenece a otro perfil Companion"
    else -> "Integridad local no verificable"
}

internal fun humanWorkoutStatus(status: String): String = when (status) {
    "planned" -> "Programado"
    "in_progress" -> "En progreso"
    "completed" -> "Completado"
    "cancelled" -> "Cancelado"
    else -> "Estado no disponible"
}

internal fun humanSyncStatus(status: String): String = when (status) {
    "synced" -> "Sincronizado"
    "pending", "pending_sync" -> "Pendiente de sincronización"
    "sending" -> "Enviando"
    "conflict" -> "Requiere intervención"
    "rejected" -> "Rechazado"
    else -> "Estado no disponible"
}

internal fun autosaveStatusText(state: AutosaveUiState): String = when (state) {
    AutosaveUiState.SAVING -> "Guardando…"
    AutosaveUiState.SAVED -> "Guardado"
    AutosaveUiState.SAVED_LOCAL -> "Guardado en este dispositivo"
    AutosaveUiState.ERROR -> "Requiere atención: no se pudo guardar localmente"
}

internal fun humanDuration(seconds: Int?): String {
    if (seconds == null || seconds < 0) return "Duración no disponible"
    val hours = seconds / 3_600
    val minutes = (seconds % 3_600) / 60
    return when {
        hours > 0 -> "${hours} h ${minutes} min"
        minutes > 0 -> "${minutes} min"
        else -> "${seconds} s"
    }
}

internal fun humanTheme(value: ThemePreference): String = when (value) {
    ThemePreference.SYSTEM -> "Sistema"
    ThemePreference.LIGHT -> "Claro"
    ThemePreference.DARK -> "Oscuro"
}

internal fun humanRecordType(value: String): String = when (value) {
    "highest_load" -> "Mayor carga"
    "most_reps_at_comparable_load" -> "Más repeticiones"
    "highest_set_volume" -> "Mayor volumen de serie"
    "highest_session_volume" -> "Mayor volumen de sesión"
    else -> "Mejor marca"
}

internal fun humanTrend(value: String): String = when (value) {
    "up" -> "Tendencia al alza"
    "down" -> "Tendencia a la baja"
    "stable" -> "Tendencia estable"
    else -> "Datos insuficientes para una tendencia"
}

internal fun humanLoadMode(value: LoadMode): String = when (value) {
    LoadMode.DIRECT_TOTAL -> "Carga total directa"
    LoadMode.PER_SIDE -> "Carga por lado"
    LoadMode.BAR_PLUS_PER_SIDE -> "Barra más carga por lado"
    LoadMode.MACHINE_INITIAL_TOTAL -> "Máquina: inicial más añadida"
    LoadMode.MACHINE_INITIAL_PER_SIDE -> "Máquina: carga por lado"
    LoadMode.MACHINE_EXTERNAL_PER_SIDE_INITIAL_TOTAL -> "Máquina: inicial total más carga externa por lado"
    LoadMode.SELECTOR_STACK -> "Torre selectora"
    LoadMode.DUMBBELL_EACH -> "Mancuerna por mano"
    LoadMode.BODYWEIGHT -> "Peso corporal"
    LoadMode.BODYWEIGHT_PLUS -> "Peso corporal más carga"
    LoadMode.ASSISTANCE -> "Peso corporal con asistencia"
    LoadMode.DURATION_DISTANCE -> "Duración y distancia"
}

internal fun humanComponent(value: String): String = when (value) {
    "direct_total" -> "Carga total"
    "per_side" -> "Carga por lado"
    "bar" -> "Barra"
    "initial_total" -> "Carga inicial total"
    "added_total" -> "Carga añadida total"
    "initial_per_side" -> "Carga inicial por lado"
    "external_per_side" -> "Carga externa por lado"
    "selector_stack" -> "Torre seleccionada"
    "dumbbell_each" -> "Cada mancuerna"
    "bodyweight" -> "Peso corporal"
    "assistance" -> "Asistencia"
    "duration_seconds" -> "Duración"
    "distance_meters" -> "Distancia"
    else -> "Componente"
}

internal fun initialLoadMode(existingMode: String?, durationSeconds: Int?, distanceMeters: String?): LoadMode =
    existingMode?.let { runCatching { LoadMode.fromWire(it) }.getOrNull() }
        ?: if (durationSeconds != null || distanceMeters != null) LoadMode.DURATION_DISTANCE else LoadMode.DIRECT_TOTAL

internal fun decimalDraft(value: String, maxLength: Int = 16): String =
    value.replace(',', '.').take(maxLength)
