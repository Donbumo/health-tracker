package io.healthtracker.companion.core.healthconnect

import io.healthtracker.companion.core.external.shortFingerprint
import io.healthtracker.companion.core.sync.rethrowIfCancellation
import java.time.Instant
import java.time.temporal.ChronoUnit

enum class ScaleDiagnosticStatus {
    IDLE,
    NO_COMPATIBLE_MEASUREMENTS,
    WEIGHT_FOUND,
    WEIGHT_AND_BODY_FAT_FOUND,
    MULTIPLE_ORIGINS,
    ORIGIN_UNCERTAIN,
    ALREADY_IMPORTED,
    PERMISSION_REQUIRED,
    HEALTH_CONNECT_UNAVAILABLE,
    TEMPORARY_ERROR,
}

data class SanitizedHealthConnectOrigin(
    val fingerprint: String,
    val safeLabel: String,
    val recordCount: Int,
    val importedCount: Int,
    val notImportedCount: Int,
    val types: Set<String>,
    val deviceMetadataAvailable: Boolean,
)

data class ScaleDiagnosticResult(
    val status: ScaleDiagnosticStatus = ScaleDiagnosticStatus.IDLE,
    val notices: Set<ScaleDiagnosticStatus> = emptySet(),
    val foundTypes: Set<String> = emptySet(),
    val recordCount: Int = 0,
    val originCount: Int = 0,
    val firstDate: String? = null,
    val lastDate: String? = null,
    val origins: List<SanitizedHealthConnectOrigin> = emptyList(),
    val importedCount: Int = 0,
    val notImportedCount: Int = 0,
    val missingPermissions: Set<String> = emptySet(),
    val errorCode: String? = null,
    val truncatedWindowDays: Int = 30,
) {
    fun humanSummary(): String = (notices.ifEmpty { setOf(status) }).joinToString(" ") { humanMessage(it) }

    private fun humanMessage(value: ScaleDiagnosticStatus): String = when (value) {
        ScaleDiagnosticStatus.IDLE -> "Listo para comprobar datos de báscula."
        ScaleDiagnosticStatus.NO_COMPATIBLE_MEASUREMENTS -> "No se encontraron mediciones compatibles."
        ScaleDiagnosticStatus.WEIGHT_FOUND -> "Se encontró peso."
        ScaleDiagnosticStatus.WEIGHT_AND_BODY_FAT_FOUND -> "Se encontraron peso y grasa corporal."
        ScaleDiagnosticStatus.MULTIPLE_ORIGINS -> "Existen varios orígenes."
        ScaleDiagnosticStatus.ORIGIN_UNCERTAIN -> "El origen no puede identificarse con seguridad."
        ScaleDiagnosticStatus.ALREADY_IMPORTED -> "Los datos ya están importados."
        ScaleDiagnosticStatus.PERMISSION_REQUIRED -> "Se necesita permiso adicional."
        ScaleDiagnosticStatus.HEALTH_CONNECT_UNAVAILABLE -> "Health Connect no está disponible."
        ScaleDiagnosticStatus.TEMPORARY_ERROR -> "Error temporal."
    }
}

class HealthConnectScaleDiagnosticService(
    private val gateway: HealthConnectGateway,
    private val isRecordImported: suspend (String, HealthConnectRecordType, String) -> Boolean,
    private val observeOrigin: suspend (String, String) -> Unit,
) {
    suspend fun inspect(scope: String, now: Instant = Instant.now()): ScaleDiagnosticResult {
        if (gateway.availability() != HealthConnectAvailability.AVAILABLE) {
            return ScaleDiagnosticResult(status = ScaleDiagnosticStatus.HEALTH_CONNECT_UNAVAILABLE)
        }
        val types = listOf(HealthConnectRecordType.WEIGHT, HealthConnectRecordType.BODY_FAT)
        val granted = runCatching { gateway.grantedPermissions() }.getOrElse {
            return ScaleDiagnosticResult(status = ScaleDiagnosticStatus.TEMPORARY_ERROR, errorCode = sanitizedError(it))
        }
        val missing = types.filter { type -> gateway.permissionsFor(setOf(type)).any { it !in granted } }.mapTo(mutableSetOf()) { it.storageValue }
        if (missing.isNotEmpty()) return ScaleDiagnosticResult(
            status = ScaleDiagnosticStatus.PERMISSION_REQUIRED,
            missingPermissions = missing,
        )

        val records = mutableListOf<Pair<HealthConnectRecordType, HealthConnectRecord>>()
        val from = now.minus(30, ChronoUnit.DAYS)
        try {
            types.forEach { type ->
                var pageToken: String? = null
                var pageCount = 0
                do {
                    val page = gateway.readPage(type, from, now, pageToken)
                    records += page.records.map { type to it }
                    pageToken = page.nextPageToken
                    pageCount++
                } while (pageToken != null && pageCount < 10 && records.size < 5_000)
            }
        } catch (failure: Exception) {
            failure.rethrowIfCancellation()
            return ScaleDiagnosticResult(status = ScaleDiagnosticStatus.TEMPORARY_ERROR, errorCode = sanitizedError(failure))
        }
        if (records.isEmpty()) return ScaleDiagnosticResult(status = ScaleDiagnosticStatus.NO_COMPATIBLE_MEASUREMENTS)

        data class MutableOrigin(
            var count: Int = 0,
            var imported: Int = 0,
            val types: MutableSet<String> = mutableSetOf(),
        )
        val grouped = linkedMapOf<String, MutableOrigin>()
        var imported = 0
        records.forEach { (type, record) ->
            val originFingerprint = shortFingerprint("health-connect-origin:${record.metadata.dataOrigin}")
            val state = grouped.getOrPut(originFingerprint) { MutableOrigin() }
            state.count++
            state.types += type.storageValue
            if (isRecordImported(scope, type, record.metadata.id)) {
                state.imported++
                imported++
            }
            observeOrigin(scope, record.metadata.dataOrigin)
        }
        val origins = grouped.map { (fingerprint, state) ->
            SanitizedHealthConnectOrigin(
                fingerprint = fingerprint,
                safeLabel = "Aplicación de salud",
                recordCount = state.count,
                importedCount = state.imported,
                notImportedCount = state.count - state.imported,
                types = state.types,
                deviceMetadataAvailable = false,
            )
        }
        val found = records.mapTo(mutableSetOf()) { it.first.storageValue }
        val first = records.minOf { it.second.startTime }.truncatedTo(ChronoUnit.DAYS).toString()
        val last = records.maxOf { it.second.startTime }.truncatedTo(ChronoUnit.DAYS).toString()
        val notices = buildSet {
            if (origins.size > 1) add(ScaleDiagnosticStatus.MULTIPLE_ORIGINS)
            if (origins.any { it.safeLabel == "Aplicación de salud" }) add(ScaleDiagnosticStatus.ORIGIN_UNCERTAIN)
            if (imported == records.size) add(ScaleDiagnosticStatus.ALREADY_IMPORTED)
            if (HealthConnectRecordType.WEIGHT.storageValue in found && HealthConnectRecordType.BODY_FAT.storageValue in found) {
                add(ScaleDiagnosticStatus.WEIGHT_AND_BODY_FAT_FOUND)
            } else {
                add(ScaleDiagnosticStatus.WEIGHT_FOUND)
            }
        }
        val status = when {
            origins.size > 1 -> ScaleDiagnosticStatus.MULTIPLE_ORIGINS
            imported == records.size -> ScaleDiagnosticStatus.ALREADY_IMPORTED
            HealthConnectRecordType.WEIGHT.storageValue in found && HealthConnectRecordType.BODY_FAT.storageValue in found -> ScaleDiagnosticStatus.WEIGHT_AND_BODY_FAT_FOUND
            else -> ScaleDiagnosticStatus.WEIGHT_FOUND
        }
        return ScaleDiagnosticResult(
            status = status,
            notices = notices,
            foundTypes = found,
            recordCount = records.size,
            originCount = origins.size,
            firstDate = first,
            lastDate = last,
            origins = origins,
            importedCount = imported,
            notImportedCount = records.size - imported,
        )
    }

    private fun sanitizedError(failure: Throwable): String = when (failure) {
        is HealthConnectGatewayException -> failure.sanitizedCode.take(64)
        is SecurityException -> "permission_revoked"
        else -> "provider_error"
    }
}
