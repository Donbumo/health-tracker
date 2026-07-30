package io.healthtracker.companion.core.bluetooth

import android.content.Context
import android.net.Uri
import androidx.core.content.FileProvider
import io.healthtracker.companion.core.external.shortFingerprint
import java.io.File
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import java.security.MessageDigest
import java.util.Base64
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

const val BLE_CAPTURE_FORMAT = "ble-capture-v1"

@Serializable
data class BleCaptureEvent(
    val serviceUuid: String? = null,
    val characteristicUuid: String? = null,
    val eventType: String,
    val relativeTimestampMs: Long,
    val payload: String? = null,
    val connectionState: String? = null,
    val error: String? = null,
)

@Serializable
data class BleExpectedResult(
    val protocolState: String,
    val fixtureFictional: Boolean = true,
)

@Serializable
data class BleCapture(
    val formatVersion: String = BLE_CAPTURE_FORMAT,
    val sourceType: String = "xiaomi_s400_ble_experimental",
    val captureId: String,
    val deviceFingerprint: String,
    val sessionStart: Long = 0,
    val events: List<BleCaptureEvent>,
    val expectedResult: BleExpectedResult? = null,
    val fixtureFictional: Boolean? = null,
)

data class BleCaptureLimits(
    val maximumDurationMs: Long = 90_000,
    val maximumBytes: Int = 256 * 1024,
    val maximumEvents: Int = 2_000,
) {
    init {
        require(maximumDurationMs in 1_000..180_000)
        require(maximumBytes in 1_024..1_048_576)
        require(maximumEvents in 1..10_000)
    }
}

data class StoredBleCapture(
    val captureId: String,
    val encryptedFileName: String,
    val eventCount: Int,
    val byteCount: Int,
    val durationMs: Long,
    val checksum: String,
)

class BleCaptureCodec(
    private val json: Json = Json { ignoreUnknownKeys = false; explicitNulls = false; encodeDefaults = true },
    private val limits: BleCaptureLimits = BleCaptureLimits(),
) {
    fun serialize(capture: BleCapture): ByteArray {
        validate(capture)
        return json.encodeToString(capture).toByteArray(StandardCharsets.UTF_8)
    }

    fun parse(bytes: ByteArray): BleCapture {
        require(bytes.size <= limits.maximumBytes * 2) { "capture_file_too_large" }
        val capture = runCatching { json.decodeFromString<BleCapture>(bytes.toString(StandardCharsets.UTF_8)) }
            .getOrElse { throw IllegalArgumentException("capture_invalid", it) }
        validate(capture)
        return capture
    }

    fun validate(capture: BleCapture) {
        require(capture.formatVersion == BLE_CAPTURE_FORMAT) { "capture_version_unsupported" }
        require(capture.sourceType == "xiaomi_s400_ble_experimental") { "capture_source_unsupported" }
        require(capture.captureId.matches(Regex("[A-Za-z0-9_-]{8,80}"))) { "capture_id_invalid" }
        require(capture.deviceFingerprint.matches(Regex("[a-f0-9]{12,64}"))) { "capture_fingerprint_invalid" }
        require(capture.sessionStart == 0L) { "capture_absolute_time_forbidden" }
        require(capture.events.size <= limits.maximumEvents) { "capture_event_limit" }
        var totalBytes = 0
        var previous = -1L
        capture.events.forEach { event ->
            require(event.relativeTimestampMs >= previous && event.relativeTimestampMs <= limits.maximumDurationMs) { "capture_timestamp_invalid" }
            previous = event.relativeTimestampMs
            require(event.eventType in setOf("notification", "read", "connection", "error")) { "capture_event_type_invalid" }
            require(event.error == null || event.error.matches(Regex("[a-z0-9_]{1,64}"))) { "capture_error_invalid" }
            event.payload?.let {
                val decoded = runCatching { Base64.getDecoder().decode(it) }.getOrElse { throw IllegalArgumentException("capture_payload_invalid") }
                totalBytes += decoded.size
            }
        }
        require(totalBytes <= limits.maximumBytes) { "capture_byte_limit" }
    }

    fun checksum(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
}

class ExperimentalBleCaptureSession(
    private val stream: BleNotificationStream,
    private val limits: BleCaptureLimits = BleCaptureLimits(),
) {
    suspend fun capture(deviceFingerprint: String): BleCapture {
        val events = mutableListOf<BleCaptureEvent>()
        var bytes = 0
        val started = System.nanoTime()
        try {
            withTimeout(limits.maximumDurationMs) {
                stream.notifications.collect { notification ->
                    if (notification.payload.size + bytes > limits.maximumBytes) throw CaptureTerminal("byte_limit")
                    if (events.size >= limits.maximumEvents) throw CaptureTerminal("event_limit")
                    bytes += notification.payload.size
                    events += BleCaptureEvent(
                        serviceUuid = notification.serviceUuid.lowercase(),
                        characteristicUuid = notification.characteristicUuid.lowercase(),
                        eventType = "notification",
                        relativeTimestampMs = notification.relativeTimestampMs.coerceAtLeast(0),
                        payload = Base64.getEncoder().encodeToString(notification.payload),
                    )
                }
            }
        } catch (_: kotlinx.coroutines.TimeoutCancellationException) {
            events += BleCaptureEvent(eventType = "connection", relativeTimestampMs = elapsedMillis(started).coerceAtMost(limits.maximumDurationMs), connectionState = "timeout")
        } catch (terminal: CaptureTerminal) {
            events += BleCaptureEvent(eventType = "connection", relativeTimestampMs = elapsedMillis(started).coerceAtMost(limits.maximumDurationMs), connectionState = terminal.code)
        } finally {
            stream.close()
        }
        return BleCapture(
            captureId = "cap_${UUID.randomUUID().toString().replace("-", "")}",
            deviceFingerprint = deviceFingerprint,
            events = events.sortedBy { it.relativeTimestampMs },
        )
    }

    private fun elapsedMillis(started: Long) = (System.nanoTime() - started) / 1_000_000
    private class CaptureTerminal(val code: String) : RuntimeException(code)
}

class EncryptedBleCaptureStore(
    private val context: Context,
    private val codec: BleCaptureCodec = BleCaptureCodec(),
) : BleCaptureStore {
    private val directory = File(context.noBackupFilesDir, "ble-captures").also { directory ->
        require(directory.exists() || directory.mkdirs())
        directory.listFiles().orEmpty().filter { it.isFile && it.name.endsWith(".blec.deleting") }.forEach(File::delete)
    }
    private val keyAlias = "health_tracker_ble_capture_v1"

    override suspend fun save(capture: BleCapture): StoredBleCapture {
        val plaintext = codec.serialize(capture)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val encrypted = cipher.doFinal(plaintext)
        val fileName = "${UUID.randomUUID()}.blec"
        val temporary = File(directory, "$fileName.tmp")
        val target = File(directory, fileName)
        temporary.outputStream().use { output ->
            output.write(byteArrayOf(1, cipher.iv.size.toByte()))
            output.write(cipher.iv)
            output.write(encrypted)
        }
        require(temporary.renameTo(target)) { "capture_atomic_move_failed" }
        return StoredBleCapture(
            captureId = capture.captureId,
            encryptedFileName = fileName,
            eventCount = capture.events.size,
            byteCount = plaintext.size,
            durationMs = capture.events.maxOfOrNull { it.relativeTimestampMs } ?: 0,
            checksum = codec.checksum(plaintext),
        )
    }

    override suspend fun load(captureId: String): BleCapture {
        val match = directory.listFiles().orEmpty().firstOrNull { file ->
            runCatching { decrypt(file).captureId == captureId }.getOrDefault(false)
        } ?: throw IllegalArgumentException("capture_not_found")
        return decrypt(match)
    }

    override suspend fun delete(captureId: String): Boolean {
        val match = directory.listFiles().orEmpty().firstOrNull { file ->
            runCatching { decrypt(file).captureId == captureId }.getOrDefault(false)
        } ?: return false
        val tombstone = File(directory, "${match.name}.deleting")
        if (!match.renameTo(tombstone)) return false
        return tombstone.delete()
    }

    fun deleteEncryptedFile(fileName: String): Boolean {
        if (!fileName.matches(Regex("[0-9a-fA-F-]{36}\\.blec"))) return false
        val target = File(directory, fileName)
        if (target.parentFile?.canonicalFile != directory.canonicalFile) return false
        if (!target.exists()) return true
        if (!target.isFile) return false
        val tombstone = File(directory, "$fileName.deleting")
        if (!target.renameTo(tombstone)) return false
        return tombstone.delete()
    }

    suspend fun deleteWithMetadata(fileName: String, removeMetadata: suspend () -> Unit): Boolean {
        if (!fileName.matches(Regex("[0-9a-fA-F-]{36}\\.blec"))) return false
        val target = File(directory, fileName)
        if (target.parentFile?.canonicalFile != directory.canonicalFile) return false
        if (!target.exists()) {
            removeMetadata()
            return true
        }
        val tombstone = File(directory, "$fileName.deleting")
        if (!target.renameTo(tombstone)) return false
        try {
            removeMetadata()
        } catch (failure: Throwable) {
            tombstone.renameTo(target)
            throw failure
        }
        return tombstone.delete()
    }

    fun encryptedFileName(captureId: String): String? = directory.listFiles().orEmpty().firstOrNull { file ->
        runCatching { decrypt(file).captureId == captureId }.getOrDefault(false)
    }?.name

    private fun decrypt(file: File): BleCapture {
        require(file.parentFile?.canonicalFile == directory.canonicalFile) { "capture_path_invalid" }
        val bytes = file.readBytes()
        require(bytes.size > 14 && bytes[0].toInt() == 1) { "capture_envelope_invalid" }
        val ivSize = bytes[1].toInt() and 0xff
        require(ivSize in 12..16 && bytes.size > 2 + ivSize) { "capture_iv_invalid" }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(2, 2 + ivSize)))
        return codec.parse(cipher.doFinal(bytes.copyOfRange(2 + ivSize, bytes.size)))
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(keyAlias, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance("AES", "AndroidKeyStore")
        generator.init(
            android.security.keystore.KeyGenParameterSpec.Builder(
                keyAlias,
                android.security.keystore.KeyProperties.PURPOSE_ENCRYPT or android.security.keystore.KeyProperties.PURPOSE_DECRYPT,
            ).setBlockModes(android.security.keystore.KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(android.security.keystore.KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }
}

class DeterministicBleReplaySource(private val preserveDelays: Boolean = false) : BleReplaySource {
    override fun replay(capture: BleCapture): Flow<BleCaptureEvent> = flow {
        var previous = 0L
        capture.events.sortedBy { it.relativeTimestampMs }.forEach { event ->
            if (preserveDelays) delay((event.relativeTimestampMs - previous).coerceAtLeast(0))
            emit(event)
            previous = event.relativeTimestampMs
        }
    }
}

class Base64BleFrameDecoder : BleFrameDecoder {
    override fun decode(event: BleCaptureEvent): DecodedBleFrame {
        val bytes = event.payload?.let { Base64.getDecoder().decode(it) } ?: byteArrayOf()
        return DecodedBleFrame(bytes.size, shortFingerprint(bytes.joinToString(",") { (it.toInt() and 0xff).toString() }), bytes)
    }
}

class BleCaptureExporter(
    private val context: Context,
    private val store: BleCaptureStore,
    private val codec: BleCaptureCodec = BleCaptureCodec(),
) {
    suspend fun prepareExplicitExport(captureId: String): Uri {
        val exportDirectory = File(context.filesDir, "ble-exports").also { require(it.exists() || it.mkdirs()) }
        val file = File(exportDirectory, "capture-${UUID.randomUUID()}.json")
        file.outputStream().use { it.write(codec.serialize(store.load(captureId))) }
        return FileProvider.getUriForFile(context, "${context.packageName}.ble-captures", file)
    }

    fun revokeAndDelete(uri: Uri) {
        context.revokeUriPermission(uri, android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
        val name = uri.lastPathSegment?.substringAfterLast('/') ?: return
        File(context.filesDir, "ble-exports/$name").takeIf { it.parentFile?.canonicalFile == File(context.filesDir, "ble-exports").canonicalFile }?.delete()
    }

    fun cleanupTemporaryExports() {
        File(context.filesDir, "ble-exports").listFiles().orEmpty().forEach { file ->
            if (file.isFile && file.parentFile?.canonicalFile == File(context.filesDir, "ble-exports").canonicalFile) file.delete()
        }
    }
}
