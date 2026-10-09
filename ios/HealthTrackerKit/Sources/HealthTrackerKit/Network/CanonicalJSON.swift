import CryptoKit
import Foundation

public enum CanonicalJSON {
    public static func sha256(_ value: JSONValue, excludingTopLevelKey: String? = nil) -> String {
        var source = value
        if let excluded = excludingTopLevelKey, case let .object(members) = value {
            source = .object(members.filter { $0.0 != excluded })
        }
        return hex(SHA256.hash(data: Data(source.sortedKeys().encoded().utf8)))
    }

    /// Local isolation key: one account per server identity and server-side user UUID.
    public static func accountScope(serverURL: String, userPublicId: String) -> String {
        hex(SHA256.hash(data: Data("\(serverURL)\u{0}\(userPublicId)".utf8)))
    }

    public static func serverIdentity(_ serverURL: String) -> String {
        var normalized = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        while normalized.hasSuffix("/") { normalized.removeLast() }
        return hex(SHA256.hash(data: Data(normalized.lowercased().utf8)))
    }

    static func hex<D: Sequence>(_ digest: D) -> String where D.Element == UInt8 {
        digest.map { String(format: "%02x", $0) }.joined()
    }
}
