import CryptoKit
import Foundation

public enum Redaction {
    private static let sensitive = try! NSRegularExpression(
        pattern: #"(?i)(authorization|access[_-]?token|refresh[_-]?token|password|cookie|secret)\s*[:=]\s*[^,\s}]+"#
    )

    public static func sanitize(_ message: String) -> String {
        let range = NSRange(message.startIndex..., in: message)
        let replaced = sensitive.stringByReplacingMatches(in: message, range: range, withTemplate: "$1=[REDACTED]")
        return String(replaced.prefix(500))
    }

    public static func diagnosticCode(_ value: String?) -> String? {
        value.map { String($0.replacingOccurrences(of: "[^a-zA-Z0-9_.-]", with: "_", options: .regularExpression).prefix(64)) }
    }
}

/// Deterministic private file names that never use remote identifiers as path segments.
public enum PrivateFileNames {
    public enum Failure: Error, Equatable { case labelInvalid, extensionInvalid }

    public static func opaque(label: String, remoteIdentifier: String, extension ext: String) throws -> String {
        guard label.range(of: "^[a-z][a-z0-9-]{0,31}$", options: .regularExpression) != nil else { throw Failure.labelInvalid }
        guard ext.range(of: "^[a-z0-9]{1,8}$", options: .regularExpression) != nil else { throw Failure.extensionInvalid }
        let digest = CanonicalJSON.hex(SHA256.hash(data: Data(remoteIdentifier.utf8)))
        return "\(label)-\(digest.prefix(32)).\(ext)"
    }
}
