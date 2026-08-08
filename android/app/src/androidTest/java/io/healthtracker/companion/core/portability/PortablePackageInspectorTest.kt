package io.healthtracker.companion.core.portability

import android.content.Context
import android.net.Uri
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.io.File
import java.security.MessageDigest
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PortablePackageInspectorTest {
    private val context: Context = ApplicationProvider.getApplicationContext()

    @Test fun validPackageIsInspectedLocallyWithoutReadingRecordContentIntoTheResult() {
        val file = validPackage("valid")
        try {
            val result = PortablePackageInspector(context.contentResolver).inspect(Uri.fromFile(file))
            assertEquals(PORTABLE_FORMAT, result.format)
            assertEquals("1.0", result.formatVersion)
            assertEquals(listOf("settings"), result.sections)
            assertEquals(1L, result.counts["settings"])
            assertEquals("verified", result.integrity)
            assertEquals("not_proven", result.authenticity)
            assertTrue(result.warnings.any { it.contains("autenticidad") })
        } finally {
            file.delete()
        }
    }

    @Test fun traversalAndChecksumMismatchAreRejectedBeforeUpload() {
        val traversal = File(context.cacheDir, "qa-traversal.htpack")
        ZipOutputStream(traversal.outputStream()).use { zip ->
            zip.putNextEntry(ZipEntry("../qa.json")); zip.write("{}".toByteArray()); zip.closeEntry()
        }
        val traversalError = runCatching {
            PortablePackageInspector(context.contentResolver).inspect(Uri.fromFile(traversal))
        }.exceptionOrNull() as PortablePackageException
        assertEquals("unsafe_path", traversalError.code)
        traversal.delete()

        val invalid = validPackage("bad-checksum", corruptPayload = true)
        val checksumError = runCatching {
            PortablePackageInspector(context.contentResolver).inspect(Uri.fromFile(invalid))
        }.exceptionOrNull() as PortablePackageException
        assertEquals("checksum_mismatch", checksumError.code)
        invalid.delete()
    }

    @Test fun managedFilesArePartitionedByAccountAndSharedWithAContentUri() {
        val store = PortableFileStore(context)
        val exportId = "00000000-0000-4000-8000-000000000017"
        val first = store.final("qa-scope-a", exportId)
        val second = store.final("qa-scope-b", exportId)
        assertNotEquals(first.parentFile, second.parentFile)
        first.writeText("QA package placeholder")
        second.writeText("QA package placeholder")
        val uri = store.shareUri("qa-scope-a", exportId)
        assertEquals("content", uri.scheme)
        store.deleteScope("qa-scope-a")
        assertFalse(first.exists())
        assertTrue(second.exists())
        store.deleteScope("qa-scope-b")
    }

    private fun validPackage(label: String, corruptPayload: Boolean = false): File {
        val payload = "{\"data\":{\"preferred_load_unit\":\"kg\"},\"public_id\":\"00000000-0000-4000-8000-000000000001\",\"revision\":1}\n".toByteArray()
        val payloadHash = sha256(payload)
        val manifest = ("{" +
            "\"counts\":{\"settings\":1}," +
            "\"export_id\":\"00000000-0000-4000-8000-000000000017\"," +
            "\"files\":[{\"path\":\"records/settings.json\",\"sha256\":\"$payloadHash\",\"size_bytes\":${payload.size}}]," +
            "\"format\":\"$PORTABLE_FORMAT\",\"format_version\":\"1.0\"," +
            "\"included_sections\":[\"settings\"],\"warnings\":[]}" +
            "\n").toByteArray()
        val checksums = ("{\"algorithm\":\"sha256\",\"files\":{" +
            "\"manifest.json\":\"${sha256(manifest)}\"," +
            "\"records/settings.json\":\"$payloadHash\"}}\n").toByteArray()
        val file = File(context.cacheDir, "qa-$label.htpack")
        ZipOutputStream(file.outputStream()).use { zip ->
            listOf(
                "manifest.json" to manifest,
                "records/settings.json" to if (corruptPayload) "corrupt\n".toByteArray() else payload,
                "checksums.json" to checksums,
            ).forEach { (name, bytes) ->
                zip.putNextEntry(ZipEntry(name)); zip.write(bytes); zip.closeEntry()
            }
        }
        return file
    }

    private fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes).joinToString("") { "%02x".format(it) }
}
