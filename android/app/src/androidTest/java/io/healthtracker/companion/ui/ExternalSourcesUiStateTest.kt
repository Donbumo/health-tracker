package io.healthtracker.companion.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.healthtracker.companion.core.bluetooth.BleEnvironmentState
import io.healthtracker.companion.core.healthconnect.ScaleDiagnosticResult
import io.healthtracker.companion.core.healthconnect.ScaleDiagnosticStatus
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ExternalSourcesUiStateTest {
    @get:Rule val compose = createComposeRule()

    @Test fun uiWithoutBleKeepsOtherFeaturesAvailable() {
        compose.setContent { MaterialTheme { BleEnvironmentMessage(BleEnvironmentState.DEVICE_WITHOUT_BLE) } }
        compose.onNodeWithText("Este dispositivo no dispone de BLE. Health Connect y el resto de la app siguen funcionando.").assertIsDisplayed()
    }

    @Test fun uiDistinguishesBluetoothDisabled() {
        compose.setContent { MaterialTheme { BleEnvironmentMessage(BleEnvironmentState.BLUETOOTH_DISABLED) } }
        compose.onNodeWithText("Bluetooth está apagado; no equivale a permiso denegado.").assertIsDisplayed()
    }

    @Test fun uiExplainsContextualPermissionWithoutBlockingHealthConnect() {
        compose.setContent { MaterialTheme { BleEnvironmentMessage(BleEnvironmentState.PERMISSION_REQUIRED) } }
        compose.onNodeWithText("Se necesita permiso Bluetooth contextual. Denegarlo no afecta Health Connect, login ni entrenamientos.").assertIsDisplayed()
    }

    @Test fun experimentalUiNeverClaimsValidatedProtocol() {
        compose.setContent { MaterialTheme { ExperimentalProtocolNotice() } }
        compose.onNodeWithText("Experimental · Protocolo todavía no validado").assertIsDisplayed()
    }

    @Test fun healthConnectDiagnosticUiShowsOnlyAggregateData() {
        val result = ScaleDiagnosticResult(
            status = ScaleDiagnosticStatus.WEIGHT_FOUND,
            foundTypes = setOf("weight"),
            recordCount = 2,
            originCount = 1,
            firstDate = "2026-07-01T00:00:00Z",
            lastDate = "2026-07-02T00:00:00Z",
            importedCount = 1,
            notImportedCount = 1,
        )
        compose.setContent { MaterialTheme { ScaleDiagnosticSummary(result) } }
        compose.onNodeWithText("Se encontró peso.").assertIsDisplayed()
        compose.onNodeWithText("Tipos: weight · registros: 2 · orígenes: 1").assertIsDisplayed()
    }
}
