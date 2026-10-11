import Foundation
#if canImport(Darwin)
import Darwin
#endif

public struct ServerValidation: Sendable, Equatable {
    public let normalizedURL: String?
    public let error: String?

    public var valid: Bool { normalizedURL != nil }

    static func failure(_ message: String) -> ServerValidation { ServerValidation(normalizedURL: nil, error: message) }
}

/// Mirrors the Android `ServerUrlValidator`: HTTPS by default, explicit local HTTP only in debug
/// builds, no credentials/query/fragment, and one canonical form per server identity.
public enum ServerURLValidator {
    #if DEBUG
    public static let buildAllowsLocalHTTP = true
    #else
    public static let buildAllowsLocalHTTP = false
    #endif

    public static func validate(_ raw: String, explicitLocalHTTP: Bool, buildAllowsLocalHTTP: Bool = buildAllowsLocalHTTP) -> ServerValidation {
        if raw.unicodeScalars.contains(where: isISOControl) {
            return .failure("La URL contiene caracteres de control.")
        }
        let candidate = raw.trimmingCharacters(in: .whitespaces)
        guard let parts = URIParts(candidate) else {
            return .failure("La URL no tiene un formato válido.")
        }
        let scheme = parts.scheme.lowercased()
        guard scheme == "https" || scheme == "http" else {
            return .failure("Solo se permiten URLs HTTPS o HTTP local explícito.")
        }
        if parts.hasUserInfo || parts.query != nil || parts.fragment != nil {
            return .failure("La URL no puede contener credenciales, consulta ni fragmento.")
        }
        guard let rawHost = parts.host, let host = canonicalHost(rawHost) else {
            return .failure("Falta un hostname válido.")
        }
        if parts.port == 0 || parts.port > 65535 {
            return .failure("El puerto del servidor no es válido.")
        }
        if scheme == "http" {
            if !buildAllowsLocalHTTP || !explicitLocalHTTP {
                return .failure("HTTP solo está disponible en debug y requiere confirmación explícita.")
            }
            if !isLocalDevelopmentHost(host) {
                return .failure("HTTP se limita a loopback, emulador, RFC1918 o nombres .local.")
            }
        }
        let rawPath = parts.path
        guard let decodedPath = rawPath.removingPercentEncoding else {
            return .failure("La URL no tiene un formato válido.")
        }
        let lowerRaw = rawPath.lowercased()
        if lowerRaw.contains("%2f") || lowerRaw.contains("%5c") ||
            decodedPath.unicodeScalars.contains(where: { CharacterSet.whitespacesAndNewlines.contains($0) || isISOControl($0) || $0 == "\\" }) {
            return .failure("La ruta base del servidor no es válida.")
        }
        var normalizedPath: String
        if decodedPath.isEmpty || decodedPath.allSatisfy({ $0 == "/" }) {
            normalizedPath = ""
        } else {
            normalizedPath = decodedPath
            while normalizedPath.hasSuffix("/") { normalizedPath.removeLast() }
        }
        if !normalizedPath.isEmpty,
           !normalizedPath.hasPrefix("/") || normalizedPath.contains("//") ||
           normalizedPath.split(separator: "/", omittingEmptySubsequences: false).contains(where: { $0 == "." || $0 == ".." }) {
            return .failure("La ruta base del servidor no es válida.")
        }
        let canonicalPort: Int
        switch (scheme, parts.port) {
        case ("https", 443), ("http", 80): canonicalPort = -1
        default: canonicalPort = parts.port
        }
        guard let encodedPath = normalizedPath.addingPercentEncoding(withAllowedCharacters: pathAllowed) else {
            return .failure("La URL no tiene un formato válido.")
        }
        let hostPart = host.contains(":") ? "[\(host)]" : host
        let portPart = canonicalPort == -1 ? "" : ":\(canonicalPort)"
        return ServerValidation(normalizedURL: "\(scheme)://\(hostPart)\(portPart)\(encodedPath)", error: nil)
    }

    public static func isLocalDevelopmentHost(_ host: String) -> Bool {
        if host == "localhost" || host.hasSuffix(".local") { return true }
        if host.contains(":") {
            if host.contains("%") { return false }
            guard let bytes = ipv6Bytes(host) else { return false }
            let loopback = bytes == [UInt8](repeating: 0, count: 15) + [1]
            let linkLocal = bytes[0] == 0xFE && (bytes[1] & 0xC0) == 0x80
            return loopback || linkLocal || (0xFC...0xFD).contains(bytes[0])
        }
        guard host.range(of: #"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$"#, options: .regularExpression) != nil else { return false }
        let octets = host.split(separator: ".").compactMap { Int($0) }
        guard octets.count == 4, octets.allSatisfy({ (0...255).contains($0) }) else { return false }
        return octets[0] == 10 ||
            (octets[0] == 172 && (16...31).contains(octets[1])) ||
            (octets[0] == 192 && octets[1] == 168) ||
            octets[0] == 127
    }

    // MARK: Helpers

    private static let pathAllowed: CharacterSet = {
        var set = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")
        set.insert(charactersIn: "!$&'()*+,;=:@/")
        return set
    }()

    static func isISOControl(_ scalar: Unicode.Scalar) -> Bool {
        scalar.value <= 0x1F || (0x7F...0x9F).contains(scalar.value)
    }

    private static func canonicalHost(_ raw: String) -> String? {
        if raw.hasPrefix("[") {
            guard raw.hasSuffix("]") else { return nil }
            let literal = String(raw.dropFirst().dropLast()).lowercased()
            guard !literal.contains("%"), ipv6Bytes(literal) != nil else { return nil }
            return literal
        }
        let lower = raw.lowercased()
        let label = "[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
        guard !lower.isEmpty, lower.count <= 253,
              lower.range(of: "^\(label)(?:\\.\(label))*$", options: .regularExpression) != nil else { return nil }
        return lower
    }

    private static func ipv6Bytes(_ text: String) -> [UInt8]? {
        var address = in6_addr()
        guard inet_pton(AF_INET6, text, &address) == 1 else { return nil }
        return withUnsafeBytes(of: &address) { Array($0) }
    }
}

/// Minimal RFC 3986 split that rejects what `java.net.URI` would reject for server URLs.
private struct URIParts {
    let scheme: String
    let hasUserInfo: Bool
    let host: String?
    let port: Int
    let path: String
    let query: String?
    let fragment: String?

    init?(_ text: String) {
        guard let colon = text.firstIndex(of: ":") else { return nil }
        let scheme = String(text[..<colon])
        guard scheme.range(of: "^[A-Za-z][A-Za-z0-9+.-]*$", options: .regularExpression) != nil else { return nil }
        self.scheme = scheme
        var rest = Substring(text[text.index(after: colon)...])

        if let hash = rest.firstIndex(of: "#") {
            fragment = String(rest[rest.index(after: hash)...])
            rest = rest[..<hash]
        } else { fragment = nil }
        if let mark = rest.firstIndex(of: "?") {
            query = String(rest[rest.index(after: mark)...])
            rest = rest[..<mark]
        } else { query = nil }

        guard rest.hasPrefix("//") else {
            // Opaque URIs (javascript:, mailto:) have no host.
            hasUserInfo = false; host = nil; port = -1; path = String(rest)
            return
        }
        rest = rest.dropFirst(2)
        let authorityEnd = rest.firstIndex(of: "/") ?? rest.endIndex
        var authority = rest[..<authorityEnd]
        let path = String(rest[authorityEnd...])
        guard path.unicodeScalars.allSatisfy(URIParts.isPathScalar), URIParts.validPercentEncoding(path) else { return nil }
        self.path = path

        if let at = authority.lastIndex(of: "@") {
            hasUserInfo = true
            authority = authority[authority.index(after: at)...]
        } else { hasUserInfo = false }

        var hostText = authority
        var port = -1
        if authority.hasPrefix("[") {
            guard let close = authority.firstIndex(of: "]") else { return nil }
            hostText = authority[...close]
            let after = authority[authority.index(after: close)...]
            if !after.isEmpty {
                guard after.hasPrefix(":") else { return nil }
                let digits = after.dropFirst()
                if !digits.isEmpty {
                    guard digits.allSatisfy(\.isASCIIDigit), let value = Int(digits.prefix(6)) else { self.host = nil; self.port = -1; return }
                    port = value
                }
            }
        } else if let portColon = authority.lastIndex(of: ":") {
            hostText = authority[..<portColon]
            let digits = authority[authority.index(after: portColon)...]
            if !digits.isEmpty {
                guard digits.allSatisfy(\.isASCIIDigit), let value = Int(digits.prefix(6)) else { self.host = nil; self.port = -1; return }
                port = value
            }
        }
        self.port = port
        self.host = hostText.isEmpty ? nil : String(hostText)
    }

    private static func isPathScalar(_ scalar: Unicode.Scalar) -> Bool {
        guard scalar.isASCII else { return false }
        let char = Character(scalar)
        return char.isLetter || char.isNumber || "-._~!$&'()*+,;=:@/%".contains(char)
    }

    private static func validPercentEncoding(_ text: String) -> Bool {
        let bytes = Array(text.utf8)
        var index = 0
        while index < bytes.count {
            if bytes[index] == UInt8(ascii: "%") {
                guard index + 2 < bytes.count,
                      bytes[index + 1].isHexDigit, bytes[index + 2].isHexDigit else { return false }
                index += 3
            } else { index += 1 }
        }
        return true
    }
}

private extension Character {
    var isASCIIDigit: Bool { isASCII && isNumber }
}

private extension UInt8 {
    var isHexDigit: Bool {
        (0x30...0x39).contains(self) || (0x41...0x46).contains(self) || (0x61...0x66).contains(self)
    }
}
