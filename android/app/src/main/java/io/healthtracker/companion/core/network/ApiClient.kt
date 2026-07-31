package io.healthtracker.companion.core.network

import android.util.Log
import io.healthtracker.companion.BuildConfig
import io.healthtracker.companion.core.config.PreferenceStore
import io.healthtracker.companion.core.model.*
import io.healthtracker.companion.core.security.Redaction
import io.healthtracker.companion.core.security.SecureTokenStore
import java.io.IOException
import java.io.File
import java.security.MessageDigest
import java.time.Duration
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.Response
import java.util.concurrent.TimeUnit

data class VerifiedPackage(val value: WorkoutPackageDto, val calculatedHash: String)
data class PortableDownloadResult(val sha256: String, val sizeBytes: Long)

class ApiClient(
    private val preferences: PreferenceStore,
    private val tokens: SecureTokenStore,
    client: OkHttpClient? = null,
) {
    val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        isLenient = false
        coerceInputValues = false
        encodeDefaults = true
    }
    private val http = (client ?: OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .retryOnConnectionFailure(false)
        .build()).newBuilder()
        .followRedirects(false)
        .followSslRedirects(false)
        .build()
    private val refreshMutex = Mutex()

    suspend fun health(baseUrl: String? = null): HealthResponse =
        call("/api/v1/health", "GET", baseOverride = baseUrl, requiresAuth = false)

    suspend fun createPortableExport(payload: JsonObject, key: String): JsonObject = call(
        "/api/v1/mobile/portability/exports", "POST", payload.toString(), idempotencyKey = key,
    )

    suspend fun portableExports(): JsonObject = call("/api/v1/mobile/portability/exports", "GET")

    suspend fun deletePortableExport(publicId: String): JsonObject = call(
        "/api/v1/mobile/portability/exports/$publicId", "DELETE",
    )

    suspend fun portableImports(): JsonObject = call("/api/v1/mobile/portability/imports", "GET")

    suspend fun inspectPortablePackage(file: File, sections: List<String>): JsonObject = withContext(Dispatchers.IO) {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", "selected.htpack", file.asRequestBody(PORTABLE_MEDIA))
            .addFormDataPart("sections", json.encodeToString(sections))
            .build()
        val raw = executeCustom("/api/v1/mobile/portability/imports/inspect", "POST", body).use { checkedResponse(it) }
        try {
            json.decodeFromString<ApiEnvelope<JsonObject>>(raw).data
        } catch (error: Exception) {
            logContractDecodeFailure("/api/v1/mobile/portability/imports/inspect", error)
            throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "El servidor respondió con un contrato incompatible.", false)
        }
    }

    suspend fun applyPortableImport(publicId: String, payload: JsonObject, key: String): JsonObject = call(
        "/api/v1/mobile/portability/imports/$publicId/apply", "POST", payload.toString(), idempotencyKey = key,
    )

    suspend fun deletePortableImport(publicId: String): JsonObject = call(
        "/api/v1/mobile/portability/imports/$publicId", "DELETE",
    )

    suspend fun downloadPortableExport(publicId: String, destination: File): PortableDownloadResult = withContext(Dispatchers.IO) {
        executeCustom("/api/v1/mobile/portability/exports/$publicId/download", "GET", null).use { response ->
            if (!response.isSuccessful) checkedResponse(response)
            val length = response.body.contentLength()
            if (length > MAX_PORTABLE_BYTES) throw AppFailure(AppErrorCode.PACKAGE_HASH_MISMATCH, "La descarga supera el límite local.", false)
            val digest = MessageDigest.getInstance("SHA-256")
            var size = 0L
            destination.parentFile?.mkdirs()
            destination.outputStream().use { output ->
                val input = response.body.byteStream()
                val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    size += read
                    if (size > MAX_PORTABLE_BYTES) throw AppFailure(AppErrorCode.PACKAGE_HASH_MISMATCH, "La descarga supera el límite local.", false)
                    digest.update(buffer, 0, read); output.write(buffer, 0, read)
                }
            }
            PortableDownloadResult(digest.digest().joinToString("") { byte -> "%02x".format(byte) }, size)
        }
    }

    suspend fun login(baseUrl: String, request: LoginRequest): TokenResponse {
        val expectedVersion = tokens.mutationVersion()
        val result: TokenResponse = call(
            "/api/v1/auth/login",
            "POST",
            json.encodeToString(request),
            baseOverride = baseUrl,
            requiresAuth = false,
        )
        if (!tokens.replaceTokensIfVersion(expectedVersion, result.accessToken, result.refreshToken, baseUrl)) {
            throw AppFailure(AppErrorCode.UNAUTHORIZED, "La sesión cambió durante el inicio de sesión.", false)
        }
        return result
    }

    suspend fun me(): UserProfile = call("/api/v1/me", "GET")
    suspend fun bootstrap(): BootstrapResponse = call("/api/v1/sync/bootstrap", "GET")

    suspend fun restoreSession() {
        val base = preferences.values.first().serverUrl
            ?: throw AppFailure(AppErrorCode.REFRESH_FAILED, "Falta la configuración del servidor.", false)
        if (tokens.accessToken(base) == null && tokens.refreshToken(base) != null) {
            refreshSingleFlight(base, null)
        }
    }

    suspend fun negotiate(request: NegotiationRequest): NegotiationResponse = call(
        "/api/v1/companion/negotiate", "POST", json.encodeToString(request),
    )

    suspend fun createDelivery(request: DeliveryCreateRequest, key: String): DeliveryDto = call(
        "/api/v1/companion/deliveries", "POST", json.encodeToString(request), idempotencyKey = key,
    )

    suspend fun deliveries(): List<DeliveryDto> = call("/api/v1/companion/deliveries", "GET")

    suspend fun downloadPackage(deliveryId: String): VerifiedPackage {
        val raw = rawCall("/api/v1/companion/deliveries/$deliveryId/package", "GET")
        val root = json.parseToJsonElement(raw).jsonObject
        val element = root["data"]?.jsonObject
            ?: throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "La respuesta no contiene un package válido.", false)
        val packageHash = element["package_hash"]?.toString()?.trim('"')
            ?: throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "El package no declara su hash.", false)
        val calculated = CanonicalJson.sha256(element, excludingTopLevelKey = "package_hash")
        if (!packageHash.equals(calculated, ignoreCase = true)) {
            throw AppFailure(AppErrorCode.PACKAGE_HASH_MISMATCH, "El package descargado no pasó la verificación SHA-256.", false)
        }
        val decoded = json.decodeFromJsonElement(WorkoutPackageDto.serializer(), element)
        if (decoded.schemaVersion != CONTRACT_VERSION) {
            throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "La versión del package no es compatible.", false)
        }
        if (decoded.exercises.isEmpty() || decoded.exercises.map { it.exerciseOrder }.distinct().size != decoded.exercises.size ||
            decoded.exercises.any { it.exerciseOrder < 1 || it.name.isBlank() || it.sets.isEmpty() }
        ) {
            throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "El package no cumple la estructura de entrenamiento 1.0.", false)
        }
        return VerifiedPackage(decoded, calculated)
    }

    suspend fun transition(deliveryId: String, action: String, request: DeliveryOperationRequest, key: String): DeliveryDto = call(
        "/api/v1/companion/deliveries/$deliveryId/$action", "POST", json.encodeToString(request), idempotencyKey = key,
    )

    suspend fun progress(deliveryId: String, request: ProgressRequest, key: String): JsonObject = call(
        "/api/v1/companion/deliveries/$deliveryId/progress", "POST", json.encodeToString(request), idempotencyKey = key,
    )

    suspend fun complete(deliveryId: String, request: CompletionRequest, key: String): CompletionResponse = call(
        "/api/v1/companion/deliveries/$deliveryId/complete", "POST", json.encodeToString(request), idempotencyKey = key,
    )

    suspend fun pull(cursor: String, limit: Int): PullResponse = call(
        "/api/v1/sync/pull?cursor=${java.net.URLEncoder.encode(cursor, Charsets.UTF_8.name())}&limit=$limit", "GET",
    )

    suspend fun syncStatus(): SyncStatusResponse = call("/api/v1/sync/status", "GET")

    suspend fun history(
        cursor: String? = null,
        limit: Int = 25,
        dateFrom: String? = null,
        dateTo: String? = null,
        exercisePublicId: String? = null,
    ): MobileHistoryPageDto {
        val query = buildList {
            add("limit=$limit")
            cursor?.let { add("cursor=${encodeQuery(it)}") }
            dateFrom?.let { add("date_from=${encodeQuery(it)}") }
            dateTo?.let { add("date_to=${encodeQuery(it)}") }
            exercisePublicId?.let { add("exercise_public_id=${encodeQuery(it)}") }
        }.joinToString("&")
        return call("/api/v1/mobile/history?$query", "GET")
    }

    suspend fun historyDetail(publicId: String): MobileHistoryDetailDto =
        call("/api/v1/mobile/history/${encodeQuery(publicId)}", "GET")

    suspend fun progressSummary(range: String): ProgressSummaryDto =
        call("/api/v1/mobile/progress/summary?range=${encodeQuery(range)}", "GET")

    suspend fun progressExercises(range: String): ProgressExerciseListDto =
        call("/api/v1/mobile/progress/exercises?range=${encodeQuery(range)}", "GET")

    suspend fun progressExercise(publicId: String, range: String): ProgressExerciseDetailDto =
        call("/api/v1/mobile/progress/exercises/${encodeQuery(publicId)}?range=${encodeQuery(range)}", "GET")

    suspend fun exerciseCatalog(search: String = "", cursor: String? = null, limit: Int = 50): ExerciseCatalogResponseDto {
        val query = buildList {
            add("limit=$limit")
            if (search.isNotBlank()) add("search=${encodeQuery(search)}")
            cursor?.let { add("cursor=${encodeQuery(it)}") }
        }.joinToString("&")
        return call("/api/v1/mobile/exercises?$query", "GET")
    }

    suspend fun plans(status: String = "active"): MobilePlanListDto =
        call("/api/v1/mobile/plans?status=${encodeQuery(status)}", "GET")

    suspend fun plan(publicId: String): MobilePlanDto =
        call("/api/v1/mobile/plans/${encodeQuery(publicId)}", "GET")

    suspend fun planWorkout(publicId: String): MobilePlanWorkoutDto =
        call("/api/v1/mobile/workouts/${encodeQuery(publicId)}", "GET")

    suspend fun createPlan(request: PlanCreateRequest, key: String): PlanMutationResponse =
        call("/api/v1/mobile/plans", "POST", json.encodeToString(request), idempotencyKey = key)

    suspend fun patchPlan(publicId: String, payload: JsonObject, key: String): PlanMutationResponse =
        call("/api/v1/mobile/plans/${encodeQuery(publicId)}", "PATCH", payload.toString(), idempotencyKey = key)

    suspend fun duplicatePlan(publicId: String, payload: JsonObject, key: String): PlanMutationResponse =
        call("/api/v1/mobile/plans/${encodeQuery(publicId)}/duplicate", "POST", payload.toString(), idempotencyKey = key)

    suspend fun createPlanWorkout(planId: String, payload: JsonObject, key: String): WorkoutMutationResponse =
        call("/api/v1/mobile/plans/${encodeQuery(planId)}/workouts", "POST", payload.toString(), idempotencyKey = key)

    suspend fun patchPlanWorkout(publicId: String, payload: JsonObject, key: String): WorkoutMutationResponse =
        call("/api/v1/mobile/workouts/${encodeQuery(publicId)}", "PATCH", payload.toString(), idempotencyKey = key)

    suspend fun duplicatePlanWorkout(publicId: String, payload: JsonObject, key: String): WorkoutMutationResponse =
        call("/api/v1/mobile/workouts/${encodeQuery(publicId)}/duplicate", "POST", payload.toString(), idempotencyKey = key)

    suspend fun schedulePlanWorkout(publicId: String, payload: JsonObject, key: String): ScheduleMutationResponse =
        call("/api/v1/mobile/workouts/${encodeQuery(publicId)}/schedule", "POST", payload.toString(), idempotencyKey = key)

    suspend fun cancelScheduledWorkout(publicId: String, payload: JsonObject, key: String): JsonObject =
        call("/api/v1/mobile/scheduled-workouts/${encodeQuery(publicId)}", "DELETE", payload.toString(), idempotencyKey = key)

    suspend fun plannedWorkouts(from: String, to: String): List<PlannedWorkoutDto> =
        call("/api/v1/planned-workouts?from=${encodeQuery(from)}&to=${encodeQuery(to)}", "GET")

    suspend fun reschedulePlannedWorkout(publicId: String, payload: JsonObject, key: String): ScheduledWorkoutMutationResponse =
        call("/api/v1/planned-workouts/${encodeQuery(publicId)}", "PATCH", payload.toString(), idempotencyKey = key)

    suspend fun plannedWorkout(publicId: String): PlannedWorkoutDto =
        call("/api/v1/planned-workouts/${encodeQuery(publicId)}", "GET")

    suspend fun healthToday(date: String, timezone: String): MobileHealthTodayDto =
        call("/api/v1/mobile/health/today?date=${encodeQuery(date)}&timezone=${encodeQuery(timezone)}", "GET")

    suspend fun healthProgress(from: String, to: String, timezone: String): MobileHealthProgressDto =
        call("/api/v1/mobile/health/progress?from=${encodeQuery(from)}&to=${encodeQuery(to)}&timezone=${encodeQuery(timezone)}", "GET")

    suspend fun bodyStats(cursor: String? = null, limit: Int = 50): MobileBodyStatsPageDto {
        val query = buildList {
            add("limit=$limit")
            cursor?.let { add("cursor=${encodeQuery(it)}") }
        }.joinToString("&")
        return call("/api/v1/mobile/body-stats?$query", "GET")
    }

    suspend fun createBodyStat(payload: JsonObject, key: String): MobileBodyStatDto =
        call("/api/v1/mobile/body-stats", "POST", payload.toString(), idempotencyKey = key)

    suspend fun patchBodyStat(publicId: String, payload: JsonObject, key: String): MobileBodyStatDto =
        call("/api/v1/mobile/body-stats/${encodeQuery(publicId)}", "PATCH", payload.toString(), idempotencyKey = key)

    suspend fun deleteBodyStat(publicId: String, payload: JsonObject, key: String): MobileDeleteResponse =
        call("/api/v1/mobile/body-stats/${encodeQuery(publicId)}", "DELETE", payload.toString(), idempotencyKey = key)

    suspend fun nutritionDay(date: String): MobileNutritionDayDto =
        call("/api/v1/mobile/nutrition/days/${encodeQuery(date)}", "GET")

    suspend fun createNutritionEntry(payload: JsonObject, key: String): MobileNutritionEntryDto =
        call("/api/v1/mobile/nutrition/entries", "POST", payload.toString(), idempotencyKey = key)

    suspend fun patchNutritionEntry(publicId: String, payload: JsonObject, key: String): MobileNutritionEntryDto =
        call("/api/v1/mobile/nutrition/entries/${encodeQuery(publicId)}", "PATCH", payload.toString(), idempotencyKey = key)

    suspend fun deleteNutritionEntry(publicId: String, payload: JsonObject, key: String): MobileDeleteResponse =
        call("/api/v1/mobile/nutrition/entries/${encodeQuery(publicId)}", "DELETE", payload.toString(), idempotencyKey = key)

    suspend fun foods(search: String = "", cursor: String? = null, limit: Int = 50): MobileFoodPageDto {
        val query = buildList {
            add("limit=$limit")
            if (search.isNotBlank()) add("search=${encodeQuery(search)}")
            cursor?.let { add("cursor=${encodeQuery(it)}") }
        }.joinToString("&")
        return call("/api/v1/mobile/foods?$query", "GET")
    }

    suspend fun createFood(payload: JsonObject, key: String): MobileFoodDto =
        call("/api/v1/mobile/foods", "POST", payload.toString(), idempotencyKey = key)

    suspend fun steps(from: String, to: String, limit: Int = 100): MobileStepsPageDto =
        call("/api/v1/mobile/steps?from=${encodeQuery(from)}&to=${encodeQuery(to)}&limit=$limit", "GET")

    suspend fun createSteps(payload: JsonObject, key: String): MobileStepDto =
        call("/api/v1/mobile/steps", "POST", payload.toString(), idempotencyKey = key)

    suspend fun patchSteps(publicId: String, payload: JsonObject, key: String): MobileStepDto =
        call("/api/v1/mobile/steps/${encodeQuery(publicId)}", "PATCH", payload.toString(), idempotencyKey = key)

    suspend fun deleteSteps(publicId: String, payload: JsonObject, key: String): MobileDeleteResponse =
        call("/api/v1/mobile/steps/${encodeQuery(publicId)}", "DELETE", payload.toString(), idempotencyKey = key)

    suspend fun push(request: PushRequest, key: String): PushResponse = call(
        "/api/v1/sync/push", "POST", json.encodeToString(request), idempotencyKey = key,
    )

    suspend fun logout() {
        call<JsonObject>("/api/v1/auth/logout", "POST", "{}")
    }

    suspend fun logoutAll(): JsonObject = call("/api/v1/auth/logout-all", "POST", "{}")

    suspend fun revokeDevice(deviceId: String) {
        call<JsonObject>("/api/v1/devices/$deviceId", "DELETE")
    }

    private suspend inline fun <reified T> call(
        path: String,
        method: String,
        body: String? = null,
        baseOverride: String? = null,
        requiresAuth: Boolean = true,
        idempotencyKey: String? = null,
    ): T {
        val raw = rawCall(path, method, body, baseOverride, requiresAuth, idempotencyKey)
        return try {
            json.decodeFromString<ApiEnvelope<T>>(raw).data
        } catch (failure: AppFailure) {
            throw failure
        } catch (error: Exception) {
            logContractDecodeFailure(path, error)
            throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "El servidor respondió con un contrato incompatible.", false)
        }
    }

    private fun logContractDecodeFailure(path: String, error: Exception) {
        if (!BuildConfig.DEBUG) return
        val endpoint = path.substringBefore('?').replace(UUID_PATH_COMPONENT, "/{id}").take(160)
        val exceptionName = Redaction.diagnosticCode(error::class.simpleName) ?: "Exception"
        val serializationPath = SERIALIZATION_PATH.find(error.message.orEmpty())
            ?.groupValues
            ?.getOrNull(1)
            ?.take(160)
        val pathDiagnostic = serializationPath?.let { " path=$it" }.orEmpty()
        Log.w(
            "HealthTrackerContract",
            "contract_decode_failed endpoint=$endpoint exception=$exceptionName code=contract_field_incompatible$pathDiagnostic",
        )
    }

    private suspend fun rawCall(
        path: String,
        method: String,
        body: String? = null,
        baseOverride: String? = null,
        requiresAuth: Boolean = true,
        idempotencyKey: String? = null,
        allowRefresh: Boolean = true,
    ): String = withContext(Dispatchers.IO) {
        val base = baseOverride ?: preferences.values.first().serverUrl
            ?: throw AppFailure(AppErrorCode.SERVER_INCOMPATIBLE, "Configura un servidor antes de continuar.", false)
        if (requiresAuth) tokens.bindLegacyServerIfMissing(base)
        val failedAccess = tokens.accessToken(base)
        val requestVersion = tokens.mutationVersion()
        val response = execute(base, path, method, body, requiresAuth, idempotencyKey)
        if (response.code == 401 && requiresAuth && allowRefresh) {
            val rawError = response.use { readResponseBody(it) }
            val parsed = runCatching { json.decodeFromString<ErrorEnvelope>(rawError).error }.getOrNull()
            if (parsed?.code == "session_revoked") {
                if (!tokens.clearIfVersion(requestVersion)) {
                    throw AppFailure(AppErrorCode.UNAUTHORIZED, "La sesión cambió durante la solicitud.", false)
                }
                throw ErrorMapper.http(401, parsed, null)
            }
            refreshSingleFlight(base, failedAccess)
            return@withContext rawCall(path, method, body, base, true, idempotencyKey, false)
        }
        response.use { checkedResponse(it) }
    }

    private fun execute(
        base: String,
        path: String,
        method: String,
        body: String?,
        requiresAuth: Boolean,
        idempotencyKey: String?,
    ): Response {
        val builder = Request.Builder()
            .url(base.trimEnd('/') + path)
            .header("Accept", "application/json")
        if (requiresAuth) {
            val token = tokens.accessToken(base)
                ?: throw AppFailure(AppErrorCode.UNAUTHORIZED, "Inicia sesión para continuar.", false)
            builder.header("Authorization", "Bearer $token")
        }
        idempotencyKey?.let { builder.header("Idempotency-Key", it) }
        val requestBody = body?.toRequestBody(JSON_MEDIA)
        builder.method(method, requestBody)
        return try {
            http.newCall(builder.build()).execute()
        } catch (error: IOException) {
            throw ErrorMapper.network(error)
        }
    }

    private suspend fun executeCustom(
        path: String,
        method: String,
        body: okhttp3.RequestBody?,
        allowRefresh: Boolean = true,
    ): Response {
        val base = preferences.values.first().serverUrl
            ?: throw AppFailure(AppErrorCode.SERVER_INCOMPATIBLE, "Configura un servidor antes de continuar.", false)
        tokens.bindLegacyServerIfMissing(base)
        val failedAccess = tokens.accessToken(base)
            ?: throw AppFailure(AppErrorCode.UNAUTHORIZED, "Inicia sesión para continuar.", false)
        val requestVersion = tokens.mutationVersion()
        val request = Request.Builder()
            .url(base.trimEnd('/') + path)
            .header("Accept", "application/json, application/vnd.health-tracker.portable+zip")
            .header("Authorization", "Bearer $failedAccess")
            .method(method, body)
            .build()
        val response = try {
            http.newCall(request).execute()
        } catch (error: IOException) {
            throw ErrorMapper.network(error)
        }
        if (response.code == 401 && allowRefresh) {
            val rawError = response.use { readResponseBody(it) }
            val parsed = runCatching { json.decodeFromString<ErrorEnvelope>(rawError).error }.getOrNull()
            if (parsed?.code == "session_revoked") {
                if (!tokens.clearIfVersion(requestVersion)) {
                    throw AppFailure(AppErrorCode.UNAUTHORIZED, "La sesion cambio durante la solicitud.", false)
                }
                throw ErrorMapper.http(401, parsed, null)
            }
            refreshSingleFlight(base, failedAccess)
            return executeCustom(path, method, body, false)
        }
        return response
    }

    private fun checkedResponse(response: Response): String {
        val raw = readResponseBody(response)
        if (response.isSuccessful) return raw
        val parsed = runCatching { json.decodeFromString<ErrorEnvelope>(raw).error }.getOrNull()
        val retryAfter = parseRetryAfter(response.header("Retry-After"))
        throw ErrorMapper.http(response.code, parsed, retryAfter)
    }

    private fun parseRetryAfter(value: String?): Long? {
        value ?: return null
        value.toLongOrNull()?.let { return it.coerceIn(0, MAX_RETRY_AFTER_SECONDS) }
        return runCatching {
            Duration.between(ZonedDateTime.now(), ZonedDateTime.parse(value, DateTimeFormatter.RFC_1123_DATE_TIME))
                .seconds.coerceIn(0, MAX_RETRY_AFTER_SECONDS)
        }.getOrNull()
    }

    private fun readResponseBody(response: Response): String = try {
        val body = response.body
        if (body.contentLength() > MAX_RESPONSE_BYTES) {
            throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "La respuesta del servidor excede el límite permitido.", false)
        }
        val source = body.source()
        source.request(MAX_RESPONSE_BYTES + 1)
        if (source.buffer.size > MAX_RESPONSE_BYTES) {
            throw AppFailure(AppErrorCode.SCHEMA_INCOMPATIBLE, "La respuesta del servidor excede el límite permitido.", false)
        }
        source.readUtf8()
    } catch (failure: AppFailure) {
        throw failure
    } catch (error: IOException) {
        throw ErrorMapper.network(error)
    }

    private fun encodeQuery(value: String): String =
        java.net.URLEncoder.encode(value, Charsets.UTF_8.name())

    private suspend fun refreshSingleFlight(base: String, failedAccess: String?) = refreshMutex.withLock {
        if (tokens.accessToken(base) != null && tokens.accessToken(base) != failedAccess) return@withLock
        val expectedVersion = tokens.mutationVersion()
        val refresh = tokens.refreshToken(base) ?: run {
            tokens.clearIfVersion(expectedVersion)
            throw AppFailure(AppErrorCode.REFRESH_FAILED, "La sesión venció. Inicia sesión nuevamente.", false)
        }
        try {
            val response: TokenResponse = call(
                "/api/v1/auth/refresh", "POST", json.encodeToString(RefreshRequest(refresh)),
                baseOverride = base, requiresAuth = false,
            )
            if (!tokens.replaceTokensIfVersion(expectedVersion, response.accessToken, response.refreshToken, base)) {
                throw AppFailure(AppErrorCode.UNAUTHORIZED, "La sesión cambió durante la renovación.", false)
            }
        } catch (error: AppFailure) {
            if (tokens.mutationVersion() != expectedVersion) throw error
            if (refreshFailureDisposition(error) == RefreshFailureDisposition.PRESERVE_LOCAL_SESSION) {
                throw error
            }
            tokens.clearIfVersion(expectedVersion)
            if (error.code == AppErrorCode.DEVICE_REVOKED) throw error
            throw AppFailure(AppErrorCode.REFRESH_FAILED, "No fue posible renovar la sesión. Inicia sesión nuevamente.", false)
        }
    }

    private companion object {
        val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()
        val PORTABLE_MEDIA = "application/vnd.health-tracker.portable+zip".toMediaType()
        val UUID_PATH_COMPONENT = Regex("/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}")
        val SERIALIZATION_PATH = Regex("(?:at path:?\\s*)(\\$[A-Za-z0-9_.$\\[\\]-]+)")
        const val MAX_RESPONSE_BYTES = 4L * 1024L * 1024L
        const val MAX_PORTABLE_BYTES = 50L * 1024L * 1024L
        const val MAX_RETRY_AFTER_SECONDS = 6L * 60L * 60L
    }
}
