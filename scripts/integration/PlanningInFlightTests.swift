import Foundation
import Testing
@testable import HealthTrackerKit

struct PlanningInFlightIntegrationTests {
    @Test func editDuringCreateFlightSurvivesAcknowledgement() async throws {
        let store = try LocalStore.make(inMemory: true)
        let scope = "fictional-qa-scope"
        let id = UUID().uuidString
        try await store.createPlanOffline(scope, id: id, key: "qa-create", name: "Before QA", description: nil)
        // SyncEngine takes a value snapshot before awaiting the network handler.
        let sent = try #require(await store.headOfQueue(scope))
        try await store.markPlanningSyncStatus(scope, action: sent, status: "syncing")
        // The UI remains editable while the original request is awaiting its response.
        try await store.editPlanOffline(scope, publicId: id, name: "After QA", description: nil, key: "qa-edit")
        let changed = try #require(await store.headOfQueue(scope))
        #expect(changed.payloadJSON == sent.payloadJSON, "An in-flight idempotency payload must stay immutable")
        // This is the exact acknowledgement deletion performed by SyncEngine.
        try await store.markPlanningSyncStatus(scope, action: sent, status: "synced")
        try await store.completePending(sent.key)
        let remaining = await store.headOfQueue(scope)
        #expect(remaining != nil, "The later local edit must remain queued after the original create succeeds")
        #expect(await store.plan(scope, publicId: id)?.syncStatus == "pending")
    }
}
