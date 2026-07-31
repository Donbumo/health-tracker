package io.healthtracker.companion.core.portability

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import io.healthtracker.companion.HealthTrackerApplication
import io.healthtracker.companion.core.database.CompanionDatabase
import io.healthtracker.companion.core.database.PortableDownloadEntity
import io.healthtracker.companion.core.database.PortableExportJobEntity
import io.healthtracker.companion.core.database.PortableImportDecisionEntity
import io.healthtracker.companion.core.database.PortableImportJobEntity
import io.healthtracker.companion.core.database.PortableImportPlanEntity
import io.healthtracker.companion.core.database.PortableInspectionEntity
import io.healthtracker.companion.core.model.AppFailure
import io.healthtracker.companion.core.network.ApiClient
import java.io.File
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.add

data class PortableExportRequest(
    val sections: Set<String>,
    val dateFrom: String? = null,
    val dateTo: String? = null,
    val includeAttachments: Boolean = false,
    val includeMedicalAttachments: Boolean = false,
    val includeIdentifiableProfile: Boolean = false,
)

class PortabilityRepository(
    private val context: Context,
    private val database: CompanionDatabase,
    private val api: ApiClient,
) {
    private val dao = database.companionDao()
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }
    private val queueMutex = Mutex()
    val fileStore = PortableFileStore(context).also { it.cleanup() }

    fun observeExports(scope: String): Flow<List<PortableExportJobEntity>> = dao.observePortableExports(scope)
    fun observeImports(scope: String): Flow<List<PortableImportJobEntity>> = dao.observePortableImports(scope)
    fun observeInspections(scope: String): Flow<List<PortableInspectionEntity>> = dao.observePortableInspections(scope)
    fun observePlans(scope: String): Flow<List<PortableImportPlanEntity>> = dao.observePortableImportPlans(scope)
    fun observeDownloads(scope: String): Flow<List<PortableDownloadEntity>> = dao.observePortableDownloads(scope)
    fun observeDecisions(scope: String, importId: String): Flow<List<PortableImportDecisionEntity>> = dao.observePortableDecisions(scope, importId)

    suspend fun queueExport(scope: String, request: PortableExportRequest): String = queueMutex.withLock {
        PortabilityPolicy.validateExportRequest(request)
        val localId = UUID.randomUUID().toString()
        val key = UUID.randomUUID().toString()
        val payload = exportPayload(request)
        dao.pendingPortableExports(scope).firstOrNull { it.requestJson == payload.toString() }?.let { return@withLock it.publicId }
        dao.upsertPortableExport(PortableExportJobEntity(
            accountScope = scope, publicId = localId, state = "requested", sectionsJson = payload["sections"].toString(),
            countsJson = "{}", sha256 = null, sizeBytes = null, requestJson = payload.toString(),
            idempotencyKey = key, revision = 1, syncStatus = "pending", createdAt = Instant.now().toString(),
            expiresAt = null, completedAt = null, errorCode = null,
        ))
        PortabilityScheduler.enqueue(context)
        localId
    }

    suspend fun submitExport(scope: String, localId: String): String {
        val local = dao.portableExport(scope, localId) ?: return localId
        val response = api.createPortableExport(json.parseToJsonElement(local.requestJson).jsonObject, local.idempotencyKey)
        val server = response.toExportEntity(scope, local.requestJson, local.idempotencyKey)
        dao.upsertPortableExport(server)
        if (server.publicId != localId) dao.deletePortableExport(scope, localId)
        return server.publicId
    }

    suspend fun refreshExports(scope: String) {
        val items = api.portableExports()["items"]?.jsonArray ?: JsonArray(emptyList())
        items.forEach { element ->
            val value = element.jsonObject
            val existing = dao.portableExport(scope, value.text("export_id"))
            dao.upsertPortableExport(value.toExportEntity(
                scope,
                existing?.requestJson ?: "{}",
                existing?.idempotencyKey ?: UUID.randomUUID().toString(),
            ))
        }
    }

    suspend fun refreshImports(scope: String) {
        val items = api.portableImports()["items"]?.jsonArray ?: JsonArray(emptyList())
        items.forEach { element ->
            val value = element.jsonObject
            val existing = dao.portableImport(scope, value.text("import_id"))
            val entity = value.toImportEntity(
                scope, existing?.sourceUri, existing?.uriPermissionPersisted ?: false,
                existing?.uploadIdempotencyKey ?: UUID.randomUUID().toString(),
                existing?.applyIdempotencyKey ?: UUID.randomUUID().toString(),
            )
            dao.upsertPortableImport(entity)
            persistServerInspectionAndPlan(scope, entity.publicId, value)
        }
    }

    suspend fun download(scope: String, exportId: String): File {
        val job = dao.portableExport(scope, exportId) ?: error("export_not_found")
        val expectedHash = requireNotNull(job.sha256) { "export_hash_missing" }
        val partial = fileStore.partial(scope, exportId)
        partial.delete()
        dao.upsertPortableDownload(PortableDownloadEntity(scope, exportId, partial.name, null, expectedHash,
            null, job.sizeBytes, 0, "downloading", Instant.now().toString(), null))
        try {
            val downloaded = api.downloadPortableExport(exportId, partial)
            if (downloaded.sha256 != expectedHash || (job.sizeBytes != null && downloaded.sizeBytes != job.sizeBytes)) {
                partial.delete(); error("download_hash_mismatch")
            }
            val final = fileStore.finalize(scope, exportId, expectedHash, job.sizeBytes)
            dao.upsertPortableDownload(PortableDownloadEntity(scope, exportId, null, final.name, expectedHash,
                downloaded.sha256, job.sizeBytes, downloaded.sizeBytes, "verified", Instant.now().toString(), null))
            return final
        } catch (error: Exception) {
            partial.delete()
            dao.upsertPortableDownload(PortableDownloadEntity(scope, exportId, null, null, expectedHash,
                null, job.sizeBytes, 0, "failed", Instant.now().toString(), diagnosticCode(error)))
            throw error
        }
    }

    suspend fun deleteLocalExport(scope: String, exportId: String) {
        fileStore.delete(scope, exportId)
        dao.upsertPortableDownload(PortableDownloadEntity(scope, exportId, null, null,
            dao.portableExport(scope, exportId)?.sha256 ?: "", null, null, 0, "deleted", Instant.now().toString(), null))
    }

    suspend fun deleteServerExport(scope: String, exportId: String) {
        api.deletePortableExport(exportId)
        dao.portableExport(scope, exportId)?.let { dao.upsertPortableExport(it.copy(state = "deleted", syncStatus = "synced")) }
    }

    suspend fun cancelExport(scope: String, exportId: String) {
        val job = dao.portableExport(scope, exportId) ?: return
        if (job.syncStatus == "pending") {
            dao.deletePortableExport(scope, exportId)
            fileStore.delete(scope, exportId)
        } else {
            deleteServerExport(scope, exportId)
        }
    }

    fun shareIntent(scope: String, exportId: String): Intent = Intent(Intent.ACTION_SEND).apply {
        type = PORTABLE_MIME
        putExtra(Intent.EXTRA_STREAM, fileStore.shareUri(scope, exportId))
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }

    suspend fun inspectLocal(scope: String, uri: Uri, persistablePermission: Boolean): String {
        val inspection = PortablePackageInspector(context.contentResolver).inspect(uri)
        val localId = UUID.randomUUID().toString()
        val uploadKey = UUID.randomUUID().toString()
        val applyKey = UUID.randomUUID().toString()
        dao.upsertPortableImport(PortableImportJobEntity(
            accountScope = scope, publicId = localId, state = "local_inspection_ready",
            sectionsJson = listJson(inspection.sections),
            countsJson = mapJson(inspection.counts), sourceUri = uri.toString(), uriPermissionPersisted = persistablePermission,
            packageSha256 = inspection.packageSha256, sizeBytes = inspection.sizeBytes,
            uploadIdempotencyKey = uploadKey, applyIdempotencyKey = applyKey, revision = 1,
            syncStatus = "pending_upload", createdAt = Instant.now().toString(), expiresAt = null,
            completedAt = null, errorCode = null,
        ))
        dao.upsertPortableInspection(PortableInspectionEntity(
            scope, localId, inspection.packageSha256, inspection.format, inspection.formatVersion,
            listJson(inspection.sections), mapJson(inspection.counts), mapJson(inspection.files),
            listJson(inspection.warnings), inspection.integrity, inspection.authenticity,
            Instant.now().toString(),
        ))
        PortabilityScheduler.enqueue(context)
        return localId
    }

    suspend fun uploadImport(scope: String, localId: String): String {
        val local = dao.portableImport(scope, localId) ?: return localId
        val uri = local.sourceUri?.let(Uri::parse) ?: error("source_uri_missing")
        val temporary = File(context.cacheDir, "portability-upload/${UUID.randomUUID()}.htpack")
        temporary.parentFile?.mkdirs()
        try {
            context.contentResolver.openInputStream(uri)?.use { input ->
                temporary.outputStream().use { output ->
                    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                    var copied = 0L
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        copied += read
                        if (copied > 50L * 1024 * 1024) error("package_too_large")
                        output.write(buffer, 0, read)
                    }
                }
            } ?: error("source_uri_unavailable")
            val sections = json.parseToJsonElement(local.sectionsJson).jsonArray.map { it.jsonPrimitive.content }
            val response = api.inspectPortablePackage(temporary, sections)
            val server = response.toImportEntity(scope, local.sourceUri, local.uriPermissionPersisted,
                local.uploadIdempotencyKey, local.applyIdempotencyKey)
            dao.upsertPortableImport(server)
            persistServerInspectionAndPlan(scope, server.publicId, response)
            if (server.publicId != localId) dao.deletePortableImport(scope, localId)
            return server.publicId
        } finally {
            temporary.delete()
        }
    }

    suspend fun saveDecision(scope: String, importId: String, section: String, sourceId: String, strategy: String) {
        require(strategy in setOf("skip_existing", "import_as_new", "use_destination", "update_when_identical_lineage", "require_manual_resolution"))
        dao.upsertPortableImportDecision(PortableImportDecisionEntity(scope, importId, section, sourceId, strategy, Instant.now().toString()))
    }

    suspend fun applyImport(scope: String, importId: String, decisions: List<PortableImportDecisionEntity>): JsonObject {
        val job = dao.portableImport(scope, importId) ?: error("import_not_found")
        val plan = dao.portableImportPlan(scope, importId) ?: error("import_plan_missing")
        val payload = buildJsonObject {
            put("confirmed", true)
            put("plan_revision", plan.revision)
            put("decisions", buildJsonArray {
                decisions.forEach { decision -> add(buildJsonObject {
                    put("section", decision.section); put("source_public_id", decision.sourcePublicId); put("strategy", decision.strategy)
                }) }
            })
        }
        val result = api.applyPortableImport(importId, payload, job.applyIdempotencyKey)
        dao.upsertPortableImport(job.copy(state = result.text("state"), syncStatus = "synced",
            completedAt = result["completed_at"]?.jsonPrimitive?.contentOrNull, errorCode = null))
        return result
    }

    suspend fun applyImport(scope: String, importId: String): JsonObject =
        applyImport(scope, importId, observeDecisions(scope, importId).first())

    suspend fun queueApply(scope: String, importId: String) {
        val job = dao.portableImport(scope, importId) ?: error("import_not_found")
        dao.upsertPortableImport(job.copy(state = "awaiting_confirmation", syncStatus = "pending_apply", errorCode = null))
        PortabilityScheduler.enqueue(context)
    }

    suspend fun resolveConflictsSafely(scope: String, importId: String) {
        val plan = dao.portableImportPlan(scope, importId) ?: error("import_plan_missing")
        val rows = json.parseToJsonElement(plan.recordsJson).jsonArray
        rows.forEach { element ->
            val row = element.jsonObject
            if (row.text("classification") in setOf("conflict", "duplicate_candidate", "broken_reference")) {
                saveDecision(scope, importId, row.text("section"), row.text("source_public_id"), "use_destination")
            }
        }
    }

    suspend fun deleteServerImport(scope: String, importId: String) {
        api.deletePortableImport(importId)
        dao.deletePortableImport(scope, importId)
    }

    suspend fun deleteLocalImport(scope: String, importId: String) {
        val job = dao.portableImport(scope, importId) ?: return
        if (job.uriPermissionPersisted && job.sourceUri != null) {
            runCatching {
                context.contentResolver.releasePersistableUriPermission(
                    Uri.parse(job.sourceUri), Intent.FLAG_GRANT_READ_URI_PERMISSION,
                )
            }
        }
        dao.deletePortableImportDecisions(scope, importId)
        dao.deletePortableImportPlan(scope, importId)
        dao.deletePortableInspection(scope, importId)
        dao.deletePortableImport(scope, importId)
    }

    suspend fun processPending(scope: String) {
        var retryable: AppFailure? = null
        var terminal: Throwable? = null
        suspend fun attempt(block: suspend () -> Unit) {
            try {
                block()
            } catch (failure: AppFailure) {
                if (failure.retryable && retryable == null) retryable = failure
                else if (!failure.retryable && terminal == null) terminal = failure
            } catch (failure: Throwable) {
                if (terminal == null) terminal = failure
            }
        }
        dao.pendingPortableExports(scope).forEach { attempt { submitExport(scope, it.publicId); Unit } }
        dao.pendingPortableImports(scope).forEach { attempt { uploadImport(scope, it.publicId); Unit } }
        dao.pendingPortableApplies(scope).forEach { attempt { applyImport(scope, it.publicId); Unit } }
        retryable?.let { throw it }
        terminal?.let { throw it }
    }

    private suspend fun persistServerInspectionAndPlan(scope: String, importId: String, value: JsonObject) {
        val inspection = value["inspection"]?.jsonObject ?: return
        dao.upsertPortableInspection(PortableInspectionEntity(
            scope, importId, inspection.text("package_sha256"), inspection.text("format"), inspection.text("format_version"),
            inspection["sections"].toString(), inspection["counts"].toString(), inspection["files"].toString(),
            inspection["warnings"].toString(), inspection.text("integrity"), inspection.text("authenticity"), Instant.now().toString(),
        ))
        val plan = value["plan"]?.jsonObject ?: return
        dao.upsertPortableImportPlan(PortableImportPlanEntity(
            scope, importId, plan.text("plan_id"), plan["revision"]?.jsonPrimitive?.intOrNull ?: 1,
            plan["selected_sections"].toString(), plan["summary"].toString(), plan["records"].toString(),
            plan["warnings"].toString(), plan.text("expires_at"),
        ))
    }

    private fun exportPayload(request: PortableExportRequest) = buildJsonObject {
        put("format", PORTABLE_FORMAT)
        put("sections", buildJsonArray { request.sections.sorted().forEach { add(it) } })
        request.dateFrom?.let { put("date_from", it) }; request.dateTo?.let { put("date_to", it) }
        put("include_attachments", request.includeAttachments)
        put("include_medical_attachments", request.includeMedicalAttachments)
        put("include_identifiable_profile", request.includeIdentifiableProfile)
    }

    private fun JsonObject.toExportEntity(scope: String, requestJson: String, key: String) = PortableExportJobEntity(
        scope, text("export_id"), text("state"), this["sections"].toString(), this["counts"].toString(),
        this["sha256"]?.jsonPrimitive?.contentOrNull, this["size_bytes"]?.jsonPrimitive?.longOrNull,
        requestJson, key, this["revision"]?.jsonPrimitive?.intOrNull ?: 1, "synced", text("created_at"),
        this["expires_at"]?.jsonPrimitive?.contentOrNull, this["completed_at"]?.jsonPrimitive?.contentOrNull,
        this["error_code"]?.jsonPrimitive?.contentOrNull,
    )

    private fun JsonObject.toImportEntity(scope: String, uri: String?, persisted: Boolean, uploadKey: String, applyKey: String) = PortableImportJobEntity(
        scope, text("import_id"), text("state"), this["sections"].toString(), this["counts"].toString(),
        uri, persisted, this["sha256"]?.jsonPrimitive?.contentOrNull, this["size_bytes"]?.jsonPrimitive?.longOrNull,
        uploadKey, applyKey, this["revision"]?.jsonPrimitive?.intOrNull ?: 1, "synced", text("created_at"),
        this["expires_at"]?.jsonPrimitive?.contentOrNull, this["completed_at"]?.jsonPrimitive?.contentOrNull,
        this["error_code"]?.jsonPrimitive?.contentOrNull,
    )

    private fun JsonObject.text(name: String): String = this[name]?.jsonPrimitive?.contentOrNull.orEmpty()
    private fun mapJson(values: Map<String, Long>): String = buildJsonObject { values.forEach { (key, value) -> put(key, value) } }.toString()
    private fun listJson(values: List<String>): String = JsonArray(values.map(::JsonPrimitive)).toString()
    private fun diagnosticCode(error: Exception): String = when (error) {
        is AppFailure -> error.code.name.lowercase()
        is PortablePackageException -> error.code
        else -> "local_storage_error"
    }

}

object PortabilityScheduler {
    fun enqueue(context: Context) {
        val constraints = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            "health-tracker-portability",
            ExistingWorkPolicy.KEEP,
            OneTimeWorkRequestBuilder<PortabilityWorker>().setConstraints(constraints).build(),
        )
    }
}

class PortabilityWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val app = applicationContext as? HealthTrackerApplication ?: return Result.failure()
        val scope = app.container.preferences.values.first().accountScope ?: return Result.success()
        return try {
            app.container.portabilityRepository.processPending(scope)
            Result.success()
        } catch (failure: AppFailure) {
            if (failure.retryable) Result.retry() else Result.failure()
        } catch (_: Exception) {
            Result.failure()
        }
    }
}
