package io.healthtracker.companion.core.external

import java.math.BigDecimal
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.time.Duration
import java.time.Instant

enum class ExternalSourceType {
    MANUAL, HEALTH_CONNECT, BLUETOOTH_LOW_ENERGY,
}

enum class ExternalSourceCapability {
    WEIGHT, BODY_FAT, DISCOVERY, ASSOCIATION, GATT_INSPECTION, EXPERIMENTAL_CAPTURE, REPLAY,
}

enum class ExternalSourceIdentityQuality { NONE, WEAK, USER_CONFIRMED, STRONG }
enum class ExternalSourceAvailability { AVAILABLE, PERMISSION_REQUIRED, BLUETOOTH_DISABLED, UNSUPPORTED, UNAVAILABLE }
enum class ExternalSourceSyncState { LOCAL_ONLY, IDLE, SYNCING, SYNCED, ERROR_RECOVERABLE }

data class ExternalHealthSource(
    val id: String,
    val type: ExternalSourceType,
    val displayName: String,
    val availability: ExternalSourceAvailability,
    val experimental: Boolean,
    val capabilities: Set<ExternalSourceCapability>,
    val requiredPermissions: Set<String>,
    val supportedMetrics: Set<String>,
    val identityQuality: ExternalSourceIdentityQuality,
    val deduplicationStrategy: String,
    val visualPriority: Int,
    val editable: Boolean,
    val userOverrideAllowed: Boolean,
    val lastDetectedAt: Instant? = null,
    val syncState: ExternalSourceSyncState = ExternalSourceSyncState.IDLE,
)

data class ExternalSourceIdentity(
    val sourceId: String,
    val fingerprint: String?,
    val quality: ExternalSourceIdentityQuality,
    val userConfirmed: Boolean,
)

data class ExternalMeasurement(
    val id: String,
    val sourceId: String,
    val metricType: String,
    val observedAt: Instant,
    val zoneOffset: String?,
    val canonicalValue: BigDecimal,
    val precision: Int?,
    val identity: ExternalSourceIdentity,
    val recordId: String? = null,
    val clientRecordId: String? = null,
    val contentFingerprint: String,
    val userOverride: Boolean = false,
    val detached: Boolean = false,
)

data class ExternalMeasurementEvidence(
    val sameRecordId: Boolean = false,
    val sameClientRecordId: Boolean = false,
    val sameContentFingerprint: Boolean = false,
    val sameConfirmedDevice: Boolean = false,
    val sameMetric: Boolean = false,
    val timestampDeltaSeconds: Long? = null,
    val canonicalDifference: BigDecimal? = null,
    val score: Int = 0,
    val reasons: Set<String> = emptySet(),
)

enum class ReconciliationResult {
    DISTINCT, EXACT_DUPLICATE, PROBABLE_DUPLICATE, POSSIBLE_DUPLICATE, USER_DETACHED, UNRESOLVED,
}

data class ReconciliationDecision(
    val result: ReconciliationResult,
    val evidence: ExternalMeasurementEvidence,
    val mayAutoReconcile: Boolean,
)

class ExternalMeasurementReconciler {
    fun reconcile(left: ExternalMeasurement, right: ExternalMeasurement): ReconciliationDecision {
        if (left.detached || right.detached) return decision(ReconciliationResult.USER_DETACHED, reasons = setOf("user_detached"))
        if (left.metricType != right.metricType) return decision(ReconciliationResult.DISTINCT, reasons = setOf("different_metric"))
        if (left.userOverride || right.userOverride) return decision(ReconciliationResult.UNRESOLVED, reasons = setOf("user_override"))

        val sameRecord = left.recordId != null && left.recordId == right.recordId
        val sameClientRecord = left.clientRecordId != null && left.clientRecordId == right.clientRecordId
        val sameContent = left.contentFingerprint == right.contentFingerprint
        val sameDevice = left.identity.userConfirmed && right.identity.userConfirmed &&
            left.identity.fingerprint != null && left.identity.fingerprint == right.identity.fingerprint
        val seconds = kotlin.math.abs(Duration.between(left.observedAt, right.observedAt).seconds)
        val difference = left.canonicalValue.subtract(right.canonicalValue).abs()
        val reasons = buildSet {
            if (sameRecord) add("record_id")
            if (sameClientRecord) add("client_record_id")
            if (sameContent) add("content_fingerprint")
            if (sameDevice) add("confirmed_device")
            if (seconds <= 2) add("timestamp_exact") else if (seconds <= 300) add("timestamp_near")
            if (difference.compareTo(BigDecimal.ZERO) == 0) add("value_exact") else if (difference <= tolerance(left.metricType)) add("value_rounded")
        }
        val result = when {
            sameRecord || sameClientRecord -> ReconciliationResult.EXACT_DUPLICATE
            sameContent && sameDevice -> ReconciliationResult.EXACT_DUPLICATE
            sameDevice && seconds <= 30 && difference <= tolerance(left.metricType) -> ReconciliationResult.PROBABLE_DUPLICATE
            seconds <= 300 && difference <= tolerance(left.metricType) -> ReconciliationResult.POSSIBLE_DUPLICATE
            else -> ReconciliationResult.DISTINCT
        }
        val evidence = ExternalMeasurementEvidence(
            sameRecordId = sameRecord,
            sameClientRecordId = sameClientRecord,
            sameContentFingerprint = sameContent,
            sameConfirmedDevice = sameDevice,
            sameMetric = true,
            timestampDeltaSeconds = seconds,
            canonicalDifference = difference,
            score = reasons.sumOf { evidenceWeight(it) },
            reasons = reasons,
        )
        return ReconciliationDecision(result, evidence, mayAutoReconcile = result == ReconciliationResult.EXACT_DUPLICATE)
    }

    private fun decision(result: ReconciliationResult, reasons: Set<String>) = ReconciliationDecision(
        result,
        ExternalMeasurementEvidence(reasons = reasons),
        mayAutoReconcile = false,
    )

    private fun tolerance(metric: String) = when (metric) {
        "weight_kg" -> BigDecimal("0.05")
        "body_fat_percent" -> BigDecimal("0.1")
        else -> BigDecimal.ZERO
    }

    private fun evidenceWeight(reason: String) = when (reason) {
        "record_id", "client_record_id" -> 100
        "content_fingerprint" -> 50
        "confirmed_device" -> 40
        "timestamp_exact", "value_exact" -> 20
        "timestamp_near", "value_rounded" -> 5
        else -> 0
    }
}

class ExternalSourceRegistry {
    fun defaults(): List<ExternalHealthSource> = listOf(
        source("manual", ExternalSourceType.MANUAL, "Registro manual", false, setOf(ExternalSourceCapability.WEIGHT, ExternalSourceCapability.BODY_FAT), ExternalSourceIdentityQuality.NONE, 100, true),
        source("health_connect_generic", ExternalSourceType.HEALTH_CONNECT, "Health Connect", false, setOf(ExternalSourceCapability.WEIGHT, ExternalSourceCapability.BODY_FAT), ExternalSourceIdentityQuality.WEAK, 80, false),
        source("health_connect_confirmed_scale", ExternalSourceType.HEALTH_CONNECT, "Báscula confirmada", false, setOf(ExternalSourceCapability.WEIGHT, ExternalSourceCapability.BODY_FAT), ExternalSourceIdentityQuality.USER_CONFIRMED, 90, false),
        source("health_connect_confirmed_xiaomi_s400", ExternalSourceType.HEALTH_CONNECT, "Xiaomi S400 confirmada", true, setOf(ExternalSourceCapability.WEIGHT, ExternalSourceCapability.BODY_FAT), ExternalSourceIdentityQuality.USER_CONFIRMED, 95, false),
        source("xiaomi_s400_ble_experimental", ExternalSourceType.BLUETOOTH_LOW_ENERGY, "Xiaomi S400 (experimental)", true, setOf(ExternalSourceCapability.DISCOVERY, ExternalSourceCapability.ASSOCIATION, ExternalSourceCapability.GATT_INSPECTION, ExternalSourceCapability.EXPERIMENTAL_CAPTURE, ExternalSourceCapability.REPLAY), ExternalSourceIdentityQuality.USER_CONFIRMED, 60, false),
    )

    private fun source(
        id: String,
        type: ExternalSourceType,
        name: String,
        experimental: Boolean,
        capabilities: Set<ExternalSourceCapability>,
        quality: ExternalSourceIdentityQuality,
        priority: Int,
        editable: Boolean,
    ) = ExternalHealthSource(
        id = id,
        type = type,
        displayName = name,
        availability = ExternalSourceAvailability.AVAILABLE,
        experimental = experimental,
        capabilities = capabilities,
        requiredPermissions = if (type == ExternalSourceType.BLUETOOTH_LOW_ENERGY) setOf("bluetooth_scan", "bluetooth_connect") else emptySet(),
        supportedMetrics = capabilities.mapNotNullTo(mutableSetOf()) { if (it == ExternalSourceCapability.WEIGHT) "weight_kg" else if (it == ExternalSourceCapability.BODY_FAT) "body_fat_percent" else null },
        identityQuality = quality,
        deduplicationStrategy = if (type == ExternalSourceType.HEALTH_CONNECT) "record_id_then_evidence" else "explicit_identity_then_evidence",
        visualPriority = priority,
        editable = editable,
        userOverrideAllowed = true,
        syncState = if (type == ExternalSourceType.BLUETOOTH_LOW_ENERGY) ExternalSourceSyncState.LOCAL_ONLY else ExternalSourceSyncState.IDLE,
    )
}

fun shortFingerprint(value: String, bytes: Int = 12): String {
    require(bytes in 6..32)
    val digest = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(StandardCharsets.UTF_8))
    return digest.take(bytes).joinToString("") { "%02x".format(it) }
}
