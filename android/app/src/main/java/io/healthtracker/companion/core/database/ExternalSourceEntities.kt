package io.healthtracker.companion.core.database

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index

@Entity(
    tableName = "external_sources",
    primaryKeys = ["accountScope", "sourceId"],
    indices = [Index(value = ["accountScope", "sourceType"])],
)
data class ExternalSourceEntity(
    val accountScope: String,
    val sourceId: String,
    val sourceType: String,
    val displayName: String,
    val availability: String,
    val experimental: Boolean,
    val requiredPermissions: String,
    val supportedMetrics: String,
    val identityQuality: String,
    val deduplicationStrategy: String,
    val visualPriority: Int,
    val editable: Boolean,
    val userOverrideAllowed: Boolean,
    val lastDetectedAt: String?,
    val syncState: String,
    val updatedAt: String,
)

@Entity(
    tableName = "external_source_capabilities",
    primaryKeys = ["accountScope", "sourceId", "capability"],
    foreignKeys = [
        ForeignKey(
            entity = ExternalSourceEntity::class,
            parentColumns = ["accountScope", "sourceId"],
            childColumns = ["accountScope", "sourceId"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [Index(value = ["accountScope", "sourceId"])],
)
data class ExternalSourceCapabilityEntity(
    val accountScope: String,
    val sourceId: String,
    val capability: String,
)

@Entity(
    tableName = "health_connect_source_associations",
    primaryKeys = ["accountScope", "sourceFingerprint"],
    indices = [
        Index(value = ["accountScope", "state"]),
        Index(value = ["accountScope", "sourceId"]),
    ],
)
data class HealthConnectSourceAssociationEntity(
    val accountScope: String,
    val sourceFingerprint: String,
    val sourceId: String,
    val safeLabel: String,
    val state: String,
    val confirmedModel: String?,
    val identityQuality: String,
    val firstSeenAt: String,
    val lastSeenAt: String,
    val confirmedAt: String?,
    val revokedAt: String?,
)

@Entity(
    tableName = "ble_device_associations",
    primaryKeys = ["accountScope", "associationKey"],
    indices = [
        Index(value = ["accountScope", "deviceFingerprint"], unique = true),
        Index(value = ["accountScope", "state"]),
    ],
)
data class BleDeviceAssociationEntity(
    val accountScope: String,
    val associationKey: String,
    val systemAssociationId: Long?,
    val sanitizedName: String,
    val alias: String?,
    val deviceFingerprint: String,
    val serviceUuids: String,
    val manufacturerFingerprint: String?,
    val firstSeenAt: String,
    val lastSeenAt: String,
    val state: String,
    val userConfirmedModel: String?,
)

@Entity(
    tableName = "ble_gatt_snapshots",
    primaryKeys = ["accountScope", "snapshotId"],
    indices = [Index(value = ["accountScope", "associationKey", "observedDate"])],
)
data class BleGattSnapshotEntity(
    val accountScope: String,
    val snapshotId: String,
    val associationKey: String,
    val serviceFingerprint: String,
    val servicesJson: String,
    val observedDate: String,
    val resultCode: String,
)

@Entity(
    tableName = "ble_capture_metadata",
    primaryKeys = ["accountScope", "captureId"],
    indices = [Index(value = ["accountScope", "associationKey", "createdDate"])],
)
data class BleCaptureMetadataEntity(
    val accountScope: String,
    val captureId: String,
    val associationKey: String,
    val encryptedFileName: String,
    val createdDate: String,
    val eventCount: Int,
    val byteCount: Int,
    val durationMs: Long,
    val checksum: String,
    val terminalState: String,
)

@Entity(
    tableName = "external_measurement_ledger",
    primaryKeys = ["accountScope", "measurementId"],
    indices = [
        Index(value = ["accountScope", "sourceId", "observedAt"]),
        Index(value = ["accountScope", "strongIdentity"], unique = true),
        Index(value = ["accountScope", "localResourceUuid"]),
    ],
)
data class ExternalMeasurementLedgerEntity(
    val accountScope: String,
    val measurementId: String,
    val sourceId: String,
    val metricType: String,
    val observedAt: String,
    val zoneOffset: String?,
    val canonicalValueHash: String,
    val precision: Int?,
    val sourceFingerprint: String?,
    val strongIdentity: String?,
    val contentFingerprint: String,
    val localResourceUuid: String?,
    val state: String,
    val userOverride: Boolean,
    val createdAt: String,
    val updatedAt: String,
)

@Entity(
    tableName = "possible_duplicates",
    primaryKeys = ["accountScope", "duplicateId"],
    indices = [
        Index(value = ["accountScope", "leftMeasurementId", "rightMeasurementId"], unique = true),
        Index(value = ["accountScope", "resolution"]),
    ],
)
data class PossibleDuplicateEntity(
    val accountScope: String,
    val duplicateId: String,
    val leftMeasurementId: String,
    val rightMeasurementId: String,
    val classification: String,
    val evidenceJson: String,
    val resolution: String,
    val createdAt: String,
    val resolvedAt: String?,
)

@Entity(
    tableName = "protocol_evidence",
    primaryKeys = ["accountScope", "evidenceId"],
    indices = [Index(value = ["accountScope", "captureId", "relativeTimestampMs"])],
)
data class ProtocolEvidenceEntity(
    val accountScope: String,
    val evidenceId: String,
    val captureId: String,
    val relativeTimestampMs: Long,
    val displayedValue: String,
    val unit: String,
    val frameFingerprint: String?,
    val state: String,
    val createdAt: String,
)
