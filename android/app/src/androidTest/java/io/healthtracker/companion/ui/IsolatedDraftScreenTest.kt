package io.healthtracker.companion.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import org.junit.Rule
import org.junit.Test

class IsolatedDraftScreenTest {
    @get:Rule val compose = createComposeRule()

    @Test fun isolatedDraftIsTerminalAndOffersRecoverableActionsWithoutSpinner() {
        compose.setContent {
            MaterialTheme {
                IsolatedDraftScreen(
                    reasonCode = "draft_package_mismatch",
                    onBack = {},
                    onDiscard = {},
                )
            }
        }

        compose.onNodeWithTag("isolated_draft_screen").assertIsDisplayed()
        compose.onAllNodesWithTag("loading_indicator").assertCountEquals(0)
        compose.onNodeWithText("Volver a Hoy").assertIsDisplayed()
        compose.onNodeWithText("Ver motivo sanitizado").performClick()
        compose.onNodeWithText("Identidad o hash del package no coincide").assertIsDisplayed()
        compose.onNodeWithText("Descartar borrador").assertIsDisplayed()
    }
}
