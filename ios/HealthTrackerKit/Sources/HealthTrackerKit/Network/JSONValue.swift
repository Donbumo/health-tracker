import Foundation

/// Lossless JSON tree. Numbers keep their literal text so canonical hashes match the
/// server and the Android client byte for byte (`1.0` must not become `1`).
public enum JSONValue: Sendable, Equatable {
    case null
    case bool(Bool)
    case number(String)
    case string(String)
    case array([JSONValue])
    case object([(String, JSONValue)])

    public static func == (lhs: JSONValue, rhs: JSONValue) -> Bool {
        switch (lhs, rhs) {
        case (.null, .null): return true
        case let (.bool(a), .bool(b)): return a == b
        case let (.number(a), .number(b)): return a == b
        case let (.string(a), .string(b)): return a == b
        case let (.array(a), .array(b)): return a == b
        case let (.object(a), .object(b)):
            return a.count == b.count && zip(a, b).allSatisfy { $0.0 == $1.0 && $0.1 == $1.1 }
        default: return false
        }
    }

    public subscript(key: String) -> JSONValue? {
        guard case let .object(members) = self else { return nil }
        return members.last { $0.0 == key }?.1
    }

    public var stringValue: String? {
        if case let .string(value) = self { return value }
        return nil
    }

    // MARK: Parsing

    public static func parse(_ data: Data) throws -> JSONValue {
        var parser = Parser(bytes: Array(data))
        parser.skipWhitespace()
        let value = try parser.parseValue(depth: 0)
        parser.skipWhitespace()
        guard parser.index == parser.bytes.count else { throw Parser.Failure.trailingContent }
        return value
    }

    public static func parse(_ text: String) throws -> JSONValue {
        try parse(Data(text.utf8))
    }

    // MARK: Encoding (kotlinx.serialization compatible, compact)

    public func encoded() -> String {
        var output = ""
        write(into: &output)
        return output
    }

    private func write(into output: inout String) {
        switch self {
        case .null: output += "null"
        case let .bool(value): output += value ? "true" : "false"
        case let .number(literal): output += literal
        case let .string(value): Self.writeQuoted(value, into: &output)
        case let .array(items):
            output += "["
            for (index, item) in items.enumerated() {
                if index > 0 { output += "," }
                item.write(into: &output)
            }
            output += "]"
        case let .object(members):
            output += "{"
            for (index, member) in members.enumerated() {
                if index > 0 { output += "," }
                Self.writeQuoted(member.0, into: &output)
                output += ":"
                member.1.write(into: &output)
            }
            output += "}"
        }
    }

    private static func writeQuoted(_ value: String, into output: inout String) {
        output += "\""
        for scalar in value.unicodeScalars {
            switch scalar {
            case "\"": output += "\\\""
            case "\\": output += "\\\\"
            case "\n": output += "\\n"
            case "\r": output += "\\r"
            case "\t": output += "\\t"
            case "\u{08}": output += "\\b"
            case "\u{0C}": output += "\\f"
            default:
                if scalar.value < 0x20 {
                    output += String(format: "\\u%04x", scalar.value)
                } else {
                    output.unicodeScalars.append(scalar)
                }
            }
        }
        output += "\""
    }

    /// Recursively orders object keys by UTF-16 code units, matching Kotlin `sortedBy { it.key }`.
    public func sortedKeys() -> JSONValue {
        switch self {
        case let .object(members):
            let sorted = members
                .map { ($0.0, $0.1.sortedKeys()) }
                .sorted { Array($0.0.utf16).lexicographicallyPrecedes(Array($1.0.utf16)) }
            return .object(sorted)
        case let .array(items):
            return .array(items.map { $0.sortedKeys() })
        default:
            return self
        }
    }
}

extension JSONValue: Decodable {
    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null; return }
        if let value = try? container.decode(Bool.self) { self = .bool(value); return }
        if let value = try? container.decode(String.self) { self = .string(value); return }
        if let value = try? container.decode(Decimal.self) { self = .number("\(value)"); return }
        if let value = try? container.decode([JSONValue].self) { self = .array(value); return }
        if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value.sorted { $0.key < $1.key }.map { ($0.key, $0.value) })
            return
        }
        throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unsupported JSON value")
    }
}

private struct Parser {
    enum Failure: Error { case unexpectedEnd, unexpectedByte(UInt8), invalidNumber, invalidEscape, trailingContent, tooDeep }

    let bytes: [UInt8]
    var index = 0
    private static let maxDepth = 256

    init(bytes: [UInt8]) { self.bytes = bytes }

    mutating func skipWhitespace() {
        while index < bytes.count, [0x20, 0x0A, 0x0D, 0x09].contains(bytes[index]) { index += 1 }
    }

    mutating func parseValue(depth: Int) throws -> JSONValue {
        guard depth < Self.maxDepth else { throw Failure.tooDeep }
        guard index < bytes.count else { throw Failure.unexpectedEnd }
        switch bytes[index] {
        case UInt8(ascii: "{"): return try parseObject(depth: depth)
        case UInt8(ascii: "["): return try parseArray(depth: depth)
        case UInt8(ascii: "\""): return .string(try parseString())
        case UInt8(ascii: "t"): try expect("true"); return .bool(true)
        case UInt8(ascii: "f"): try expect("false"); return .bool(false)
        case UInt8(ascii: "n"): try expect("null"); return .null
        default: return .number(try parseNumber())
        }
    }

    private mutating func expect(_ literal: String) throws {
        for byte in literal.utf8 {
            guard index < bytes.count else { throw Failure.unexpectedEnd }
            guard bytes[index] == byte else { throw Failure.unexpectedByte(bytes[index]) }
            index += 1
        }
    }

    private mutating func parseObject(depth: Int) throws -> JSONValue {
        index += 1
        var members: [(String, JSONValue)] = []
        skipWhitespace()
        if index < bytes.count, bytes[index] == UInt8(ascii: "}") { index += 1; return .object(members) }
        while true {
            skipWhitespace()
            guard index < bytes.count else { throw Failure.unexpectedEnd }
            guard bytes[index] == UInt8(ascii: "\"") else { throw Failure.unexpectedByte(bytes[index]) }
            let key = try parseString()
            skipWhitespace()
            try expect(":")
            skipWhitespace()
            members.append((key, try parseValue(depth: depth + 1)))
            skipWhitespace()
            guard index < bytes.count else { throw Failure.unexpectedEnd }
            if bytes[index] == UInt8(ascii: ",") { index += 1; continue }
            if bytes[index] == UInt8(ascii: "}") { index += 1; return .object(members) }
            throw Failure.unexpectedByte(bytes[index])
        }
    }

    private mutating func parseArray(depth: Int) throws -> JSONValue {
        index += 1
        var items: [JSONValue] = []
        skipWhitespace()
        if index < bytes.count, bytes[index] == UInt8(ascii: "]") { index += 1; return .array(items) }
        while true {
            skipWhitespace()
            items.append(try parseValue(depth: depth + 1))
            skipWhitespace()
            guard index < bytes.count else { throw Failure.unexpectedEnd }
            if bytes[index] == UInt8(ascii: ",") { index += 1; continue }
            if bytes[index] == UInt8(ascii: "]") { index += 1; return .array(items) }
            throw Failure.unexpectedByte(bytes[index])
        }
    }

    private mutating func parseString() throws -> String {
        index += 1
        var scalars = String.UnicodeScalarView()
        var raw: [UInt8] = []
        func flush() throws {
            guard !raw.isEmpty else { return }
            guard let text = String(bytes: raw, encoding: .utf8) else { throw Failure.invalidEscape }
            scalars.append(contentsOf: text.unicodeScalars)
            raw.removeAll(keepingCapacity: true)
        }
        while true {
            guard index < bytes.count else { throw Failure.unexpectedEnd }
            let byte = bytes[index]
            index += 1
            switch byte {
            case UInt8(ascii: "\""):
                try flush()
                return String(scalars)
            case UInt8(ascii: "\\"):
                try flush()
                guard index < bytes.count else { throw Failure.unexpectedEnd }
                let escape = bytes[index]
                index += 1
                switch escape {
                case UInt8(ascii: "\""): scalars.append("\"")
                case UInt8(ascii: "\\"): scalars.append("\\")
                case UInt8(ascii: "/"): scalars.append("/")
                case UInt8(ascii: "b"): scalars.append("\u{08}")
                case UInt8(ascii: "f"): scalars.append("\u{0C}")
                case UInt8(ascii: "n"): scalars.append("\n")
                case UInt8(ascii: "r"): scalars.append("\r")
                case UInt8(ascii: "t"): scalars.append("\t")
                case UInt8(ascii: "u"):
                    var code = try parseHex4()
                    if (0xD800...0xDBFF).contains(code) {
                        try expect("\\u")
                        let low = try parseHex4()
                        guard (0xDC00...0xDFFF).contains(low) else { throw Failure.invalidEscape }
                        code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
                    }
                    guard let scalar = Unicode.Scalar(code) else { throw Failure.invalidEscape }
                    scalars.append(scalar)
                default: throw Failure.invalidEscape
                }
            default:
                guard byte >= 0x20 else { throw Failure.unexpectedByte(byte) }
                raw.append(byte)
            }
        }
    }

    private mutating func parseHex4() throws -> UInt32 {
        guard index + 4 <= bytes.count else { throw Failure.unexpectedEnd }
        guard let text = String(bytes: bytes[index..<index + 4], encoding: .ascii),
              let value = UInt32(text, radix: 16) else { throw Failure.invalidEscape }
        index += 4
        return value
    }

    private mutating func parseNumber() throws -> String {
        let start = index
        if index < bytes.count, bytes[index] == UInt8(ascii: "-") { index += 1 }
        let digitsStart = index
        while index < bytes.count, (0x30...0x39).contains(bytes[index]) { index += 1 }
        guard index > digitsStart else { throw Failure.invalidNumber }
        if bytes[digitsStart] == 0x30, index - digitsStart > 1 { throw Failure.invalidNumber }
        if index < bytes.count, bytes[index] == UInt8(ascii: ".") {
            index += 1
            let fractionStart = index
            while index < bytes.count, (0x30...0x39).contains(bytes[index]) { index += 1 }
            guard index > fractionStart else { throw Failure.invalidNumber }
        }
        if index < bytes.count, bytes[index] == UInt8(ascii: "e") || bytes[index] == UInt8(ascii: "E") {
            index += 1
            if index < bytes.count, bytes[index] == UInt8(ascii: "+") || bytes[index] == UInt8(ascii: "-") { index += 1 }
            let exponentStart = index
            while index < bytes.count, (0x30...0x39).contains(bytes[index]) { index += 1 }
            guard index > exponentStart else { throw Failure.invalidNumber }
        }
        return String(decoding: bytes[start..<index], as: UTF8.self)
    }
}
