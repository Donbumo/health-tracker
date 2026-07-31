package io.healthtracker.companion.core.portability

object PortabilityPolicy {
    fun validateExportRequest(request: PortableExportRequest) {
        require(request.sections.isNotEmpty()) { "sections_required" }
        require("attachments" !in request.sections || request.includeAttachments || request.includeMedicalAttachments) {
            "attachments_confirmation_required"
        }
        if (request.includeMedicalAttachments) {
            require(setOf("attachments", "medical_studies", "lab_panels", "lab_results", "medical_documents_metadata").all {
                it in request.sections
            }) { "medical_sections_required" }
        }
        require("profile" !in request.sections || request.includeIdentifiableProfile) { "profile_confirmation_required" }
        require(request.dateFrom == null || request.dateTo == null || request.dateFrom <= request.dateTo) { "invalid_date_range" }
    }

    fun isSafeArchiveName(name: String): Boolean {
        if (name.isBlank() || name.length > 255 || name.any { it.code > 127 || it == '\\' || it == '\u0000' }) return false
        val parts = name.split('/')
        if (name.startsWith('/') || (parts.firstOrNull()?.getOrNull(1) == ':')) return false
        return parts.none { it.isBlank() || it == "." || it == ".." }
    }
}
