package io.healthtracker.companion.core.medical

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import androidx.room.withTransaction
import io.healthtracker.companion.core.database.*
import io.healthtracker.companion.core.model.AppFailure
import io.healthtracker.companion.core.network.ApiClient
import java.io.File
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.serialization.json.*

private const val MAX_DOCUMENT_BYTES = 25L * 1024L * 1024L

class MedicalRepository(
    private val context: Context,
    private val database: CompanionDatabase,
    private val api: ApiClient,
) {
    private val dao = database.companionDao()

    fun observeStudies(scope: String, serverIdentity: String): Flow<List<MedicalStudyEntity>> =
        dao.observeMedicalStudies(scope, serverIdentity)
    fun observeStudy(scope: String, serverIdentity: String, publicId: String): Flow<MedicalStudyEntity?> =
        dao.observeMedicalStudy(scope, serverIdentity, publicId)
    fun observePanels(scope: String, serverIdentity: String, studyId: String): Flow<List<LabPanelEntity>> =
        dao.observeLabPanels(scope, serverIdentity, studyId)
    fun observeResults(scope: String, serverIdentity: String, panelIds: List<String>): Flow<List<LabResultEntity>> =
        dao.observeLabResults(scope, serverIdentity, panelIds)
    fun observeDocuments(scope: String, serverIdentity: String, studyId: String): Flow<List<MedicalDocumentEntity>> =
        dao.observeMedicalDocuments(scope, serverIdentity, studyId)
    fun observeMarkers(scope: String, serverIdentity: String): Flow<List<LabMarkerEntity>> =
        dao.observeLabMarkers(scope, serverIdentity)
    fun observeHistory(scope: String, serverIdentity: String, key: String, period: String): Flow<MedicalHistoryCacheEntity?> =
        dao.observeMedicalHistory(scope, serverIdentity, key, period)
    fun observeDuplicates(scope: String, serverIdentity: String): Flow<List<MedicalDuplicateCandidateEntity>> =
        dao.observeMedicalDuplicates(scope, serverIdentity)

    suspend fun createStudy(
        scope: String,
        serverIdentity: String,
        title: String,
        studyType: String,
        studyDate: String,
        laboratoryName: String?,
        timezone: String?,
        notes: String?,
    ): String {
        require(title.isNotBlank() && studyDate.isNotBlank())
        val now = Instant.now().toString(); val publicId = UUID.randomUUID().toString()
        val entity = MedicalStudyEntity(
            scope, serverIdentity, publicId, studyType, title.trim().take(240),
            laboratoryName?.trim()?.takeIf { it.isNotEmpty() }, null, studyDate, null,
            timezone, notes?.trim()?.takeIf { it.isNotEmpty() }, "draft", "mobile",
            0, 1, "pending", now, now,
        )
        database.withTransaction {
            dao.upsertMedicalStudy(entity)
            enqueue(scope, serverIdentity, "study_create", publicId, null, studyPayload(entity, creating = true))
        }
        return publicId
    }

    suspend fun editStudy(scope: String, serverIdentity: String, publicId: String, title: String, notes: String?) {
        val current = dao.medicalStudy(scope, serverIdentity, publicId) ?: return
        val updated = current.copy(
            title = title.trim().take(240), notes = notes?.trim()?.takeIf { it.isNotEmpty() },
            localRevision = current.localRevision + 1, syncStatus = "pending", updatedAt = Instant.now().toString(),
        )
        database.withTransaction {
            dao.upsertMedicalStudy(updated)
            enqueue(scope, serverIdentity, if (current.revision == 0) "study_create" else "study_patch",
                publicId, null, studyPayload(updated, creating = current.revision == 0))
        }
    }

    suspend fun archiveStudy(scope: String, serverIdentity: String, publicId: String) {
        val current = dao.medicalStudy(scope, serverIdentity, publicId) ?: return
        val updated = current.copy(state = "archived", localRevision = current.localRevision + 1,
            syncStatus = "pending", updatedAt = Instant.now().toString())
        database.withTransaction {
            dao.upsertMedicalStudy(updated)
            if (current.revision == 0) {
                enqueue(scope, serverIdentity, "study_create", publicId, null, studyPayload(updated, true))
            } else {
                enqueue(scope, serverIdentity, "study_archive", publicId, null,
                    buildJsonObject { put("base_revision", current.revision) })
            }
        }
    }

    suspend fun completeStudy(scope: String, serverIdentity: String, publicId: String) {
        val current = dao.medicalStudy(scope, serverIdentity, publicId) ?: return
        val updated = current.copy(state = "complete", localRevision = current.localRevision + 1,
            syncStatus = "pending", updatedAt = Instant.now().toString())
        database.withTransaction {
            dao.upsertMedicalStudy(updated)
            enqueue(scope, serverIdentity, if (current.revision == 0) "study_create" else "study_patch",
                publicId, null, studyPayload(updated, creating = current.revision == 0))
        }
    }

    suspend fun addResult(
        scope: String,
        serverIdentity: String,
        studyId: String,
        panelName: String,
        displayName: String,
        valueType: String,
        originalValue: String,
        numericValue: String?,
        unit: String?,
        referenceLower: String?,
        referenceUpper: String?,
        sourceStatus: String,
    ): String {
        val now = Instant.now().toString(); val panelId = UUID.randomUUID().toString(); val resultId = UUID.randomUUID().toString()
        val panel = LabPanelEntity(scope, serverIdentity, panelId, studyId, panelName.trim().take(200), 0,
            "mobile", 0, "pending", now, now)
        val result = LabResultEntity(
            scope, serverIdentity, resultId, panelId, displayName.trim().take(200), null,
            valueType, originalValue.trim().take(500), numericValue, "equal", unit, null,
            referenceLower, referenceUpper, null, sourceStatus, "not_computable", null, null,
            null, 0, "mobile", 0, 1, "pending", now, now,
        )
        val payload = buildJsonObject {
            put("public_id", resultId); put("panel_name", panel.name); put("display_name", result.displayName)
            put("value_type", valueType); put("original_value", result.originalValue)
            numericValue?.let { put("numeric_value", it) }; put("comparator", "equal")
            unit?.let { put("original_unit", it) }; referenceLower?.let { put("reference_lower", it) }
            referenceUpper?.let { put("reference_upper", it) }; put("source_status", sourceStatus); put("source", "mobile")
        }
        database.withTransaction {
            dao.upsertLabPanel(panel); dao.upsertLabResult(result)
            enqueue(scope, serverIdentity, "result_create", resultId, studyId, payload)
        }
        return resultId
    }

    suspend fun editResult(
        scope: String,
        serverIdentity: String,
        publicId: String,
        originalValue: String,
        numericValue: String?,
        unit: String?,
        referenceLower: String?,
        referenceUpper: String?,
        sourceStatus: String,
        correctionReason: String?,
    ) {
        val current = dao.labResult(scope, serverIdentity, publicId) ?: return
        val updated = current.copy(originalValue = originalValue.trim().take(500), numericValue = numericValue,
            originalUnit = unit, referenceLower = referenceLower, referenceUpper = referenceUpper,
            sourceStatus = sourceStatus, derivedRangeStatus = MedicalRules.derivedRangeStatus(
                current.valueType, numericValue, referenceLower, referenceUpper, current.comparator,
            ), localRevision = current.localRevision + 1, syncStatus = "pending", updatedAt = Instant.now().toString())
        val snapshot = buildJsonObject {
            put("original_value", current.originalValue); current.numericValue?.let { put("numeric_value", it) }
            current.originalUnit?.let { put("original_unit", it) }; put("source_status", current.sourceStatus)
        }
        val panel = dao.labPanel(scope, serverIdentity, current.panelPublicId)
        val payload = resultPayload(updated, if (current.revision == 0) panel?.name else null, current.revision, correctionReason)
        database.withTransaction {
            dao.upsertLabResultRevision(LabResultRevisionEntity(scope, serverIdentity, publicId,
                current.localRevision + 1, snapshot.toString(), correctionReason, "mobile", Instant.now().toString()))
            dao.upsertLabResult(updated)
            enqueue(scope, serverIdentity, if (current.revision == 0) "result_create" else "result_patch",
                publicId, panel?.studyPublicId, payload)
        }
    }

    suspend fun deleteResult(scope: String, serverIdentity: String, publicId: String) {
        val current = dao.labResult(scope, serverIdentity, publicId) ?: return
        database.withTransaction {
            if (current.revision == 0) {
                dao.pendingMedicalOperationsForEntity(scope, serverIdentity, publicId).forEach {
                    dao.deleteMedicalOperation(scope, serverIdentity, it.operationId)
                }
            } else {
                enqueue(scope, serverIdentity, "result_delete", publicId, null,
                    buildJsonObject { put("base_revision", current.revision) })
            }
            dao.deleteLabResultRevisions(scope, serverIdentity, listOf(publicId))
            dao.deleteLabResult(scope, serverIdentity, publicId)
        }
    }

    suspend fun attachDocument(
        scope: String,
        serverIdentity: String,
        studyId: String,
        uri: Uri,
        filename: String,
        mimeType: String,
    ): String {
        require(mimeType in setOf("application/pdf", "image/jpeg", "image/png", "application/json", "text/csv"))
        val resolver = context.contentResolver
        val persisted = runCatching {
            resolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION); true
        }.getOrDefault(false)
        val directory = File(context.noBackupFilesDir, "medical_uploads/${scopeHash(scope)}").apply { mkdirs() }
        val tempName = "${UUID.randomUUID()}.upload"; val target = File(directory, tempName)
        var size = 0L; val digest = MessageDigest.getInstance("SHA-256")
        try {
            resolver.openInputStream(uri)?.use { input -> target.outputStream().use { output ->
                val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                while (true) {
                    val read = input.read(buffer); if (read < 0) break
                    size += read; require(size <= MAX_DOCUMENT_BYTES) { "document_too_large" }
                    digest.update(buffer, 0, read); output.write(buffer, 0, read)
                }
            } } ?: error("document_unavailable")
        } catch (error: Exception) { target.delete(); throw error }
        val now = Instant.now().toString(); val publicId = UUID.randomUUID().toString()
        val hash = digest.digest().joinToString("") { "%02x".format(it) }
        val document = MedicalDocumentEntity(scope, serverIdentity, publicId, studyId, "original",
            sanitizeFilename(filename), mimeType, size, hash, "available", uri.toString(), persisted,
            tempName, "mobile", 0, "pending", now)
        database.withTransaction {
            dao.upsertMedicalDocument(document)
            enqueue(scope, serverIdentity, "document_upload", publicId, studyId, buildJsonObject {
                put("filename", document.originalFilename); put("mime_type", mimeType); put("temp_file", tempName)
            })
        }
        return publicId
    }

    suspend fun deleteDocument(scope: String, serverIdentity: String, publicId: String) {
        val current = dao.medicalDocument(scope, serverIdentity, publicId) ?: return
        database.withTransaction {
            if (current.revision == 0) {
                dao.pendingMedicalOperationsForEntity(scope, serverIdentity, publicId).forEach {
                    dao.deleteMedicalOperation(scope, serverIdentity, it.operationId)
                }
            } else {
                enqueue(scope, serverIdentity, "document_delete", publicId, current.studyPublicId,
                    buildJsonObject { put("base_revision", current.revision); put("confirmed", true) })
            }
            dao.deleteMedicalDocument(scope, serverIdentity, publicId)
        }
        current.uploadTempFileName?.let { File(context.noBackupFilesDir,
            "medical_uploads/${scopeHash(scope)}/$it").delete() }
        File(sharedDocumentDirectory(scope), "${current.publicId}${extensionFor(current.mimeType)}").delete()
    }

    suspend fun explicitShareIntent(scope: String, serverIdentity: String, publicId: String): Intent {
        val document = dao.medicalDocument(scope, serverIdentity, publicId) ?: error("document_not_found")
        val directory = sharedDocumentDirectory(scope).apply { mkdirs() }
        val target = File(directory, "${document.publicId}${extensionFor(document.mimeType)}")
        val existing = if (target.isFile()) fileDigest(target) else null
        if (existing == null || existing.first != document.sha256 || existing.second != document.sizeBytes) {
            target.delete()
            val partial = File(directory, "${document.publicId}.partial").also { it.delete() }
            try {
                val localName = document.uploadTempFileName
                if (localName != null) {
                    val source = File(context.noBackupFilesDir, "medical_uploads/${scopeHash(scope)}/$localName")
                    require(source.isFile) { "document_access_lost" }
                    source.copyTo(partial, overwrite = true)
                } else {
                    api.downloadMedicalDocument(publicId, partial)
                }
                val downloaded = fileDigest(partial)
                require(downloaded.first == document.sha256 && downloaded.second == document.sizeBytes) {
                    "document_integrity_mismatch"
                }
                require(partial.renameTo(target)) { "document_finalize_failed" }
            } catch (error: Exception) {
                partial.delete()
                throw error
            }
        }
        val uri = FileProvider.getUriForFile(
            context, "${context.packageName}.medical-documents", target,
        )
        return Intent(Intent.ACTION_SEND).apply {
            type = document.mimeType
            putExtra(Intent.EXTRA_STREAM, uri)
            clipData = android.content.ClipData.newRawUri("Documento médico", uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
    }

    suspend fun permanentlyDeleteStudy(scope: String, serverIdentity: String, publicId: String) {
        val current = dao.medicalStudy(scope, serverIdentity, publicId) ?: return
        val panels = dao.labPanels(scope, serverIdentity, publicId)
        val results = if (panels.isEmpty()) emptyList() else dao.labResults(scope, serverIdentity, panels.map { it.publicId })
        val documents = dao.medicalDocuments(scope, serverIdentity, publicId)
        database.withTransaction {
            if (current.revision == 0) {
                dao.pendingMedicalOperationsForEntity(scope, serverIdentity, publicId).forEach {
                    dao.deleteMedicalOperation(scope, serverIdentity, it.operationId)
                }
            } else {
                enqueue(scope, serverIdentity, "study_delete", publicId, null, buildJsonObject {
                    put("base_revision", current.revision); put("confirmed", true); put("impact_acknowledged", true)
                })
            }
            documents.forEach { document ->
                dao.pendingMedicalOperationsForEntity(scope, serverIdentity, document.publicId).forEach {
                    dao.deleteMedicalOperation(scope, serverIdentity, it.operationId)
                }
            }
            results.forEach { result ->
                dao.pendingMedicalOperationsForEntity(scope, serverIdentity, result.publicId).forEach {
                    dao.deleteMedicalOperation(scope, serverIdentity, it.operationId)
                }
            }
            if (results.isNotEmpty()) dao.deleteLabResultRevisions(scope, serverIdentity, results.map { it.publicId })
            if (panels.isNotEmpty()) dao.deleteLabResultsForPanels(scope, serverIdentity, panels.map { it.publicId })
            dao.deleteLabPanelsForStudy(scope, serverIdentity, publicId)
            dao.deleteMedicalDocumentsForStudy(scope, serverIdentity, publicId)
            dao.deleteMedicalStudy(scope, serverIdentity, publicId)
        }
        documents.forEach { document ->
            document.uploadTempFileName?.let {
                File(context.noBackupFilesDir, "medical_uploads/${scopeHash(scope)}/$it").delete()
            }
            File(sharedDocumentDirectory(scope), "${document.publicId}${extensionFor(document.mimeType)}").delete()
        }
    }

    suspend fun refresh(scope: String, serverIdentity: String) {
        val root = api.medicalStudies(); val items = root["items"]?.jsonArray.orEmpty()
        items.forEach { item ->
            val id = item.jsonObject.string("public_id") ?: return@forEach
            storeStudyDetail(scope, serverIdentity, api.medicalStudy(id))
        }
        val markers = api.labMarkers()["items"]?.jsonArray.orEmpty().mapNotNull { value ->
            val row = value.jsonObject; val key = row.string("canonical_key") ?: return@mapNotNull null
            LabMarkerEntity(scope, serverIdentity, key, row.string("display_name").orEmpty(),
                row["aliases"]?.toString() ?: "[]", row["common_units"]?.toString() ?: "[]", Instant.now().toString())
        }
        dao.upsertLabMarkers(markers)
    }

    suspend fun refreshHistory(scope: String, serverIdentity: String, key: String, period: String) {
        val response = api.labHistory(key, period)
        dao.upsertMedicalHistory(MedicalHistoryCacheEntity(scope, serverIdentity, key, period,
            response["points"]?.toString() ?: "[]", response.bool("series_comparable") ?: false,
            response.string("comparison_notice"), Instant.now().toString()))
    }

    suspend fun synchronize(scope: String, serverIdentity: String) {
        for (operation in dao.readyMedicalOperations(scope, serverIdentity, System.currentTimeMillis())) {
            try {
                when (operation.operationType) {
                    "study_create" -> api.createMedicalStudy(operation.payloadJson.jsonObject(), operation.idempotencyKey)
                    "study_patch" -> api.patchMedicalStudy(operation.entityPublicId, operation.payloadJson.jsonObject(), operation.idempotencyKey)
                    "study_archive" -> api.archiveMedicalStudy(operation.entityPublicId, operation.payloadJson.jsonObject(), operation.idempotencyKey)
                    "study_delete" -> api.deleteMedicalStudy(operation.entityPublicId, operation.payloadJson.jsonObject(), operation.idempotencyKey)
                    "result_create" -> api.createMedicalResult(operation.parentPublicId.orEmpty(), operation.payloadJson.jsonObject(), operation.idempotencyKey)
                    "result_patch" -> api.patchMedicalResult(operation.entityPublicId, operation.payloadJson.jsonObject(), operation.idempotencyKey)
                    "result_delete" -> api.deleteMedicalResult(operation.entityPublicId, operation.payloadJson.jsonObject(), operation.idempotencyKey)
                    "document_upload" -> {
                        val payload = operation.payloadJson.jsonObject(); val name = payload.string("temp_file").orEmpty()
                        val file = File(context.noBackupFilesDir, "medical_uploads/${scopeHash(scope)}/$name")
                        api.uploadMedicalDocument(operation.parentPublicId.orEmpty(), file,
                            payload.string("filename").orEmpty(), payload.string("mime_type").orEmpty(), operation.idempotencyKey)
                        file.delete()
                    }
                    "document_delete" -> api.deleteMedicalDocument(operation.entityPublicId, operation.payloadJson.jsonObject(), operation.idempotencyKey)
                }
                dao.deleteMedicalOperation(scope, serverIdentity, operation.operationId)
            } catch (failure: AppFailure) {
                dao.upsertMedicalOperation(operation.copy(attemptCount = operation.attemptCount + 1,
                    notBeforeEpochMs = System.currentTimeMillis() + 30_000L, lastErrorCode = failure.code.name))
                if (failure.retryable) throw failure
            }
        }
        refresh(scope, serverIdentity)
    }

    fun cleanupScopeFiles(scope: String) {
        File(context.noBackupFilesDir, "medical_uploads/${scopeHash(scope)}").deleteRecursively()
        sharedDocumentDirectory(scope).deleteRecursively()
    }

    fun cleanupSharedDocuments() {
        File(context.cacheDir, "medical_documents").deleteRecursively()
    }

    private suspend fun storeStudyDetail(scope: String, serverIdentity: String, row: JsonObject) {
        val now = Instant.now().toString(); val id = row.string("public_id") ?: return
        val study = MedicalStudyEntity(scope, serverIdentity, id, row.string("study_type").orEmpty(),
            row.string("title").orEmpty(), row.string("laboratory_name"), row.string("professional_name"),
            row.string("study_date").orEmpty(), row.string("issued_date"), row.string("timezone"), row.string("notes"),
            row.string("state") ?: "complete", row.string("source") ?: "server", row.int("revision") ?: 1,
            0, "synced", row.string("created_at") ?: now, row.string("updated_at") ?: now)
        val panels = row["panels"]?.jsonArray.orEmpty().mapNotNull { value ->
            val panel = value.jsonObject; val panelId = panel.string("public_id") ?: return@mapNotNull null
            LabPanelEntity(scope, serverIdentity, panelId, id, panel.string("name").orEmpty(),
                panel.int("display_order") ?: 0, panel.string("source") ?: "server", panel.int("revision") ?: 1,
                "synced", panel.string("created_at") ?: now, panel.string("updated_at") ?: now)
        }
        val results = row["panels"]?.jsonArray.orEmpty().flatMap { panelValue ->
            val panel = panelValue.jsonObject; val panelId = panel.string("public_id").orEmpty()
            panel["results"]?.jsonArray.orEmpty().mapNotNull { value -> resultEntity(scope, serverIdentity, panelId, value.jsonObject, now) }
        }
        val documents = row["documents"]?.jsonArray.orEmpty().mapNotNull { value ->
            val document = value.jsonObject; val documentId = document.string("public_id") ?: return@mapNotNull null
            MedicalDocumentEntity(scope, serverIdentity, documentId, id, document.string("document_type") ?: "original",
                document.string("filename").orEmpty(), document.string("mime_type").orEmpty(), document.long("size_bytes") ?: 0,
                document.string("sha256").orEmpty(), document.string("availability") ?: "metadata_only", null, false, null,
                document.string("source") ?: "server", document.int("revision") ?: 1, "synced", document.string("created_at") ?: now)
        }
        database.withTransaction {
            dao.upsertMedicalStudy(study); dao.upsertLabPanels(panels); dao.upsertLabResults(results); dao.upsertMedicalDocuments(documents)
        }
    }

    private fun resultEntity(scope: String, serverIdentity: String, panelId: String, row: JsonObject, now: String): LabResultEntity? {
        val id = row.string("public_id") ?: return null
        return LabResultEntity(scope, serverIdentity, id, panelId, row.string("display_name").orEmpty(), row.string("canonical_key"),
            row.string("value_type") ?: "unknown", row.string("original_value").orEmpty(), row.string("numeric_value"),
            row.string("comparator") ?: "none", row.string("original_unit"), row.string("canonical_unit"),
            row.string("reference_lower"), row.string("reference_upper"), row.string("reference_text"),
            row.string("source_status") ?: "not_provided", row.string("derived_range_status") ?: "not_computable",
            row.string("method"), row.string("specimen"), row.string("notes"), row.int("display_order") ?: 0,
            row.string("source") ?: "server", row.int("revision") ?: 1, 0, "synced",
            row.string("created_at") ?: now, row.string("updated_at") ?: now)
    }

    private suspend fun enqueue(scope: String, serverIdentity: String, type: String, entityId: String, parentId: String?, payload: JsonObject) {
        val existing = dao.pendingMedicalOperationsForEntity(scope, serverIdentity, entityId)
        val reusable = existing.firstOrNull {
            (it.operationType == "study_create" && type in setOf("study_create", "study_patch")) ||
                (it.operationType == "result_create" && type in setOf("result_create", "result_patch"))
        }
        existing.filter { it.operationId != reusable?.operationId }.forEach { dao.deleteMedicalOperation(scope, serverIdentity, it.operationId) }
        val raw = payload.toString(); val now = Instant.now().toString()
        dao.upsertMedicalOperation(MedicalOperationEntity(scope, serverIdentity,
            reusable?.operationId ?: UUID.randomUUID().toString(), reusable?.operationType ?: type,
            entityId, parentId, reusable?.idempotencyKey ?: UUID.randomUUID().toString(), raw, sha256(raw),
            "pending", 0, 0, reusable?.createdAt ?: now, null))
    }

    private fun studyPayload(value: MedicalStudyEntity, creating: Boolean) = buildJsonObject {
        if (creating) put("public_id", value.publicId) else put("base_revision", value.revision)
        put("study_type", value.studyType); put("title", value.title); value.laboratoryName?.let { put("laboratory_name", it) }
        value.professionalName?.let { put("professional_name", it) }; put("study_date", value.studyDate)
        value.issuedDate?.let { put("issued_date", it) }; value.timezone?.let { put("timezone", it) }
        value.notes?.let { put("notes", it) }; put("state", value.state)
        if (creating) put("source", "mobile")
    }

    private fun resultPayload(value: LabResultEntity, panelName: String?, baseRevision: Int, reason: String?) = buildJsonObject {
        if (panelName != null) { put("public_id", value.publicId); put("panel_name", panelName) }
        else put("base_revision", baseRevision)
        put("display_name", value.displayName); value.canonicalKey?.let { put("canonical_key", it) }
        put("value_type", value.valueType); put("original_value", value.originalValue)
        value.numericValue?.let { put("numeric_value", it) }; put("comparator", value.comparator)
        value.originalUnit?.let { put("original_unit", it) }; value.referenceLower?.let { put("reference_lower", it) }
        value.referenceUpper?.let { put("reference_upper", it) }; value.referenceText?.let { put("reference_text", it) }
        put("source_status", value.sourceStatus); value.method?.let { put("method", it) }; value.specimen?.let { put("specimen", it) }
        value.notes?.let { put("notes", it) }; put("display_order", value.displayOrder)
        if (panelName != null) put("source", "mobile") else reason?.let { put("correction_reason", it) }
    }

    private fun String.jsonObject() = api.json.parseToJsonElement(this).jsonObject
    private fun JsonObject.string(key: String) = this[key]?.jsonPrimitive?.contentOrNull
    private fun JsonObject.int(key: String) = this[key]?.jsonPrimitive?.intOrNull
    private fun JsonObject.long(key: String) = this[key]?.jsonPrimitive?.longOrNull
    private fun JsonObject.bool(key: String) = this[key]?.jsonPrimitive?.booleanOrNull
    private fun sha256(value: String) = MessageDigest.getInstance("SHA-256").digest(value.toByteArray())
        .joinToString("") { "%02x".format(it) }
    private fun scopeHash(scope: String) = sha256(scope).take(24)
    private fun sharedDocumentDirectory(scope: String) = File(context.cacheDir, "medical_documents/${scopeHash(scope)}")
    private fun extensionFor(mimeType: String) = when (mimeType) {
        "application/pdf" -> ".pdf"
        "image/jpeg" -> ".jpg"
        "image/png" -> ".png"
        "application/json" -> ".json"
        "text/csv" -> ".csv"
        else -> ".bin"
    }
    private fun fileDigest(file: File): Pair<String, Long> {
        val digest = MessageDigest.getInstance("SHA-256")
        var size = 0L
        file.inputStream().use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                size += read
                require(size <= MAX_DOCUMENT_BYTES) { "document_too_large" }
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) } to size
    }
    private fun sanitizeFilename(value: String): String = value
        .substringAfterLast('/').substringAfterLast('\\')
        .filter { !it.isISOControl() && it !in "\"';" }
        .trim().take(255).ifBlank { "documento" }
}
