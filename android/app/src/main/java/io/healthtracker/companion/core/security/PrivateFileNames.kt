package io.healthtracker.companion.core.security

import java.security.MessageDigest

/** Builds deterministic private filenames without trusting remote identifiers as path segments. */
internal object PrivateFileNames {
    private val safeLabel = Regex("[a-z][a-z0-9-]{0,31}")
    private val safeExtension = Regex("[a-z0-9]{1,8}")

    fun opaque(label: String, remoteIdentifier: String, extension: String): String {
        require(safeLabel.matches(label)) { "private_file_label_invalid" }
        require(safeExtension.matches(extension)) { "private_file_extension_invalid" }
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(remoteIdentifier.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
        return "$label-${digest.take(32)}.$extension"
    }
}
