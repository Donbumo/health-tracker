package io.healthtracker.companion.core.healthconnect

import io.healthtracker.companion.core.security.Redaction
import java.time.Instant
import java.time.temporal.ChronoUnit

data class HealthConnectDiagnosticContext(
    val appVersion: String,
    val appVersionCode: Int,
    val androidVersion: String,
    val androidApi: Int,
    val pendingOperations: Int = 0,
)

fun sanitizedHealthConnectDiagnostic(
    context: HealthConnectDiagnosticContext,
    state: HealthConnectUiState,
): String = buildString {
    appendLine("Health Tracker Health Connect diagnostic")
    appendLine("app=${context.appVersion} (${context.appVersionCode})")
    appendLine("android=${context.androidVersion} api=${context.androidApi}")
    appendLine("provider_state=${state.status.name.lowercase()}")
    appendLine("provider_available=${state.status !in setOf(HealthConnectUiStatus.UNAVAILABLE_DEVICE, HealthConnectUiStatus.UNAVAILABLE_PROVIDER)}")
    appendLine("provider_update_required=${state.status == HealthConnectUiStatus.UPDATE_REQUIRED}")
    appendLine("selected_type_count=${state.selectedTypes.size}")
    appendLine("selected_type_groups=${state.selectedTypes.map(::diagnosticTypeGroup).toSortedSet().joinToString(",")}")
    appendLine("granted_type_count=${state.grantedTypes.size}")
    appendLine("granted_type_groups=${state.grantedTypes.map(::diagnosticTypeGroup).toSortedSet().joinToString(",")}")
    appendLine("background_available=${state.backgroundAvailable}")
    appendLine("background_authorized=${state.backgroundGranted}")
    appendLine("pending_operations=${context.pendingOperations.coerceAtLeast(0)}")
    appendLine("imported_count=${state.importedCount}")
    appendLine("deleted_count=${state.deletedCount}")
    appendLine("last_import_at=${diagnosticHour(state.lastImportAt)}")
    appendLine("error_code=${Redaction.diagnosticCode(state.errorCode) ?: "none"}")
}

private fun diagnosticTypeGroup(type: HealthConnectRecordType): String = when (type) {
    HealthConnectRecordType.WEIGHT,
    HealthConnectRecordType.BODY_FAT,
    HealthConnectRecordType.LEAN_BODY_MASS,
    HealthConnectRecordType.BODY_WATER_MASS -> "body"
    HealthConnectRecordType.STEPS -> "activity"
    HealthConnectRecordType.NUTRITION -> "other"
}

private fun diagnosticHour(value: String?): String = when (value) {
    null -> "never"
    else -> runCatching { Instant.parse(value).truncatedTo(ChronoUnit.HOURS).toString() }.getOrDefault("invalid")
}
