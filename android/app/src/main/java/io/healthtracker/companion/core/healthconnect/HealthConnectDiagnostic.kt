package io.healthtracker.companion.core.healthconnect

import io.healthtracker.companion.core.security.Redaction
import java.time.Instant
import java.time.temporal.ChronoUnit

data class HealthConnectDiagnosticContext(
    val appVersion: String,
    val appVersionCode: Int,
    val androidVersion: String,
    val androidApi: Int,
)

fun sanitizedHealthConnectDiagnostic(
    context: HealthConnectDiagnosticContext,
    state: HealthConnectUiState,
): String = buildString {
    appendLine("Health Tracker Health Connect diagnostic")
    appendLine("app=${context.appVersion} (${context.appVersionCode})")
    appendLine("android=${context.androidVersion} api=${context.androidApi}")
    appendLine("provider_state=${state.status.name.lowercase()}")
    appendLine("selected_types=${state.selectedTypes.map { it.storageValue }.sorted().joinToString(",")}")
    appendLine("granted_type_count=${state.grantedTypes.size}")
    appendLine("imported_count=${state.importedCount}")
    appendLine("deleted_count=${state.deletedCount}")
    appendLine("last_import_at=${diagnosticHour(state.lastImportAt)}")
    appendLine("error_code=${Redaction.diagnosticCode(state.errorCode) ?: "none"}")
}

private fun diagnosticHour(value: String?): String = when (value) {
    null -> "never"
    else -> runCatching { Instant.parse(value).truncatedTo(ChronoUnit.HOURS).toString() }.getOrDefault("invalid")
}
