package io.healthtracker.companion.core.bluetooth

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.core.content.FileProvider
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.healthtracker.companion.BuildConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class BleManifestTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()

    @Test fun manifestDeclaresOnlyRequiredModernBluetoothPermissions() {
        val info = context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_PERMISSIONS)
        val permissions = info.requestedPermissions.orEmpty().toSet()
        assertTrue(Manifest.permission.BLUETOOTH_SCAN in permissions)
        assertTrue(Manifest.permission.BLUETOOTH_CONNECT in permissions)
        assertFalse(Manifest.permission.BLUETOOTH_ADVERTISE in permissions)
    }

    @Test fun bleHardwareIsOptional() {
        val features = context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_CONFIGURATIONS).reqFeatures.orEmpty()
        val ble = features.firstOrNull { it.name == PackageManager.FEATURE_BLUETOOTH_LE }
        assertNotNull(ble)
        assertFalse(ble!!.flags and android.content.pm.FeatureInfo.FLAG_REQUIRED != 0)
    }

    @Test fun fileProviderIsPrivateAndUsesAppAuthority() {
        val provider = context.packageManager.resolveContentProvider("${BuildConfig.APPLICATION_ID}.ble-captures", PackageManager.GET_META_DATA)
        assertNotNull(provider)
        assertFalse(provider!!.exported)
        assertTrue(provider.grantUriPermissions)
    }

    @Test fun apiPermissionResolverMatchesManifestPolicy() {
        assertEquals(setOf(Manifest.permission.ACCESS_FINE_LOCATION), requiredBlePermissionsFor(30))
        assertEquals(setOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT), requiredBlePermissionsFor(31))
    }
}
