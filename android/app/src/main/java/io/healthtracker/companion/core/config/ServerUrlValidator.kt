package io.healthtracker.companion.core.config

import io.healthtracker.companion.BuildConfig
import java.net.IDN
import java.net.Inet4Address
import java.net.InetAddress
import java.net.URI

data class ServerValidation(val normalizedUrl: String? = null, val error: String? = null) {
    val valid: Boolean get() = normalizedUrl != null
}

object ServerUrlValidator {
    fun validate(raw: String, explicitLocalHttp: Boolean): ServerValidation {
        val candidate = raw.trim()
        val uri = runCatching { URI(candidate) }.getOrNull()
            ?: return ServerValidation(error = "La URL no tiene un formato válido.")
        val scheme = uri.scheme?.lowercase()
        if (scheme !in setOf("https", "http")) {
            return ServerValidation(error = "Solo se permiten URLs HTTPS o HTTP local explícito.")
        }
        if (uri.userInfo != null || uri.query != null || uri.fragment != null) {
            return ServerValidation(error = "La URL no puede contener credenciales, consulta ni fragmento.")
        }
        val host = uri.host?.let { runCatching { IDN.toASCII(it.lowercase()) }.getOrNull() }
            ?: return ServerValidation(error = "Falta un hostname válido.")
        if (uri.port !in -1..65535) {
            return ServerValidation(error = "El puerto del servidor no es válido.")
        }
        if (scheme == "http") {
            if (!BuildConfig.ALLOW_LOCAL_HTTP || !explicitLocalHttp) {
                return ServerValidation(error = "HTTP solo está disponible en debug y requiere confirmación explícita.")
            }
            if (!isLocalDevelopmentHost(host)) {
                return ServerValidation(error = "HTTP se limita a loopback, emulador, RFC1918 o nombres .local.")
            }
        }
        val rawPath = uri.rawPath.orEmpty()
        val normalizedPath = when {
            rawPath.isBlank() || rawPath == "/" -> ""
            else -> rawPath.trimEnd('/')
        }
        if (normalizedPath.isNotEmpty() && (!normalizedPath.startsWith('/') || normalizedPath.contains("//"))) {
            return ServerValidation(error = "La ruta base del servidor no es válida.")
        }
        val normalized = runCatching {
            URI(scheme, null, host, uri.port, normalizedPath, null, null).normalize().toASCIIString()
        }.getOrNull() ?: return ServerValidation(error = "La URL no tiene un formato válido.")
        if (URI(normalized).rawPath != normalizedPath) {
            return ServerValidation(error = "La ruta base no puede contener segmentos relativos.")
        }
        return ServerValidation(normalizedUrl = normalized)
    }

    internal fun isLocalDevelopmentHost(host: String): Boolean {
        if (host == "localhost" || host.endsWith(".local")) return true
        if (!IPV4_LITERAL.matches(host)) return false
        val address = runCatching { InetAddress.getByName(host) }.getOrNull() as? Inet4Address ?: return false
        val bytes = address.address.map { it.toInt() and 0xff }
        return bytes[0] == 10 ||
            (bytes[0] == 172 && bytes[1] in 16..31) ||
            (bytes[0] == 192 && bytes[1] == 168) ||
            bytes[0] == 127
    }

    private val IPV4_LITERAL = Regex("^(?:[0-9]{1,3}\\.){3}[0-9]{1,3}$")
}
