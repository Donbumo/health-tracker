package io.healthtracker.companion.core.database

import androidx.room.Entity
import androidx.room.Index

@Entity(
    tableName = "medical_studies",
    primaryKeys = ["accountScope", "serverIdentity", "publicId"],
    indices = [
        Index(value = ["accountScope", "serverIdentity", "studyDate", "state"]),
        Index(value = ["accountScope", "serverIdentity", "syncStatus"]),
    ],
)
data class MedicalStudyEntity(
    val accountScope: String,
    val serverIdentity: String,
    val publicId: String,
    val studyType: String,
    val title: String,
    val laboratoryName: String?,
    val professionalName: String?,
    val studyDate: String,
    val issuedDate: String?,
    val timezone: String?,
    val notes: String?,
    val state: String,
    val source: String,
    val revision: Int,
    val localRevision: Int,
    val syncStatus: String,
    val createdAt: String,
    val updatedAt: String,
)

@Entity(
    tableName = "medical_documents",
    primaryKeys = ["accountScope", "serverIdentity", "publicId"],
    indices = [
        Index(value = ["accountScope", "serverIdentity", "studyPublicId"]),
        Index(value = ["accountScope", "serverIdentity", "sha256"]),
        Index(value = ["accountScope", "serverIdentity", "syncStatus"]),
    ],
)
data class MedicalDocumentEntity(
    val accountScope: String,
    val serverIdentity: String,
    val publicId: String,
    val studyPublicId: String,
    val documentType: String,
    val originalFilename: String,
    val mimeType: String,
    val sizeBytes: Long,
    val sha256: String,
    val availability: String,
    val localUri: String?,
    val uriPermissionPersisted: Boolean,
    val uploadTempFileName: String?,
    val source: String,
    val revision: Int,
    val syncStatus: String,
    val createdAt: String,
)

@Entity(
    tableName = "lab_panels",
    primaryKeys = ["accountScope", "serverIdentity", "publicId"],
    indices = [
        Index(value = ["accountScope", "serverIdentity", "studyPublicId", "displayOrder"], unique = true),
    ],
)
data class LabPanelEntity(
    val accountScope: String,
    val serverIdentity: String,
    val publicId: String,
    val studyPublicId: String,
    val name: String,
    val displayOrder: Int,
    val source: String,
    val revision: Int,
    val syncStatus: String,
    val createdAt: String,
    val updatedAt: String,
)

@Entity(
    tableName = "lab_results",
    primaryKeys = ["accountScope", "serverIdentity", "publicId"],
    indices = [
        Index(value = ["accountScope", "serverIdentity", "panelPublicId", "displayOrder"], unique = true),
        Index(value = ["accountScope", "serverIdentity", "canonicalKey"]),
    ],
)
data class LabResultEntity(
    val accountScope: String,
    val serverIdentity: String,
    val publicId: String,
    val panelPublicId: String,
    val displayName: String,
    val canonicalKey: String?,
    val valueType: String,
    val originalValue: String,
    val numericValue: String?,
    val comparator: String,
    val originalUnit: String?,
    val canonicalUnit: String?,
    val referenceLower: String?,
    val referenceUpper: String?,
    val referenceText: String?,
    val sourceStatus: String,
    val derivedRangeStatus: String,
    val method: String?,
    val specimen: String?,
    val notes: String?,
    val displayOrder: Int,
    val source: String,
    val revision: Int,
    val localRevision: Int,
    val syncStatus: String,
    val createdAt: String,
    val updatedAt: String,
)

@Entity(
    tableName = "lab_result_revisions",
    primaryKeys = ["accountScope", "serverIdentity", "resultPublicId", "revision"],
    indices = [Index(value = ["accountScope", "serverIdentity", "resultPublicId", "createdAt"])],
)
data class LabResultRevisionEntity(
    val accountScope: String,
    val serverIdentity: String,
    val resultPublicId: String,
    val revision: Int,
    val snapshotJson: String,
    val correctionReason: String?,
    val source: String,
    val createdAt: String,
)

@Entity(
    tableName = "lab_markers",
    primaryKeys = ["accountScope", "serverIdentity", "canonicalKey"],
    indices = [Index(value = ["accountScope", "serverIdentity", "displayName"])],
)
data class LabMarkerEntity(
    val accountScope: String,
    val serverIdentity: String,
    val canonicalKey: String,
    val displayName: String,
    val aliasesJson: String,
    val commonUnitsJson: String,
    val updatedAt: String,
)

@Entity(
    tableName = "medical_operations",
    primaryKeys = ["accountScope", "serverIdentity", "operationId"],
    indices = [
        Index(value = ["accountScope", "serverIdentity", "status", "createdAt"]),
        Index(value = ["accountScope", "serverIdentity", "entityPublicId"]),
        Index(value = ["accountScope", "serverIdentity", "idempotencyKey"], unique = true),
    ],
)
data class MedicalOperationEntity(
    val accountScope: String,
    val serverIdentity: String,
    val operationId: String,
    val operationType: String,
    val entityPublicId: String,
    val parentPublicId: String?,
    val idempotencyKey: String,
    val payloadJson: String,
    val payloadHash: String,
    val status: String,
    val attemptCount: Int,
    val notBeforeEpochMs: Long,
    val createdAt: String,
    val lastErrorCode: String?,
)

@Entity(
    tableName = "medical_history_cache",
    primaryKeys = ["accountScope", "serverIdentity", "canonicalKey", "period"],
    indices = [Index(value = ["accountScope", "serverIdentity", "updatedAt"])],
)
data class MedicalHistoryCacheEntity(
    val accountScope: String,
    val serverIdentity: String,
    val canonicalKey: String,
    val period: String,
    val seriesJson: String,
    val comparable: Boolean,
    val comparisonNotice: String?,
    val updatedAt: String,
)

@Entity(
    tableName = "medical_duplicate_candidates",
    primaryKeys = ["accountScope", "serverIdentity", "publicId"],
    indices = [
        Index(value = ["accountScope", "serverIdentity", "resolution"]),
        Index(value = ["accountScope", "serverIdentity", "leftStudyPublicId", "rightStudyPublicId"], unique = true),
    ],
)
data class MedicalDuplicateCandidateEntity(
    val accountScope: String,
    val serverIdentity: String,
    val publicId: String,
    val leftStudyPublicId: String,
    val rightStudyPublicId: String,
    val classification: String,
    val evidenceJson: String,
    val resolution: String,
    val createdAt: String,
    val resolvedAt: String?,
)
