import Foundation
import Testing
@testable import HealthTrackerKit

/// Ported from android `LoadCalculatorTest`, plus golden vectors produced by the backend
/// `calculate_workout_load` (the server rejects any `load_details` that differs).
struct LoadCalculatorTests {
    private func kg(_ value: String) -> ComponentInput { ComponentInput(Decimal(string: value)!, "kg") }
    private func lb(_ value: String) -> ComponentInput { ComponentInput(Decimal(string: value)!, "lb") }

    @Test func press397Lb() throws {
        let result = try LoadCalculator.calculate(mode: .machineExternalPerSideInitialTotal, displayUnit: "lb",
                                                  components: ["initial_total": lb("167"), "external_per_side": lb("115")])
        #expect(result.weightKg == "180.08")
        #expect(result.details["display_total"]?["value"] == .string("397"))
    }

    @Test func shoulderPress144Lb() throws {
        let result = try LoadCalculator.calculate(mode: .machineInitialPerSide, displayUnit: "lb",
                                                  components: ["initial_per_side": lb("27"), "external_per_side": lb("45")])
        #expect(result.weightKg == "65.32")
        #expect(result.details["calculated_total_lb"] == .string("144"))
    }

    @Test func tBarRow82Lb() throws {
        let result = try LoadCalculator.calculate(mode: .machineInitialTotal, displayUnit: "lb",
                                                  components: ["initial_total": lb("37"), "added_total": lb("45")])
        #expect(result.weightKg == "37.19")
    }

    @Test func mixedKgAndLbAreConvertedOnce() throws {
        let result = try LoadCalculator.calculate(mode: .barPlusPerSide, displayUnit: "kg", components: ["bar": kg("20"), "per_side": lb("45")])
        #expect(result.weightKg == "60.82")
        #expect(result.details["components"]?["per_side"]?["unit"] == .string("lb"))
    }

    @Test func everyModeHasExpectedFormula() throws {
        for mode in LoadMode.allCases {
            var components: [String: ComponentInput] = [:]
            for name in mode.components {
                components[name] = name == "duration_seconds" ? ComponentInput(600, "s") : name == "distance_meters" ? ComponentInput(2000, "m") : kg("10")
            }
            let result = try LoadCalculator.calculate(mode: mode, displayUnit: "kg", components: components)
            #expect(result.details["calculation_version"] == .string("1.0"))
        }
        let duration = try LoadCalculator.calculate(mode: .durationDistance, displayUnit: "kg",
                                                    components: ["duration_seconds": ComponentInput(600, "s"), "distance_meters": ComponentInput(2000, "m")])
        #expect(duration.weightKg == "0.00")
    }

    @Test func assistanceNeverBecomesNegative() throws {
        let result = try LoadCalculator.calculate(mode: .assistance, displayUnit: "kg", components: ["bodyweight": kg("60"), "assistance": kg("70")])
        #expect(result.weightKg == "0.00")
        #expect(result.details["warnings"] == .array([.string("assistance_is_subtracted_from_bodyweight")]))
    }

    @Test func zeroAndDecimalsAreAccepted() throws {
        #expect(try LoadCalculator.calculate(mode: .directTotal, displayUnit: "kg", components: ["direct_total": kg("0.125")]).weightKg == "0.13")
    }

    @Test func negativesExtraComponentsAndUnknownModesAreRejected() {
        #expect(throws: LoadValidationError.self) { try LoadCalculator.calculate(mode: .directTotal, displayUnit: "kg", components: ["direct_total": kg("-1")]) }
        #expect(throws: LoadValidationError.self) { try LoadCalculator.calculate(mode: .directTotal, displayUnit: "kg", components: ["direct_total": kg("1"), "bar": kg("1")]) }
        #expect(throws: LoadValidationError.self) { try LoadMode.fromWire("invented") }
        #expect(throws: LoadValidationError.self) { try LoadCalculator.calculate(mode: .directTotal, displayUnit: "kg", components: ["direct_total": kg("2000.01")]) }
    }

    @Test func strictParsingAndPythonDecimalText() {
        #expect(LoadCalculator.parse("12.5") == Decimal(string: "12.5"))
        #expect(LoadCalculator.parse(".5") == Decimal(string: "0.5"))
        #expect(LoadCalculator.parse("1e3") == nil)
        #expect(LoadCalculator.parse("-1") == nil)
        #expect(LoadCalculator.parse("") == nil)
        #expect(LoadCalculator.text(Decimal(string: "40.00")!) == "40")
        #expect(LoadCalculator.text(Decimal(string: "100")!) == "100")
        #expect(LoadCalculator.text(0) == "0")
        #expect(LoadCalculator.storageWeight(Decimal(string: "0.125")!) == "0.13")
        #expect(LoadCalculator.storageWeight(100) == "100.00")
    }

    @Test func goldenVectorsMatchTheBackendExactly() throws {
        let url = try #require(Bundle.module.url(forResource: "load_vectors_python", withExtension: "json", subdirectory: "Fixtures"))
        guard case let .array(vectors) = try JSONValue.parse(Data(contentsOf: url)) else { Issue.record("fixture"); return }
        #expect(vectors.count >= 15)
        for vector in vectors {
            let mode = try LoadMode.fromWire(try #require(vector["mode"]?.stringValue))
            let unit = try #require(vector["unit"]?.stringValue)
            guard case let .object(members) = try #require(vector["components"]) else { continue }
            var components: [String: ComponentInput] = [:]
            for (name, component) in members {
                components[name] = ComponentInput(try #require(LoadCalculator.parse(component["value"]?.stringValue ?? "")), component["unit"]?.stringValue ?? "")
            }
            let result = try LoadCalculator.calculate(mode: mode, displayUnit: unit, components: components)
            #expect(result.weightKg == vector["weight_kg"]?.stringValue, "\(mode)")
            let expected = try #require(vector["details"]).sortedKeys()
            #expect(result.details.sortedKeys() == expected, "\(mode) \(unit): \(result.details.encoded())")
        }
    }

    @Test func loadModeCopyNeverExposesWireNames() {
        #expect(DisplayText.loadMode(.barPlusPerSide) == "Barra más carga por lado")
        #expect(DisplayText.component("external_per_side") == "Carga externa por lado")
        #expect(DisplayText.initialLoadMode(existing: nil, durationSeconds: 600, distanceMeters: nil) == .durationDistance)
        #expect(DisplayText.initialLoadMode(existing: nil, durationSeconds: nil, distanceMeters: "5000") == .durationDistance)
        #expect(DisplayText.initialLoadMode(existing: "bodyweight", durationSeconds: nil, distanceMeters: nil) == .bodyweight)
        #expect(DisplayText.autosaveStatus(.saving) == "Guardando…")
        #expect(DisplayText.autosaveStatus(.saved) == "Guardado")
        #expect(DisplayText.autosaveStatus(.savedLocal) == "Guardado en este dispositivo")
    }
}
