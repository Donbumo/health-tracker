package io.healthtracker.companion.core.bluetooth

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.io.File
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class BleCaptureStoreTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()

    @Test fun captureIsEncryptedOutsideBackupAndCanBeDeleted() = runTest {
        val store = EncryptedBleCaptureStore(context)
        val capture = BleCapture(
            captureId = "cap_android_fixture_0001",
            deviceFingerprint = "abcdef123456",
            events = listOf(BleCaptureEvent(eventType = "connection", relativeTimestampMs = 0, connectionState = "fixture")),
            fixtureFictional = true,
        )
        val metadata = store.save(capture)
        val file = File(context.noBackupFilesDir, "ble-captures/${metadata.encryptedFileName}")
        assertTrue(file.isFile)
        assertFalse(file.readText(Charsets.ISO_8859_1).contains("cap_android_fixture_0001"))
        assertEquals(capture, store.load(capture.captureId))
        assertTrue(store.delete(capture.captureId))
        assertFalse(file.exists())
    }

    @Test fun explicitExportUsesPrivateFileProviderAndCanBeRevoked() = runTest {
        val store = EncryptedBleCaptureStore(context)
        val capture = BleCapture(
            captureId = "cap_android_fixture_0002",
            deviceFingerprint = "abcdef123456",
            events = emptyList(),
            fixtureFictional = true,
        )
        store.save(capture)
        val exporter = BleCaptureExporter(context, store)
        val uri = exporter.prepareExplicitExport(capture.captureId)
        assertEquals("content", uri.scheme)
        assertEquals("${context.packageName}.ble-captures", uri.authority)
        exporter.revokeAndDelete(uri)
        store.delete(capture.captureId)
    }
}
