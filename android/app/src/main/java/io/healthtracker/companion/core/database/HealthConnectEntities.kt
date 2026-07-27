package io.healthtracker.companion.core.database

import androidx.room.Entity
import androidx.room.Index

@Entity(tableName = "health_connect_settings", primaryKeys = ["accountScope"])
data class HealthConnectSettingsEntity(
    val accountScope: String,
    val enabled: Boolean,
    val paused: Boolean,
    val selectedTypes: String,
    val initialLookbackDays: Int,
    val permissionGeneration: Long,
    val lastAvailability: String,
    val updatedAt: String,
)

@Entity(
    tableName = "health_connect_permission_state",
    primaryKeys = ["accountScope", "recordType"],
)
data class HealthConnectPermissionStateEntity(
    val accountScope: String,
    val recordType: String,
    val selected: Boolean,
    val granted: Boolean,
    val backgroundGranted: Boolean,
    val checkedAt: String,
    val reasonCode: String?,
)

@Entity(
    tableName = "health_connect_sync_state",
    primaryKeys = ["accountScope", "recordType"],
)
data class HealthConnectSyncStateEntity(
    val accountScope: String,
    val recordType: String,
    val token: String?,
    val tokenCreatedAt: String?,
    val lastSuccessfulReadAt: String?,
    val lastFullReconciliationAt: String?,
    val coveredTypes: String,
    val permissionGeneration: Long,
    val state: String,
    val lastAttemptAt: String?,
    val lastImportedAt: String?,
    val importedCount: Int,
    val deletedCount: Int,
    val lastErrorCode: String?,
)

@Entity(
    tableName = "health_connect_record_ledger",
    primaryKeys = ["accountScope", "recordType", "healthConnectRecordId"],
    indices = [
        Index(value = ["accountScope", "localResourceUuid"]),
        Index(value = ["accountScope", "recordType", "sourceStartTime"]),
        Index(value = ["accountScope", "state"]),
    ],
)
data class HealthConnectRecordLedgerEntity(
    val accountScope: String,
    val recordType: String,
    val healthConnectRecordId: String,
    val clientRecordId: String?,
    val dataOrigin: String,
    val localResourceUuid: String?,
    val serverResourceUuid: String?,
    val lastModifiedTime: String,
    val clientRecordVersion: Long?,
    val contentFingerprint: String,
    val importedAt: String,
    val lastSeenAt: String,
    val state: String,
    val detachedByUser: Boolean,
    val deletedAt: String?,
    val sourceStartTime: String,
    val sourceEndTime: String?,
)
