import Foundation

/// Load modes and their input components (android `LoadMode`, backend `MODE_COMPONENTS`).
public enum LoadMode: String, CaseIterable, Sendable {
    case directTotal = "direct_total"
    case perSide = "per_side"
    case barPlusPerSide = "bar_plus_per_side"
    case machineInitialTotal = "machine_initial_total"
    case machineInitialPerSide = "machine_initial_per_side"
    case machineExternalPerSideInitialTotal = "machine_external_per_side_initial_total"
    case selectorStack = "selector_stack"
    case dumbbellEach = "dumbbell_each"
    case bodyweight = "bodyweight"
    case bodyweightPlus = "bodyweight_plus"
    case assistance = "assistance"
    case durationDistance = "duration_distance"

    public var components: [String] {
        switch self {
        case .directTotal: ["direct_total"]
        case .perSide: ["per_side"]
        case .barPlusPerSide: ["bar", "per_side"]
        case .machineInitialTotal: ["initial_total", "added_total"]
        case .machineInitialPerSide: ["initial_per_side", "external_per_side"]
        case .machineExternalPerSideInitialTotal: ["initial_total", "external_per_side"]
        case .selectorStack: ["selector_stack"]
        case .dumbbellEach: ["dumbbell_each"]
        case .bodyweight: ["bodyweight"]
        case .bodyweightPlus: ["bodyweight", "added_total"]
        case .assistance: ["bodyweight", "assistance"]
        case .durationDistance: ["duration_seconds", "distance_meters"]
        }
    }

    public static func fromWire(_ value: String) throws -> LoadMode {
        guard let mode = LoadMode(rawValue: value) else { throw LoadValidationError("Modo de carga desconocido.") }
        return mode
    }

    public static func isMeasure(_ component: String) -> Bool {
        component == "duration_seconds" || component == "distance_meters"
    }
}

public struct LoadValidationError: Error, Sendable, Equatable, LocalizedError {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var errorDescription: String? { message }
}

public struct ComponentInput: Sendable, Equatable {
    public let value: Decimal
    public let unit: String
    public init(_ value: Decimal, _ unit: String) {
        self.value = value
        self.unit = unit
    }
}

public struct LoadPreview: Sendable, Equatable {
    /// Storage weight: total kg rounded half-up to 2 decimals, as text ("180.08").
    public let weightKg: String
    public let totalKg: Decimal
    public let totalLb: Decimal
    /// Load details object exactly as the backend recomputes it (`workout_loads.calculate_workout_load`).
    public let details: JSONValue
}

/// Port of android `LoadCalculator` / backend `calculate_workout_load`. The server compares
/// `load_details` by equality, so arithmetic mirrors Python `decimal` (28 significant digits,
/// half-even) and every decimal is rendered like `decimal_text` (normalized, no exponent).
public enum LoadCalculator {
    public static let lbToKg = Decimal(string: "0.45359237")!
    private static let maxWeight = Decimal(2000)
    private static let precision = 28

    public static func calculate(mode: LoadMode, displayUnit: String, components: [String: ComponentInput]) throws -> LoadPreview {
        guard ["kg", "lb"].contains(displayUnit) else { throw LoadValidationError("Unidad no compatible.") }
        guard Set(components.keys) == Set(mode.components) else {
            throw LoadValidationError("Faltan componentes o existen componentes extra.")
        }
        for (name, input) in components { try validate(name, input) }
        var kg: [String: Decimal] = [:]
        for (name, input) in components {
            kg[name] = LoadMode.isMeasure(name) ? input.value : try toKg(input.value, input.unit)
        }
        func v(_ name: String) -> Decimal { kg[name] ?? 0 }
        var warnings: [String] = []
        let totalKg: Decimal
        switch mode {
        case .directTotal: totalKg = v("direct_total")
        case .perSide: totalKg = context(v("per_side") * 2)
        case .barPlusPerSide: totalKg = context(v("bar") + context(v("per_side") * 2))
        case .machineInitialTotal: totalKg = context(v("initial_total") + v("added_total"))
        case .machineInitialPerSide: totalKg = context(context(v("initial_per_side") + v("external_per_side")) * 2)
        case .machineExternalPerSideInitialTotal: totalKg = context(v("initial_total") + context(v("external_per_side") * 2))
        case .selectorStack: totalKg = v("selector_stack")
        case .dumbbellEach: totalKg = context(v("dumbbell_each") * 2)
        case .bodyweight: totalKg = v("bodyweight")
        case .bodyweightPlus: totalKg = context(v("bodyweight") + v("added_total"))
        case .assistance:
            warnings.append("assistance_is_subtracted_from_bodyweight")
            totalKg = max(context(v("bodyweight") - v("assistance")), 0)
        case .durationDistance:
            warnings.append("duration_distance_has_no_normalized_weight")
            totalKg = 0
        }
        guard totalKg <= maxWeight else { throw LoadValidationError("La carga normalizada supera 2000 kg.") }
        let totalLb = divide(totalKg, lbToKg)
        let componentMembers: [(String, JSONValue)] = mode.components.map { name in
            let input = components[name]!
            return (name, .object([("value", .string(text(input.value))), ("unit", .string(input.unit))]))
        }
        let displayValue = displayUnit == "kg" ? totalKg : totalLb
        var members: [(String, JSONValue)] = [
            ("schema_version", .string(contractVersion)),
            ("load_mode", .string(mode.rawValue)),
            ("original_input", .object([("unit", .string(displayUnit)), ("components", .object(componentMembers))])),
            ("original_unit", .string(displayUnit)),
            ("components", .object(componentMembers)),
            ("normalized_total_kg", .string(text(totalKg))),
            ("calculated_total_lb", .string(text(totalLb))),
            ("display_total", .object([("value", .string(text(displayValue))), ("unit", .string(displayUnit))])),
            ("bodyweight_kg", kg["bodyweight"].map { .string(text($0)) } ?? .null),
            ("assistance", componentMembers.first { $0.0 == "assistance" }?.1 ?? .null),
            ("calculation_version", .string(contractVersion)),
        ]
        if !warnings.isEmpty { members.append(("warnings", .array(warnings.map(JSONValue.string)))) }
        return LoadPreview(weightKg: storageWeight(totalKg), totalKg: totalKg, totalLb: totalLb, details: .object(members))
    }

    /// Parses user or wire text strictly (digits with an optional decimal point).
    public static func parse(_ value: String) -> Decimal? {
        guard value.range(of: #"^(\d+\.?\d*|\.\d+)$"#, options: .regularExpression) != nil else { return nil }
        return Decimal(string: value, locale: Locale(identifier: "en_US_POSIX"))
    }

    /// Python `decimal_text`: normalized plain text, never an exponent, "0" for zero.
    public static func text(_ value: Decimal) -> String {
        var result = NSDecimalNumber(decimal: value).description(withLocale: Locale(identifier: "en_US_POSIX"))
        if result.contains(".") {
            while result.hasSuffix("0") { result.removeLast() }
            if result.hasSuffix(".") { result.removeLast() }
        }
        return result == "-0" || result.isEmpty ? "0" : result
    }

    /// Backend `storage_weight`: quantize to 0.01 half-up, rendered with two decimals.
    public static func storageWeight(_ value: Decimal) -> String {
        var source = value
        var rounded = Decimal()
        NSDecimalRound(&rounded, &source, 2, .plain)
        let plain = text(rounded)
        let parts = plain.split(separator: ".", maxSplits: 1)
        let fraction = parts.count > 1 ? String(parts[1]) : ""
        return "\(parts[0]).\(fraction.padding(toLength: 2, withPad: "0", startingAt: 0))"
    }

    // MARK: Private

    private static func validate(_ name: String, _ input: ComponentInput) throws {
        if input.value < 0 { throw LoadValidationError("\(name) no puede ser negativo.") }
        let expectedUnit: String? = name == "duration_seconds" ? "s" : name == "distance_meters" ? "m" : nil
        if let expectedUnit, input.unit != expectedUnit { throw LoadValidationError("\(name) debe usar \(expectedUnit).") }
        if expectedUnit == nil, !["kg", "lb"].contains(input.unit) { throw LoadValidationError("\(name) debe usar kg o lb.") }
        let maximum: Decimal = name == "duration_seconds" ? 604_800 : name == "distance_meters" ? 10_000_000 : maxWeight
        if input.value > maximum { throw LoadValidationError("\(name) supera el máximo permitido.") }
    }

    private static func toKg(_ value: Decimal, _ unit: String) throws -> Decimal {
        switch unit {
        case "kg": return value
        case "lb": return context(value * lbToKg)
        default: throw LoadValidationError("Unidad no compatible.")
        }
    }

    /// Division rounded to the Python context precision.
    private static func divide(_ lhs: Decimal, _ rhs: Decimal) -> Decimal {
        var a = lhs, b = rhs, result = Decimal()
        NSDecimalDivide(&result, &a, &b, .bankers)
        return context(result)
    }

    /// Rounds to 28 significant digits, half-even (Python default context).
    static func context(_ value: Decimal) -> Decimal {
        guard value != 0 else { return 0 }
        let magnitude = abs(value)
        let digits = NSDecimalNumber(decimal: magnitude).description(withLocale: Locale(identifier: "en_US_POSIX"))
        let adjusted: Int
        if let dot = digits.firstIndex(of: "."), digits.hasPrefix("0") {
            let fraction = digits[digits.index(after: dot)...]
            adjusted = -((fraction.firstIndex { $0 != "0" }.map { fraction.distance(from: fraction.startIndex, to: $0) } ?? 0) + 1)
        } else {
            adjusted = (digits.firstIndex(of: ".").map { digits.distance(from: digits.startIndex, to: $0) } ?? digits.count) - 1
        }
        let scale = precision - 1 - adjusted
        var source = value
        var rounded = Decimal()
        NSDecimalRound(&rounded, &source, scale, .bankers)
        return rounded
    }
}
