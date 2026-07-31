package io.healthtracker.companion.core.medical

import android.content.Context
import android.content.pm.PackageManager
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.healthtracker.companion.BuildConfig
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MedicalFileProviderTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()

    @Test fun medicalFileProviderIsPrivateAndGrantsOnlyTemporaryUris() {
        val provider = context.packageManager.resolveContentProvider(
            "${BuildConfig.APPLICATION_ID}.medical-documents", PackageManager.GET_META_DATA,
        )
        assertNotNull(provider)
        assertFalse(provider!!.exported)
        assertTrue(provider.grantUriPermissions)
    }
}
