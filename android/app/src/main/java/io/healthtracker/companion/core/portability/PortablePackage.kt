package io.healthtracker.companion.core.portability

import android.content.ContentResolver
import android.content.Context
import android.net.Uri
import androidx.core.content.FileProvider
import io.healthtracker.companion.BuildConfig
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.time.Instant
import java.time.temporal.ChronoUnit
import java.util.Locale
import java.util.UUID
import java.util.zip.ZipException
import java.util.zip.ZipInputStream
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

const val PORTABLE_FORMAT = "health-tracker-portable-v1"
const val PORTABLE_MIME = "application/vnd.health-tracker.portable+zip"
const val PORTABLE_HEALTH_WARNING = "Este archivo puede contener información corporal, alimentaria y de entrenamiento."

data class LocalPortableInspection(
    val packageSha256: String,
    val sizeBytes: Long,
    val format: String,
    val formatVersion: String,
    val exportId: String,
    val sections: List<String>,
    val counts: Map<String, Long>,
    val files: Map<String, Long>,
    val warnings: List<String>,
    val integrity: String = "verified",
    val authenticity: String = "not_proven",
)

class PortablePackageException(val code: String, message: String) : IllegalArgumentException(message)

class PortablePackageInspector(
    private val resolver: ContentResolver,
    private val maxCompressedBytes: Long = 50L * 1024 * 1024,
    private val maxUncompressedBytes: Long = 200L * 1024 * 1024,
    private val maxFileBytes: Long = 50L * 1024 * 1024,
    private val maxFiles: Int = 256,
) {
    private val json = Json { ignoreUnknownKeys = false; isLenient = false; coerceInputValues = false }

    fun inspect(uri: Uri): LocalPortableInspection {
        val packageDigest = MessageDigest.getInstance("SHA-256")
        var packageSize = 0L
        resolver.openInputStream(uri)?.use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                packageSize += read
                if (packageSize > maxCompressedBytes) fail("package_too_large", "El paquete supera el límite local.")
                packageDigest.update(buffer, 0, read)
            }
        } ?: fail("file_unavailable", "Ya no se puede leer el archivo seleccionado.")
        if (packageSize == 0L) fail("invalid_archive", "El archivo está vacío.")

        val members = linkedMapOf<String, Pair<String, Long>>()
        val names = mutableSetOf<String>()
        var manifestBytes: ByteArray? = null
        var checksumsBytes: ByteArray? = null
        var total = 0L
        try {
            resolver.openInputStream(uri)?.use { raw ->
                ZipInputStream(raw).use { zip ->
                    while (true) {
                        val entry = zip.nextEntry ?: break
                        val name = entry.name
                        validateName(name)
                        if (entry.isDirectory) fail("special_file", "No se permiten directorios explícitos.")
                        val folded = name.lowercase(Locale.ROOT)
                        if (!names.add(folded)) fail("duplicate_file", "Hay archivos duplicados o ambiguos.")
                        if (names.size > maxFiles) fail("too_many_files", "El paquete contiene demasiados archivos.")
                        val digest = MessageDigest.getInstance("SHA-256")
                        val collected = if (name == "manifest.json" || name == "checksums.json") java.io.ByteArrayOutputStream() else null
                        var size = 0L
                        val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                        while (true) {
                            val read = zip.read(buffer)
                            if (read < 0) break
                            size += read; total += read
                            if (size > maxFileBytes) fail("file_too_large", "Un archivo supera el límite local.")
                            if (total > maxUncompressedBytes) fail("archive_too_large", "El paquete descomprimido supera el límite local.")
                            digest.update(buffer, 0, read)
                            collected?.write(buffer, 0, read)
                        }
                        members[name] = digest.hex() to size
                        if (name == "manifest.json") manifestBytes = collected!!.toByteArray()
                        if (name == "checksums.json") checksumsBytes = collected!!.toByteArray()
                        zip.closeEntry()
                    }
                }
            } ?: fail("file_unavailable", "Ya no se puede leer el archivo seleccionado.")
        } catch (error: ZipException) {
            if (error.message.orEmpty().contains("entry path", ignoreCase = true)) {
                fail("unsafe_path", "El paquete contiene traversal o una ruta absoluta.")
            }
            fail("invalid_archive", "El archivo ZIP no es válido.")
        }
        val manifestRaw = manifestBytes ?: fail("manifest_missing", "Falta manifest.json.")
        val checksumRaw = checksumsBytes ?: fail("checksums_missing", "Falta checksums.json.")
        val manifest = decodeObject(manifestRaw, "manifest.json")
        val checksums = decodeObject(checksumRaw, "checksums.json")
        val format = manifest.text("format")
        val version = manifest.text("format_version")
        if (format != PORTABLE_FORMAT || version != "1.0") fail("unsupported_format", "El formato no es compatible.")
        val exportId = manifest.text("export_id")
        runCatching { UUID.fromString(exportId) }.getOrElse { fail("invalid_manifest", "export_id no es UUID.") }
        if (checksums.text("algorithm") != "sha256") fail("unsupported_checksum", "El algoritmo de checksum no es compatible.")
        val checksumFiles = checksums["files"]?.jsonObject ?: fail("checksums_incomplete", "Falta la lista de checksums.")
        val expected = mutableMapOf("manifest.json" to (manifestRaw.sha256()))
        val declaredSizes = mutableMapOf<String, Long>()
        val declaredRows = manifest["files"]?.jsonArray ?: fail("invalid_manifest", "Falta files en manifest.")
        declaredRows.forEach { element ->
            val row = element.jsonObject
            val name = row.text("path")
            validateName(name)
            expected[name] = row.text("sha256")
            declaredSizes[name] = row["size_bytes"]?.jsonPrimitive?.content?.toLongOrNull()
                ?: fail("invalid_manifest", "Un tamaño del manifest no es válido.")
        }
        val expectedNames = expected.keys + "checksums.json"
        if (members.keys != expectedNames) fail("undeclared_file", "Hay archivos ausentes o no declarados.")
        if (checksumFiles.keys != expected.keys) fail("checksums_incomplete", "checksums.json no cubre todos los archivos.")
        expected.forEach { (name, hash) ->
            val actual = members[name] ?: fail("file_missing", "Falta un archivo declarado.")
            if (actual.first != hash || checksumFiles[name]?.jsonPrimitive?.content != hash) {
                fail("checksum_mismatch", "Un checksum no coincide.")
            }
            if (name != "manifest.json" && actual.second != declaredSizes[name]) fail("size_mismatch", "Un tamaño no coincide.")
        }
        val sections = manifest["included_sections"]?.jsonArray?.map { it.jsonPrimitive.content }
            ?: fail("invalid_manifest", "Faltan secciones.")
        if (sections.size != sections.distinct().size) fail("invalid_manifest", "Hay secciones duplicadas.")
        val counts = manifest["counts"]?.jsonObject?.mapValues { it.value.jsonPrimitive.content.toLongOrNull()
            ?: fail("invalid_manifest", "Un conteo no es válido.") } ?: emptyMap()
        val warnings = manifest["warnings"]?.jsonArray?.map { it.jsonPrimitive.content } ?: emptyList()
        return LocalPortableInspection(
            packageSha256 = packageDigest.hex(), sizeBytes = packageSize, format = format,
            formatVersion = version, exportId = exportId, sections = sections,
            counts = counts, files = declaredSizes, warnings = warnings + listOf(
                PORTABLE_HEALTH_WARNING,
                "Los checksums prueban integridad, no autenticidad; el servidor debe repetir la verificación.",
            ),
        )
    }

    private fun decodeObject(bytes: ByteArray, label: String): JsonObject = try {
        json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
    } catch (_: Exception) {
        fail("invalid_json", "$label no contiene JSON UTF-8 válido.")
    }

    private fun validateName(name: String) {
        if (!PortabilityPolicy.isSafeArchiveName(name)) {
            fail("unsafe_path", "El paquete contiene traversal o una ruta absoluta.")
        }
    }

    private fun JsonObject.text(name: String): String = this[name]?.jsonPrimitive?.content
        ?: fail("invalid_manifest", "Falta $name.")

    private fun fail(code: String, message: String): Nothing = throw PortablePackageException(code, message)
}

class PortableFileStore(private val context: Context) {
    private val root = File(context.filesDir, "portability").apply { mkdirs() }

    fun partial(scope: String, exportId: String): File = File(scopeRoot(scope), safeUuid(exportId) + ".partial")
    fun final(scope: String, exportId: String): File = File(scopeRoot(scope), safeUuid(exportId) + ".htpack")

    fun finalize(scope: String, exportId: String, expectedSha256: String, expectedBytes: Long?): File {
        val partial = partial(scope, exportId)
        if (!partial.isFile) throw PortablePackageException("partial_missing", "Falta la descarga parcial.")
        val digest = partial.inputStream().use { it.sha256() }
        if (digest != expectedSha256 || (expectedBytes != null && partial.length() != expectedBytes)) {
            partial.delete()
            throw PortablePackageException("download_hash_mismatch", "La descarga no coincide con el SHA-256 del servidor.")
        }
        val final = final(scope, exportId)
        if (final.exists()) final.delete()
        if (!partial.renameTo(final)) throw PortablePackageException("file_move_failed", "No se pudo finalizar la descarga.")
        return final
    }

    fun delete(scope: String, exportId: String) {
        partial(scope, exportId).delete(); final(scope, exportId).delete()
    }

    fun shareUri(scope: String, exportId: String): Uri {
        val file = final(scope, exportId)
        if (!file.isFile) throw PortablePackageException("file_missing", "El paquete local no existe.")
        return FileProvider.getUriForFile(context, BuildConfig.APPLICATION_ID + ".portability", file)
    }

    fun copyTo(scope: String, exportId: String, destination: Uri) {
        val source = final(scope, exportId)
        if (!source.isFile) throw PortablePackageException("file_missing", "El paquete local no existe.")
        context.contentResolver.openOutputStream(destination, "w")?.use { output ->
            source.inputStream().use { it.copyTo(output) }
        } ?: throw PortablePackageException("destination_unavailable", "No se pudo escribir en el destino seleccionado.")
    }

    fun cleanup(now: Instant = Instant.now()) {
        val cutoff = now.minus(48, ChronoUnit.HOURS).toEpochMilli()
        root.walkBottomUp().filter { it != root && it.isFile && it.lastModified() < cutoff }.forEach(File::delete)
        root.listFiles()?.filter { it.isDirectory && it.listFiles().isNullOrEmpty() }?.forEach(File::delete)
        File(context.cacheDir, "portability-share").deleteRecursively()
    }

    fun deleteScope(scope: String) {
        scopeRoot(scope, create = false).takeIf(File::exists)?.deleteRecursively()
    }

    private fun scopeRoot(scope: String, create: Boolean = true): File {
        require(scope.isNotBlank()) { "account_scope_required" }
        val digest = MessageDigest.getInstance("SHA-256").digest(scope.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
            .take(24)
        return File(root, digest).also { if (create) it.mkdirs() }
    }

    private fun safeUuid(value: String): String = UUID.fromString(value).toString()
}

private fun MessageDigest.hex(): String = digest().joinToString("") { "%02x".format(it) }
private fun ByteArray.sha256(): String = MessageDigest.getInstance("SHA-256").digest(this).joinToString("") { "%02x".format(it) }
private fun java.io.InputStream.sha256(): String {
    val digest = MessageDigest.getInstance("SHA-256")
    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
    while (true) {
        val read = read(buffer)
        if (read < 0) break
        digest.update(buffer, 0, read)
    }
    return digest.hex()
}
