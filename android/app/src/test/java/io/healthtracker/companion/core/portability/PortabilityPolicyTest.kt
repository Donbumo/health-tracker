package io.healthtracker.companion.core.portability

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PortabilityPolicyTest {
    @Test fun attachmentsAndIdentifiableProfileRequireExplicitConsent() {
        assertFailure("attachments_confirmation_required") {
            PortabilityPolicy.validateExportRequest(PortableExportRequest(setOf("attachments")))
        }
        assertFailure("profile_confirmation_required") {
            PortabilityPolicy.validateExportRequest(PortableExportRequest(setOf("profile")))
        }
        PortabilityPolicy.validateExportRequest(PortableExportRequest(setOf("medical_documents_metadata")))
        assertFailure("medical_sections_required") {
            PortabilityPolicy.validateExportRequest(PortableExportRequest(
                setOf("attachments"), includeMedicalAttachments = true,
            ))
        }
        PortabilityPolicy.validateExportRequest(PortableExportRequest(
            setOf("profile", "attachments", "medical_studies", "lab_panels", "lab_results", "medical_documents_metadata"),
            includeAttachments = true,
            includeMedicalAttachments = true, includeIdentifiableProfile = true,
        ))
    }

    @Test fun invalidDateRangeAndEmptySelectionAreRejectedBeforeQueueing() {
        assertFailure("sections_required") { PortabilityPolicy.validateExportRequest(PortableExportRequest(emptySet())) }
        assertFailure("invalid_date_range") {
            PortabilityPolicy.validateExportRequest(PortableExportRequest(setOf("settings"), "2026-08-01", "2026-07-01"))
        }
    }

    @Test fun archiveNamesRejectTraversalAbsoluteAlternateSeparatorUnicodeAndEmptyParts() {
        listOf("../qa.json", "/qa.json", "C:/qa.json", "records\\qa.json", "récords/qa.json", "records//qa.json")
            .forEach { assertFalse(it, PortabilityPolicy.isSafeArchiveName(it)) }
        assertTrue(PortabilityPolicy.isSafeArchiveName("records/body_stats.jsonl"))
        assertTrue(PortabilityPolicy.isSafeArchiveName("attachments/00000000-0000-4000-8000-000000000017/qa.txt"))
    }

    private fun assertFailure(code: String, block: () -> Unit) {
        val failure = runCatching(block).exceptionOrNull()
        assertTrue(failure is IllegalArgumentException)
        assertTrue(failure?.message == code)
    }
}
