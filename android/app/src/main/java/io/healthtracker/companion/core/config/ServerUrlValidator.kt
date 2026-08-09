package io.healthtracker.companion.core.config

import io.healthtracker.companion.BuildConfig
import java.net.IDN
import java.net.Inet4Address
import java.net.Inet6Address
import java.net.InetAddress
import java.net.URI

data class ServerValidation(val normalizedUrl: String? = null, val error: String? = null) {
    val valid: Boolean get() = normalizedUrl != null
}

object ServerUrlValidator {
    fun validate(raw: String, explicitLocalHttp: Boolean): ServerValidation {
        if (raw.any { it.isISOControl() }) {
            return ServerValidation(error = "La URL contiene caracteres de control.")
        }
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
        val rawHost = uri.host?.removePrefix("[")?.removeSuffix("]")
        val host = rawHost?.let {
            if (it.contains(':')) it.lowercase()
            else runCatching { IDN.toASCII(it.lowercase(), IDN.USE_STD3_ASCII_RULES) }.getOrNull()
        } ?: return ServerValidation(error = "Falta un hostname válido.")
        if (uri.port == 0 || uri.port !in -1..65535) {
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
        val decodedPath = uri.path.orEmpty()
        if (rawPath.contains(ENCODED_PATH_SEPARATOR) ||
            decodedPath.any { it.isWhitespace() || it.isISOControl() || it == '\\' }
        ) {
            return ServerValidation(error = "La ruta base del servidor no es válida.")
        }
        val normalizedPath = when {
            decodedPath.isBlank() || decodedPath.all { it == '/' } -> ""
            else -> decodedPath.trimEnd('/')
        }
        if (normalizedPath.isNotEmpty() &&
            (!normalizedPath.startsWith('/') || normalizedPath.contains("//") ||
                normalizedPath.split('/').any { it == "." || it == ".." })
        ) {
            return ServerValidation(error = "La ruta base del servidor no es válida.")
        }
        val canonicalPort = when {
            scheme == "https" && uri.port == 443 -> -1
            scheme == "http" && uri.port == 80 -> -1
            else -> uri.port
        }
        val normalized = runCatching {
            URI(scheme, null, host, canonicalPort, normalizedPath, null, null).normalize().toASCIIString()
        }.getOrNull() ?: return ServerValidation(error = "La URL no tiene un formato válido.")
        return ServerValidation(normalizedUrl = normalized)
    }

    internal fun isLocalDevelopmentHost(host: String): Boolean {
        if (host == "localhost" || host.endsWith(".local")) return true
        if (host.contains(':')) {
            if ('%' in host) return false
            val address = runCatching { InetAddress.getByName(host) }.getOrNull() as? Inet6Address ?: return false
            val first = address.address[0].toInt() and 0xff
            return address.isLoopbackAddress || address.isLinkLocalAddress || first in 0xfc..0xfd
        }
        if (!IPV4_LITERAL.matches(host)) return false
        val octets = host.split('.').mapNotNull { it.toIntOrNull() }
        if (octets.size != 4 || octets.any { it !in 0..255 }) return false
        val address = runCatching { InetAddress.getByName(host) }.getOrNull() as? Inet4Address ?: return false
        val bytes = address.address.map { it.toInt() and 0xff }
        return bytes[0] == 10 ||
            (bytes[0] == 172 && bytes[1] in 16..31) ||
            (bytes[0] == 192 && bytes[1] == 168) ||
            bytes[0] == 127
    }

    private val IPV4_LITERAL = Regex("^(?:[0-9]{1,3}\\.){3}[0-9]{1,3}$")
    private val ENCODED_PATH_SEPARATOR = Regex("%(?:2f|5c)", RegexOption.IGNORE_CASE)
}
