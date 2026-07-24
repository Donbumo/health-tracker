package io.healthtracker.companion.core.network

import android.util.Log
import io.healthtracker.companion.BuildConfig
import io.healthtracker.companion.core.config.PreferenceStore
import io.healthtracker.companion.core.model.*
import io.healthtracker.companion.core.security.Redaction
import io.healthtracker.companion.core.security.SecureTokenStore
import java.io.IOException
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
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.util.concurrent.TimeUnit

data class VerifiedPackage(val value: WorkoutPackageDto, val calculatedHash: String)

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
    private val http = client ?: OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .retryOnConnectionFailure(false)
        .build()
    private val refreshMutex = Mutex()

    suspend fun health(baseUrl: String? = null): HealthResponse =
        call("/api/v1/health", "GET", baseOverride = baseUrl, requiresAuth = false)

    suspend fun login(baseUrl: String, request: LoginRequest): TokenResponse {
        val result: TokenResponse = call(
            "/api/v1/auth/login",
            "POST",
            json.encodeToString(request),
            baseOverride = baseUrl,
            requiresAuth = false,
        )
        tokens.setTokens(result.accessToken, result.refreshToken)
        return result
    }

    suspend fun me(): UserProfile = call("/api/v1/me", "GET")
    suspend fun bootstrap(): BootstrapResponse = call("/api/v1/sync/bootstrap", "GET")

    suspend fun restoreSession() {
        if (tokens.accessToken() == null && tokens.refreshToken() != null) {
            val base = preferences.values.first().serverUrl
                ?: throw AppFailure(AppErrorCode.REFRESH_FAILED, "Falta la configuración del servidor.", false)
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
        val failedAccess = tokens.accessToken()
        val response = execute(base, path, method, body, requiresAuth, idempotencyKey)
        if (response.code == 401 && requiresAuth && allowRefresh) {
            val rawError = response.body.string()
            val parsed = runCatching { json.decodeFromString<ErrorEnvelope>(rawError).error }.getOrNull()
            response.close()
            if (parsed?.code == "session_revoked") {
                tokens.clear()
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
            val token = tokens.accessToken()
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

    private fun checkedResponse(response: Response): String {
        val raw = response.body.string()
        if (response.isSuccessful) return raw
        val parsed = runCatching { json.decodeFromString<ErrorEnvelope>(raw).error }.getOrNull()
        val retryAfter = parseRetryAfter(response.header("Retry-After"))
        throw ErrorMapper.http(response.code, parsed, retryAfter)
    }

    private fun parseRetryAfter(value: String?): Long? {
        value ?: return null
        value.toLongOrNull()?.let { return it.coerceAtLeast(0) }
        return runCatching {
            Duration.between(ZonedDateTime.now(), ZonedDateTime.parse(value, DateTimeFormatter.RFC_1123_DATE_TIME))
                .seconds.coerceAtLeast(0)
        }.getOrNull()
    }

    private suspend fun refreshSingleFlight(base: String, failedAccess: String?) = refreshMutex.withLock {
        if (tokens.accessToken() != null && tokens.accessToken() != failedAccess) return@withLock
        val refresh = tokens.refreshToken() ?: run {
            tokens.clear()
            throw AppFailure(AppErrorCode.REFRESH_FAILED, "La sesión venció. Inicia sesión nuevamente.", false)
        }
        try {
            val response: TokenResponse = call(
                "/api/v1/auth/refresh", "POST", json.encodeToString(RefreshRequest(refresh)),
                baseOverride = base, requiresAuth = false,
            )
            tokens.setTokens(response.accessToken, response.refreshToken)
        } catch (error: AppFailure) {
            if (refreshFailureDisposition(error) == RefreshFailureDisposition.PRESERVE_LOCAL_SESSION) {
                throw error
            }
            tokens.clear()
            if (error.code == AppErrorCode.DEVICE_REVOKED) throw error
            throw AppFailure(AppErrorCode.REFRESH_FAILED, "No fue posible renovar la sesión. Inicia sesión nuevamente.", false)
        }
    }

    private companion object {
        val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()
        val UUID_PATH_COMPONENT = Regex("/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}")
        val SERIALIZATION_PATH = Regex("(?:at path:?\\s*)(\\$[A-Za-z0-9_.$\\[\\]-]+)")
    }
}
