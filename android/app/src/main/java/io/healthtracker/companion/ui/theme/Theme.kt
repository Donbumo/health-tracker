package io.healthtracker.companion.ui.theme

import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat
import io.healthtracker.companion.core.config.ThemePreference

private val LightColors = lightColorScheme(
    primary = Color(0xFF006A60), onPrimary = Color.White,
    secondary = Color(0xFF4A635E), background = Color(0xFFF5FBF8),
    surface = Color(0xFFF5FBF8), error = Color(0xFFBA1A1A),
)
private val DarkColors = darkColorScheme(
    primary = Color(0xFF53DBC8), onPrimary = Color(0xFF003731),
    secondary = Color(0xFFB1CCC5), background = Color(0xFF0E1513),
    surface = Color(0xFF0E1513), error = Color(0xFFFFB4AB),
)

@Composable
fun HealthTrackerTheme(preference: ThemePreference, content: @Composable () -> Unit) {
    val dark = when (preference) {
        ThemePreference.SYSTEM -> isSystemInDarkTheme()
        ThemePreference.LIGHT -> false
        ThemePreference.DARK -> true
    }
    val colors = if (dark) DarkColors else LightColors
    val view = LocalView.current
    if (!view.isInEditMode) SideEffect {
        val window = (view.context as Activity).window
        WindowCompat.getInsetsController(window, view).apply {
            isAppearanceLightStatusBars = !dark
            isAppearanceLightNavigationBars = !dark
        }
    }
    MaterialTheme(colorScheme = colors, content = content)
}
