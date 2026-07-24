package io.healthtracker.companion.core.security

object Redaction {
    private val sensitive = Regex(
        "(?i)(authorization|access[_-]?token|refresh[_-]?token|password|cookie|secret)\\s*[:=]\\s*[^,\\s}]+",
    )

    fun sanitize(message: String): String = message
        .replace(sensitive) { match -> "${match.groupValues[1]}=[REDACTED]" }
        .take(500)

    fun diagnosticCode(value: String?): String? = value
        ?.replace(Regex("[^a-zA-Z0-9_.-]"), "_")
        ?.take(64)
}
