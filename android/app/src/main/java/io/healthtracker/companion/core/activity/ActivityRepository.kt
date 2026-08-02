package io.healthtracker.companion.core.activity

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import androidx.room.withTransaction
import io.healthtracker.companion.BuildConfig
import io.healthtracker.companion.core.database.*
import io.healthtracker.companion.core.model.AppErrorCode
import io.healthtracker.companion.core.model.AppFailure
import io.healthtracker.companion.core.network.ApiClient
import io.healthtracker.companion.core.security.PrivateFileNames
import java.io.File
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.serialization.json.*

const val MAX_ACTIVITY_IMPORT_BYTES = 10L * 1024L * 1024L
private val ACTIVITY_EXTENSIONS = setOf("fit", "gpx", "tcx")

data class LocalActivitySelection(
    val filename: String,
    val format: String,
    val sizeBytes: Long,
    val sha256: String,
    val permissionPersisted: Boolean,
)

object ActivityFileRules {
    fun formatFor(filename: String): String? = filename.substringAfterLast('.', "").lowercase()
        .takeIf { it in ACTIVITY_EXTENSIONS }

    fun shortHash(value: String): String = value.take(12)
}

class ActivityRepository(
    private val context: Context,
    private val database: CompanionDatabase,
    private val api: ApiClient,
) {
    private val dao = database.companionDao()

    fun observeImports(scope: String, identity: String): Flow<List<ActivityImportEntity>> = dao.observeActivityImports(scope, identity)
    fun observeActivities(scope: String, identity: String): Flow<List<ActivityEntity>> = dao.observeActivities(scope, identity)
    fun observeActivity(scope: String, identity: String, id: String): Flow<ActivityEntity?> = dao.observeActivity(scope, identity, id)
    fun observeLaps(scope: String, identity: String, id: String): Flow<List<ActivityLapEntity>> = dao.observeActivityLaps(scope, identity, id)
    fun observeSeriesMetadata(scope: String, identity: String, id: String): Flow<ActivitySeriesMetadataEntity?> = dao.observeActivitySeriesMetadata(scope, identity, id)
    fun observeRoute(scope: String, identity: String, id: String): Flow<ActivityRouteEntity?> = dao.observeActivityRoute(scope, identity, id)
    fun observeDuplicates(scope: String, identity: String): Flow<List<ActivityDuplicateCandidateEntity>> = dao.observeActivityDuplicates(scope, identity)
    fun observePlanLink(scope: String, identity: String, id: String): Flow<PlanActivityLinkEntity?> = dao.observePlanActivityLink(scope, identity, id)
    fun observeComparison(scope: String, identity: String, id: String): Flow<PlanActualComparisonEntity?> = dao.observePlanActualComparison(scope, identity, id)

    suspend fun selectFile(scope: String, identity: String, uri: Uri, filename: String, routePolicy: String, redactStartMeters: Int, redactEndMeters: Int): LocalActivitySelection {
        val safeName = filename.substringAfterLast('/').take(240)
        val format = ActivityFileRules.formatFor(safeName)
            ?: throw AppFailure(AppErrorCode.VALIDATION_ERROR, "Selecciona un archivo FIT, GPX o TCX.", false)
        require(routePolicy in setOf("keep", "drop", "redact"))
        require(redactStartMeters in 0..50_000 && redactEndMeters in 0..50_000)
        require(routePolicy == "redact" || redactStartMeters == 0 && redactEndMeters == 0)
        val resolver = context.contentResolver
        val permission = runCatching {
            resolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION); true
        }.getOrDefault(false)
        val id = UUID.randomUUID().toString(); val partialName = "$id.partial"
        val target = File(importDirectory(scope), partialName)
        val digest = MessageDigest.getInstance("SHA-256"); var size = 0L
        try {
            resolver.openInputStream(uri)?.use { input -> target.outputStream().use { output ->
                val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                while (true) {
                    val read = input.read(buffer); if (read < 0) break
                    size += read
                    if (size > MAX_ACTIVITY_IMPORT_BYTES) throw AppFailure(AppErrorCode.VALIDATION_ERROR, "El archivo supera 10 MB.", false)
                    digest.update(buffer, 0, read); output.write(buffer, 0, read)
                }
            } } ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "Ya no se puede abrir el archivo seleccionado.", false)
            if (size == 0L) throw AppFailure(AppErrorCode.VALIDATION_ERROR, "El archivo está vacío.", false)
        } catch (error: Exception) {
            target.delete()
            if (permission) release(uri)
            throw error
        }
        val hash = digest.digest().joinToString("") { "%02x".format(it) }; val now = Instant.now().toString()
        val entity = ActivityImportEntity(scope, identity, id, null, safeName, format, resolver.getType(uri), size,
            hash, uri.toString(), permission, partialName, routePolicy, redactStartMeters, redactEndMeters,
            "pending_upload", "[]", null, now, now)
        val operation = operation(entity)
        database.withTransaction { dao.upsertActivityImport(entity); dao.upsertActivityOperation(operation) }
        ActivityImportScheduler.enqueue(context, scope, identity, id)
        return LocalActivitySelection(safeName, format, size, hash, permission)
    }

    suspend fun uploadAndInspect(scope: String, identity: String, importId: String) {
        val row = dao.activityImport(scope, identity, importId) ?: return
        if (row.state == "cancelled" || row.state == "ready_to_confirm" || row.state == "applied") return
        val operation = dao.activityOperationForImport(scope, identity, importId) ?: return
        val file = row.partialFileName?.let { File(importDirectory(scope), it) }
            ?: throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "Falta el archivo parcial de la importación.", false)
        if (!file.isFile) {
            dao.upsertActivityImport(row.copy(state = "source_lost", errorCode = "source_lost", updatedAt = Instant.now().toString()))
            throw AppFailure(AppErrorCode.LOCAL_STORAGE_ERROR, "Se perdió el permiso o el archivo seleccionado.", false)
        }
        if (sha256(file) != row.sha256) throw AppFailure(AppErrorCode.PACKAGE_HASH_MISMATCH, "El archivo cambió antes de subirlo.", false)
        dao.upsertActivityImport(row.copy(state = "uploading", errorCode = null, updatedAt = Instant.now().toString()))
        try {
            val uploaded = api.uploadActivity(file, row.displayName, mimeFor(row), row.routePolicy,
                row.redactStartMeters, row.redactEndMeters, operation.idempotencyKey)
            if (sha256(file) != row.sha256) throw AppFailure(AppErrorCode.PACKAGE_HASH_MISMATCH, "El archivo cambió durante la carga.", false)
            val serverId = uploaded.string("import_id") ?: throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "Falta el identificador de importación.", false)
            val inspected = api.inspectActivityImport(serverId)
            dao.upsertActivityImport(row.copy(serverPublicId = serverId, detectedFormat = inspected.string("detected_format") ?: row.detectedFormat,
                state = "ready_to_confirm", warningsJson = inspected["warnings"]?.toString() ?: "[]", errorCode = null,
                updatedAt = Instant.now().toString()))
            dao.deleteActivityOperationsForImport(scope, identity, importId)
        } catch (failure: AppFailure) {
            dao.upsertActivityImport(row.copy(state = if (failure.retryable) "retry" else "failed", errorCode = failure.serverCode ?: failure.code.name,
                updatedAt = Instant.now().toString()))
            dao.upsertActivityOperation(operation.copy(status = if (failure.retryable) "retry" else "failed",
                attemptCount = operation.attemptCount + 1, notBeforeEpochMs = System.currentTimeMillis() + 30_000L,
                lastErrorCode = failure.serverCode ?: failure.code.name))
            throw failure
        }
    }

    suspend fun confirm(scope: String, identity: String, importId: String) {
        val row = dao.activityImport(scope, identity, importId) ?: return
        val serverId = row.serverPublicId ?: throw AppFailure(AppErrorCode.VALIDATION_ERROR, "Primero inspecciona la importación.", false)
        val response = api.applyActivityImport(serverId, "activity-apply-$importId")
        response["activity"]?.jsonObject?.let { storeActivity(scope, identity, it) }
        dao.upsertActivityImport(row.copy(state = "applied", sourceUri = null, uriPermissionPersisted = false,
            partialFileName = null, updatedAt = Instant.now().toString()))
        cleanupPartial(row)
    }

    suspend fun retry(scope: String, identity: String, importId: String) {
        val row = dao.activityImport(scope, identity, importId) ?: return
        if (row.partialFileName == null || !File(importDirectory(scope), row.partialFileName).isFile) {
            dao.upsertActivityImport(row.copy(state = "source_lost", errorCode = "source_lost", updatedAt = Instant.now().toString())); return
        }
        dao.upsertActivityImport(row.copy(state = "pending_upload", errorCode = null, updatedAt = Instant.now().toString()))
        val current = dao.activityOperationForImport(scope, identity, importId)
        dao.upsertActivityOperation(current?.copy(status = "pending", notBeforeEpochMs = 0, lastErrorCode = null) ?: operation(row))
        ActivityImportScheduler.enqueue(context, scope, identity, importId)
    }

    suspend fun cancel(scope: String, identity: String, importId: String) {
        ActivityImportScheduler.cancel(context, scope, identity, importId)
        val row = dao.activityImport(scope, identity, importId) ?: return
        dao.deleteActivityOperationsForImport(scope, identity, importId)
        dao.upsertActivityImport(row.copy(state = "cancelled", partialFileName = null, updatedAt = Instant.now().toString()))
        cleanupPartial(row)
    }

    suspend fun refresh(scope: String, identity: String) {
        api.activities()["items"]?.jsonArray.orEmpty().forEach { storeActivity(scope, identity, it.jsonObject) }
        api.activityImports()["items"]?.jsonArray.orEmpty().forEach { raw ->
            val row = raw.jsonObject; val serverId = row.string("import_id") ?: return@forEach
            val existing = dao.activityImportByServerId(scope, identity, serverId) ?: dao.activityImport(scope, identity, serverId)
            if (existing == null) {
                val now = Instant.now().toString()
                dao.upsertActivityImport(ActivityImportEntity(scope, identity, serverId, serverId, "Importación del servidor",
                    row.string("detected_format"), null, row.long("size_bytes") ?: 0, row.string("file_sha256_short").orEmpty(), null,
                    false, null, row.string("route_policy") ?: "keep", row.int("redact_start_meters") ?: 0,
                    row.int("redact_end_meters") ?: 0, row.string("state") ?: "unknown",
                    row["warnings"]?.toString() ?: "[]", row.string("error_code"), row.string("created_at") ?: now, row.string("updated_at") ?: now))
            }
        }
    }

    suspend fun refreshDetail(scope: String, identity: String, publicId: String) {
        val detail = api.activity(publicId); storeActivity(scope, identity, detail)
        val laps = api.activityLaps(publicId)["items"]?.jsonArray.orEmpty().mapNotNull { raw ->
            val row = raw.jsonObject; val index = row.int("index") ?: return@mapNotNull null
            ActivityLapEntity(scope, identity, publicId, index, row.string("startTime"), row.numberString("durationSeconds"),
                row.numberString("distanceMeters"), row["metrics"]?.toString() ?: "{}")
        }
        val series = api.activitySeries(publicId, 240); val seriesItems = series["items"]?.jsonArray.orEmpty()
        val seriesName = if (seriesItems.isNotEmpty()) writeCache(scope, cacheName("activity-series", publicId), seriesItems.toString()) else null
        val fields = seriesItems.flatMap { it.jsonObject.keys }.filterNot { it in setOf("timestamp", "offsetSeconds") }.distinct()
        val now = Instant.now().toString()
        val metadata = ActivitySeriesMetadataEntity(scope, identity, publicId, series.long("sample_count") ?: seriesItems.size.toLong(),
            JsonArray(fields.map(::JsonPrimitive)).toString(), seriesItems.firstOrNull()?.jsonObject?.string("timestamp"),
            seriesItems.lastOrNull()?.jsonObject?.string("timestamp"), seriesName, now)
        val route = runCatching { api.activityRoute(publicId) }.getOrNull()
        val routeName = if (route?.bool("present") == true) writeCache(scope, cacheName("activity-route", publicId), route["points"]?.toString() ?: "[]") else null
        val routeEntity = ActivityRouteEntity(scope, identity, publicId, route?.string("state") ?: "unavailable",
            detail["route"]?.jsonObject?.string("policy") ?: "keep", route?.get("points")?.jsonArray?.size?.toLong() ?: 0,
            route?.get("points")?.jsonArray.orEmpty().any { it.jsonObject.containsKey("elevation") }, routeName,
            if (route?.string("state") == "removed") now else null, now)
        database.withTransaction {
            dao.deleteActivityLaps(scope, identity, publicId); dao.upsertActivityLaps(laps)
            dao.upsertActivitySeriesMetadata(metadata); dao.upsertActivityRoute(routeEntity)
        }
        cacheLinkAndDuplicates(scope, identity, publicId, detail)
        runCatching { cacheComparison(scope, identity, publicId, api.activityComparison(publicId)) }
    }

    suspend fun archive(scope: String, identity: String, activity: ActivityEntity) {
        storeActivity(scope, identity, api.archiveActivity(activity.publicId, activity.revision, UUID.randomUUID().toString()))
    }

    suspend fun removeRoute(scope: String, identity: String, activity: ActivityEntity) {
        storeActivity(scope, identity, api.deleteActivityRoute(activity.publicId, activity.revision, UUID.randomUUID().toString()))
        dao.upsertActivityRoute(ActivityRouteEntity(scope, identity, activity.publicId, "removed", "drop", 0, false, null,
            Instant.now().toString(), Instant.now().toString()))
        File(cacheDirectory(scope), cacheName("activity-route", activity.publicId)).delete()
    }

    suspend fun planCandidates(activityId: String): List<JsonObject> =
        api.activityPlanCandidates(activityId)["items"]?.jsonArray.orEmpty().map { it.jsonObject }

    suspend fun setPlanDecision(scope: String, identity: String, activityId: String, plannedId: String, revision: Int, action: String) {
        require(action in setOf("confirm", "reject"))
        val payload = buildJsonObject { put("planned_workout_id", plannedId); put("action", action); put("base_revision", revision) }
        val row = api.linkActivity(activityId, payload, UUID.randomUUID().toString())
        cacheLink(scope, identity, activityId, row)
        if (action == "confirm") cacheComparison(scope, identity, activityId, api.activityComparison(activityId))
    }

    suspend fun export(scope: String, activityId: String, format: String, includeRoute: Boolean): Intent {
        require(format in setOf("json", "summary_csv", "laps_csv", "samples_csv", "gpx"))
        val extension = if (format == "gpx") "gpx" else if (format == "json") "json" else "csv"
        val directory = File(context.cacheDir, "activity_exports").apply { mkdirs() }
        val target = File(directory, PrivateFileNames.opaque("activity-export", activityId, extension))
        try {
            api.downloadActivityExport(activityId, format, includeRoute, target)
        } catch (failure: Throwable) {
            target.delete()
            throw failure
        }
        val uri = FileProvider.getUriForFile(context, "${BuildConfig.APPLICATION_ID}.activity-exports", target)
        return Intent(Intent.ACTION_SEND).setType(if (extension == "gpx") "application/gpx+xml" else if (extension == "json") "application/json" else "text/csv")
            .putExtra(Intent.EXTRA_STREAM, uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }

    fun routePoints(scope: String, activityId: String, maximum: Int = 240): List<Pair<Double, Double>> {
        val file = File(cacheDirectory(scope), cacheName("activity-route", activityId))
        val values = runCatching { api.json.parseToJsonElement(file.readText()).jsonArray }.getOrNull().orEmpty()
        val stride = (values.size / maximum.coerceAtLeast(1)).coerceAtLeast(1)
        return values.filterIndexed { index, _ -> index % stride == 0 }.take(maximum).mapNotNull { raw ->
            val row = raw.jsonObject; val lat = row["lat"]?.jsonPrimitive?.doubleOrNull; val lon = row["lon"]?.jsonPrimitive?.doubleOrNull
            if (lat == null || lon == null || lat !in -90.0..90.0 || lon !in -180.0..180.0) null else lat to lon
        }
    }

    fun metricSeries(scope: String, activityId: String, metric: String): List<Double> {
        val allowed = setOf("speed", "pace", "heartRate", "cadence", "power", "elevation", "distance")
        if (metric !in allowed) return emptyList()
        val file = File(cacheDirectory(scope), cacheName("activity-series", activityId))
        return runCatching { api.json.parseToJsonElement(file.readText()).jsonArray }.getOrNull().orEmpty()
            .mapNotNull { it.jsonObject[metric]?.jsonPrimitive?.doubleOrNull?.takeIf(Double::isFinite) }
    }

    fun cleanupScopeFiles(scope: String) {
        androidx.work.WorkManager.getInstance(context).cancelAllWorkByTag(ActivityImportScheduler.scopeTag(scope))
        importDirectory(scope).deleteRecursively(); cacheDirectory(scope).deleteRecursively()
    }
    fun cleanupExports() { File(context.cacheDir, "activity_exports").deleteRecursively() }

    private suspend fun storeActivity(scope: String, identity: String, row: JsonObject) {
        val id = row.string("publicId") ?: return; val summary = row["summary"]?.jsonObject ?: buildJsonObject {}
        val source = row["sourceReference"]?.jsonObject
        dao.upsertActivity(ActivityEntity(scope, identity, id, row.string("discipline") ?: "other", row.string("subtype"),
            row.string("title"), row.string("startTime") ?: Instant.EPOCH.toString(), row.string("timezone"),
            summary.metricLong("duration"), summary.metricLong("elapsed_time"), summary.metricString("distance"),
            summary.metricString("calories"), summary.metricString("heart_rate_average"), summary.metricString("heart_rate_maximum"),
            row.string("sourceFormat") ?: source?.string("format") ?: "unknown", source?.string("device") ?: row.string("sourceDevice"),
            null, row.string("status") ?: "imported", row.int("revision") ?: 1, summary.toString(), "synced",
            row.string("updatedAt") ?: Instant.now().toString()))
    }

    private suspend fun cacheLinkAndDuplicates(scope: String, identity: String, activityId: String, row: JsonObject) {
        row["planLink"]?.jsonObject?.let { cacheLink(scope, identity, activityId, it) }
        val values = row["duplicates"]?.jsonArray.orEmpty().mapNotNull { raw ->
            val item = raw.jsonObject; val id = item.string("candidate_id") ?: return@mapNotNull null
            ActivityDuplicateCandidateEntity(scope, identity, id, activityId, item.string("activity_id").orEmpty(),
                item.string("classification") ?: "probable", item["evidence"]?.toString() ?: "{}",
                item.string("resolution") ?: "pending", Instant.now().toString())
        }
        dao.upsertActivityDuplicates(values)
    }

    private suspend fun cacheLink(scope: String, identity: String, activityId: String, row: JsonObject) {
        val id = row.string("link_id") ?: return
        dao.upsertPlanActivityLinks(listOf(PlanActivityLinkEntity(scope, identity, id, activityId,
            row.string("planned_workout_id").orEmpty(), if (row.string("state") == "strong_auto_link") "strong" else "manual",
            row.string("state") ?: "confirmed", row["evidence"]?.toString() ?: "{}", Instant.now().toString())))
    }

    private suspend fun cacheComparison(scope: String, identity: String, activityId: String, row: JsonObject) {
        if (row.string("status") == "not_comparable") return
        val linkId = row.string("link_id") ?: "link-$activityId"
        dao.upsertPlanActualComparison(PlanActualComparisonEntity(scope, identity, "comparison-$activityId", activityId,
            linkId, row.string("status") ?: "insufficient_data", row.toString(), Instant.now().toString()))
    }

    private fun operation(row: ActivityImportEntity): ActivityOperationEntity {
        val raw = buildJsonObject { put("route_policy", row.routePolicy); put("redact_start_meters", row.redactStartMeters); put("redact_end_meters", row.redactEndMeters); put("sha256", row.sha256) }.toString()
        return ActivityOperationEntity(row.accountScope, row.serverIdentity, UUID.randomUUID().toString(), row.publicId,
            "upload_inspect", "activity-upload-${row.publicId}", raw, hashText(raw), "pending", 0, 0, row.createdAt, null)
    }

    private fun cleanupPartial(row: ActivityImportEntity) {
        row.partialFileName?.let { File(importDirectory(row.accountScope), it).delete() }
        row.sourceUri?.let { runCatching { release(Uri.parse(it)) } }
    }
    private fun release(uri: Uri) { context.contentResolver.releasePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) }
    private fun importDirectory(scope: String) = File(context.noBackupFilesDir, "activity_imports/${scopeHash(scope)}").apply { mkdirs() }
    private fun cacheDirectory(scope: String) = File(context.noBackupFilesDir, "activity_cache/${scopeHash(scope)}").apply { mkdirs() }
    private fun writeCache(scope: String, name: String, content: String): String {
        val directory = cacheDirectory(scope).canonicalFile
        val target = File(directory, name).canonicalFile
        require(target.parentFile == directory) { "activity_cache_path_invalid" }
        target.writeText(content)
        return name
    }
    private fun cacheName(label: String, activityId: String) = PrivateFileNames.opaque(label, activityId, "json")
    private fun mimeFor(row: ActivityImportEntity) = row.mimeType ?: when (row.detectedFormat ?: ActivityFileRules.formatFor(row.displayName)) {
        "gpx" -> "application/gpx+xml"; "tcx" -> "application/vnd.garmin.tcx+xml"; else -> "application/octet-stream"
    }
    private fun sha256(file: File): String { val digest = MessageDigest.getInstance("SHA-256"); file.inputStream().use { input ->
        val buffer = ByteArray(DEFAULT_BUFFER_SIZE); while (true) { val read = input.read(buffer); if (read < 0) break; digest.update(buffer, 0, read) }
    }; return digest.digest().joinToString("") { "%02x".format(it) } }
    private fun hashText(value: String) = MessageDigest.getInstance("SHA-256").digest(value.toByteArray()).joinToString("") { "%02x".format(it) }
    private fun scopeHash(value: String) = hashText(value).take(24)
    private fun JsonObject.string(key: String) = this[key]?.jsonPrimitive?.contentOrNull
    private fun JsonObject.long(key: String) = this[key]?.jsonPrimitive?.longOrNull
    private fun JsonObject.int(key: String) = this[key]?.jsonPrimitive?.intOrNull
    private fun JsonObject.bool(key: String) = this[key]?.jsonPrimitive?.booleanOrNull
    private fun JsonObject.numberString(key: String) = this[key]?.jsonPrimitive?.contentOrNull
    private fun JsonObject.metricString(key: String) = this[key]?.jsonObject?.get("value")?.jsonPrimitive?.contentOrNull
    private fun JsonObject.metricLong(key: String) = metricString(key)?.toDoubleOrNull()?.toLong()
}
