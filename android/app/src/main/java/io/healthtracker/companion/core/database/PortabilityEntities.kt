package io.healthtracker.companion.core.database

import androidx.room.Entity
import androidx.room.Index

@Entity(
    tableName = "portable_export_jobs",
    primaryKeys = ["accountScope", "publicId"],
    indices = [Index(value = ["accountScope", "createdAt"]), Index(value = ["accountScope", "state"])],
)
data class PortableExportJobEntity(
    val accountScope: String,
    val publicId: String,
    val state: String,
    val sectionsJson: String,
    val countsJson: String,
    val sha256: String?,
    val sizeBytes: Long?,
    val requestJson: String,
    val idempotencyKey: String,
    val revision: Int,
    val syncStatus: String,
    val createdAt: String,
    val expiresAt: String?,
    val completedAt: String?,
    val errorCode: String?,
)

@Entity(
    tableName = "portable_import_jobs",
    primaryKeys = ["accountScope", "publicId"],
    indices = [Index(value = ["accountScope", "createdAt"]), Index(value = ["accountScope", "state"])],
)
data class PortableImportJobEntity(
    val accountScope: String,
    val publicId: String,
    val state: String,
    val sectionsJson: String,
    val countsJson: String,
    val sourceUri: String?,
    val uriPermissionPersisted: Boolean,
    val packageSha256: String?,
    val sizeBytes: Long?,
    val uploadIdempotencyKey: String,
    val applyIdempotencyKey: String,
    val revision: Int,
    val syncStatus: String,
    val createdAt: String,
    val expiresAt: String?,
    val completedAt: String?,
    val errorCode: String?,
)

@Entity(tableName = "portable_inspections", primaryKeys = ["accountScope", "importPublicId"])
data class PortableInspectionEntity(
    val accountScope: String,
    val importPublicId: String,
    val packageSha256: String,
    val format: String,
    val formatVersion: String,
    val sectionsJson: String,
    val countsJson: String,
    val filesJson: String,
    val warningsJson: String,
    val integrity: String,
    val authenticity: String,
    val verifiedAt: String,
)

@Entity(tableName = "portable_import_plans", primaryKeys = ["accountScope", "importPublicId"])
data class PortableImportPlanEntity(
    val accountScope: String,
    val importPublicId: String,
    val planId: String,
    val revision: Int,
    val selectedSectionsJson: String,
    val summaryJson: String,
    val recordsJson: String,
    val warningsJson: String,
    val expiresAt: String,
)

@Entity(
    tableName = "portable_import_decisions",
    primaryKeys = ["accountScope", "importPublicId", "section", "sourcePublicId"],
    indices = [Index(value = ["accountScope", "importPublicId"])],
)
data class PortableImportDecisionEntity(
    val accountScope: String,
    val importPublicId: String,
    val section: String,
    val sourcePublicId: String,
    val strategy: String,
    val updatedAt: String,
)

@Entity(
    tableName = "portable_downloads",
    primaryKeys = ["accountScope", "exportPublicId"],
    indices = [Index(value = ["accountScope", "state"])],
)
data class PortableDownloadEntity(
    val accountScope: String,
    val exportPublicId: String,
    val partialFileName: String?,
    val finalFileName: String?,
    val expectedSha256: String,
    val calculatedSha256: String?,
    val expectedBytes: Long?,
    val downloadedBytes: Long,
    val state: String,
    val updatedAt: String,
    val errorCode: String?,
)

@Entity(
    tableName = "portable_temp_files",
    primaryKeys = ["accountScope", "fileId"],
    indices = [Index(value = ["accountScope", "expiresAt"])],
)
data class PortableTempFileEntity(
    val accountScope: String,
    val fileId: String,
    val kind: String,
    val fileName: String,
    val sha256: String?,
    val sizeBytes: Long?,
    val createdAt: String,
    val expiresAt: String,
)
