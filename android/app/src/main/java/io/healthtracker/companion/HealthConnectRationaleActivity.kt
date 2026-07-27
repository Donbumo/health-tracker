package io.healthtracker.companion

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.healthtracker.companion.ui.theme.HealthTrackerTheme

/** Privacy rationale opened by Health Connect; it never displays imported values. */
class HealthConnectRationaleActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            HealthTrackerTheme(io.healthtracker.companion.core.config.ThemePreference.SYSTEM) {
                HealthConnectRationale()
            }
        }
    }
}

@Composable
private fun HealthConnectRationale() {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("Privacidad de Health Connect", style = MaterialTheme.typography.headlineMedium)
        Text(
            "Health Tracker solo lee los tipos que eliges. Primero guarda la importación en este dispositivo y después la sincroniza con tu servidor privado cuando hay red.",
        )
        Text(
            "Puedes pausar, desconectar, administrar permisos o borrar únicamente los datos importados desde Ajustes. Los datos manuales no se sustituyen ni se borran automáticamente.",
        )
        Text(
            "No escribimos datos en Health Connect y no solicitamos expedientes médicos, signos vitales, sueño ni sesiones de ejercicio.",
        )
    }
}
