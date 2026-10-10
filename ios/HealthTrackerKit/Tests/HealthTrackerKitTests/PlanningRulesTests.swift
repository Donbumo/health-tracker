import Foundation
import Testing
@testable import HealthTrackerKit

/// Ported from android `PlanningRulesTest`.
struct PlanningRulesTests {
    @Test func reorderIsStableAndRejectsBoundaries() {
        #expect(PlanningRules.reorderedIds(["a", "b", "c"], id: "a", delta: 1) == ["b", "a", "c"])
        #expect(PlanningRules.reorderedIds(["a", "b", "c"], id: "a", delta: -1) == nil)
        #expect(PlanningRules.reorderedIds(["a", "b", "c"], id: "missing", delta: 1) == nil)
    }

    @Test func weekUsesLocalMondayThroughSunday() {
        let range = PlanningRules.dateRange(anchor: "2026-07-24", month: false)
        #expect(range?.lowerBound == "2026-07-20")
        #expect(range?.upperBound == "2026-07-26")
        #expect(PlanningRules.dateRange(anchor: "2026-07-26", month: false)?.lowerBound == "2026-07-20")
    }

    @Test func monthUsesActualCalendarBoundaries() {
        let range = PlanningRules.dateRange(anchor: "2028-02-10", month: true)
        #expect(range?.lowerBound == "2028-02-01")
        #expect(range?.upperBound == "2028-02-29")
    }

    @Test func monthGridIncludesBoundariesAndLeapDay() {
        let grid = PlanningRules.monthGrid(anchor: "2028-02-10")
        #expect(grid.first == "2028-01-31")
        #expect(grid.last == "2028-03-05")
        #expect(grid.contains("2028-02-29"))
        #expect(grid.count == 35)
    }

    @Test func monthAndWeekNavigationKeepAValidSelectedDay() {
        #expect(PlanningRules.shiftedAnchor("2026-01-31", month: true, delta: 1) == "2026-02-28")
        #expect(PlanningRules.shiftedAnchor("2026-07-24", month: false, delta: 1) == "2026-07-31")
    }

    @Test func remoteRefreshCannotOverwriteQueuedOrConflictedPlanningState() {
        #expect(protectLocalPlanningState("pending", hasQueuedPlanningWork: true))
        #expect(protectLocalPlanningState("conflict", hasQueuedPlanningWork: true))
        #expect(!protectLocalPlanningState("synced", hasQueuedPlanningWork: true))
        #expect(!protectLocalPlanningState("pending", hasQueuedPlanningWork: false))
    }

    @Test func prescriptionLimitsRejectInvalidLocalAutosave() {
        #expect(PlanningRules.validPrescription(reps: "8", load: "42.5", rir: "2", rpe: "8.5", rest: "90"))
        #expect(!PlanningRules.validPrescription(reps: "0", load: "42.5", rir: "2", rpe: "8", rest: "90"))
        #expect(!PlanningRules.validPrescription(reps: "8", load: "-1", rir: "2", rpe: "8", rest: "90"))
        #expect(PlanningRules.validPrescription(reps: "8", load: "42.5", rir: "20", rpe: "0", rest: "90"))
        #expect(!PlanningRules.validPrescription(reps: "8", load: "42.5", rir: "20.1", rpe: "8", rest: "90"))
        #expect(!PlanningRules.validPrescription(reps: "8", load: "42.5", rir: "2", rpe: "11", rest: "90"))
        #expect(!PlanningRules.validPrescription(reps: "8", load: "42.5", rir: "2", rpe: "8", rest: "86401"))
    }
}
