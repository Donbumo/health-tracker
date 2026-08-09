package io.healthtracker.companion.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import io.healthtracker.companion.MainActivity
import org.junit.Rule
import org.junit.Test

class LoginScreenTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()

    @Test fun loginScreenHasNativeAccessibleEntryPoint() {
        compose.onNodeWithTag("login_screen").assertIsDisplayed()
        compose.onNodeWithTag("login_button", useUnmergedTree = true).assertIsDisplayed()
    }
}
