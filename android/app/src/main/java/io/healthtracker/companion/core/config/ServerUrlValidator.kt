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
        val candidate = raw.trim().trimEnd('/')
        val uri = runCatching { URI(candidate) }.getOrNull()
            ?: return ServerValidation(error = "La URL no tiene un formato válido.")
        val scheme = uri.scheme?.lowercase()
        if (scheme !in setOf("https", "http")) {
            return ServerValidation(error = "Solo se permiten URLs HTTPS o HTTP local explícito.")
        }
        if (uri.userInfo != null || uri.query != null || uri.fragment != null) {
            return ServerValidation(error = "La URL no puede contener credenciales, consulta ni fragmento.")
        }
        if (uri.path !in setOf("", "/")) {
            return ServerValidation(error = "Configura la raíz del servidor, sin una ruta adicional.")
        }
        val host = uri.host?.let { runCatching { IDN.toASCII(it.lowercase()) }.getOrNull() }
            ?: return ServerValidation(error = "Falta un hostname válido.")
        if (scheme == "http") {
            if (!BuildConfig.ALLOW_LOCAL_HTTP || !explicitLocalHttp) {
                return ServerValidation(error = "HTTP solo está disponible en debug y requiere confirmación explícita.")
            }
            if (!isLocalDevelopmentHost(host)) {
                return ServerValidation(error = "HTTP se limita a loopback, emulador, RFC1918 o nombres .local.")
            }
        }
        val port = if (uri.port == -1) "" else ":${uri.port}"
        return ServerValidation(normalizedUrl = "$scheme://$host$port")
    }

    internal fun isLocalDevelopmentHost(host: String): Boolean {
        if (host == "localhost" || host == "10.0.2.2" || host.endsWith(".local")) return true
        val address = runCatching { InetAddress.getByName(host) }.getOrNull() as? Inet4Address ?: return false
        val bytes = address.address.map { it.toInt() and 0xff }
        return bytes[0] == 10 ||
            (bytes[0] == 172 && bytes[1] in 16..31) ||
            (bytes[0] == 192 && bytes[1] == 168) ||
            bytes[0] == 127
    }
}
