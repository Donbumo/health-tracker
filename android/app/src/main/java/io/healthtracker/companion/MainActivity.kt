package io.healthtracker.companion

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.enableEdgeToEdge
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import io.healthtracker.companion.ui.CompanionApp
import io.healthtracker.companion.ui.CompanionViewModel
import io.healthtracker.companion.ui.theme.HealthTrackerTheme

class MainActivity : ComponentActivity() {
    private val viewModel: CompanionViewModel by viewModels {
        CompanionViewModel.Factory((application as HealthTrackerApplication).container)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val preferences by viewModel.preferences.collectAsState()
            HealthTrackerTheme(preferences.theme) {
                CompanionApp(viewModel)
            }
        }
    }
}
