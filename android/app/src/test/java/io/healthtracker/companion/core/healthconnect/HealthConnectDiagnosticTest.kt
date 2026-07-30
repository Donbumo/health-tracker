package io.healthtracker.companion.core.healthconnect

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HealthConnectDiagnosticTest {
    @Test fun sharedDiagnosticContainsOnlySanitizedMetadataAndCounts() {
        val diagnostic = sanitizedHealthConnectDiagnostic(
            HealthConnectDiagnosticContext("1.5.0-alpha01-debug", 15, "16", 36, pendingOperations = 3),
            HealthConnectUiState(
                status = HealthConnectUiStatus.PERMISSIONS_PARTIAL,
                selectedTypes = setOf(HealthConnectRecordType.WEIGHT, HealthConnectRecordType.STEPS),
                grantedTypes = setOf(HealthConnectRecordType.WEIGHT),
                backgroundAvailable = true,
                backgroundGranted = false,
                lastImportAt = "2026-07-27T12:34:56Z",
                importedCount = 2,
                deletedCount = 1,
                errorCode = "provider_io",
            ),
        )

        listOf("app=", "android=", "provider_state=permissions_partial", "provider_available=true",
            "provider_update_required=false", "selected_type_count=2", "selected_type_groups=activity,body",
            "granted_type_count=1", "granted_type_groups=body", "background_available=true",
            "background_authorized=false", "pending_operations=3", "imported_count=2", "last_import_at=",
            "error_code=provider_io")
            .forEach { assertTrue(diagnostic.contains(it)) }
        listOf("70.5", "8500", "record_id", "data_origin", "changes_token", "access_token", "refresh_token",
            "selected_types=", "weight", "steps", "nutrition")
            .forEach { assertFalse(diagnostic.contains(it)) }
        assertTrue(diagnostic.contains("last_import_at=2026-07-27T12:00:00Z"))
        assertFalse(diagnostic.contains("12:34:56"))
    }

    @Test fun unsafeErrorTextIsReducedToAStableCode() {
        val diagnostic = sanitizedHealthConnectDiagnostic(
            HealthConnectDiagnosticContext("qa", 15, "qa", 36),
            HealthConnectUiState(errorCode = "path=/private user@example.test"),
        )
        assertFalse(diagnostic.contains("/private"))
        assertFalse(diagnostic.contains("user@example.test"))
    }
}
