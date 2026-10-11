import Foundation
@testable import HealthTrackerKit

/// Fictional QA payloads only — no real user, device or health data.
enum QAFixtures {
    static let allCapabilities = #"{"offline_sync_push":true,"incremental_pull":true,"planned_workouts":true,"completed_workouts":true,"companion_delivery":true,"capability_negotiation":true,"progress_checkpoints":true,"workout_package":true,"mobile_planning":true,"exercise_catalog":true}"#

    static func planned(id: String = "qa-planned-1", date: String = "2026-10-09", title: String = "Pierna QA", revision: Int = 1, status: String = "planned") -> String {
        #"{"schema_version":"1.0","id":"\#(id)","training_plan_id":"qa-plan","training_plan_version_id":"qa-plan-v1","scheduled_for_date":"\#(date)","timezone":"UTC","status":"\#(status)","title":"\#(title)","snapshot":{"workout_id":"qa-workout-1"},"source_version":1,"revision":\#(revision),"created_at":"2026-10-01T00:00:00Z","updated_at":"2026-10-01T00:00:00Z","completed_at":null,"cancelled_at":null,"deleted":false}"#
    }

    static func completed(id: String = "qa-completed-1", weight: String = "40.0", reps: Int = 8, loadMode: String? = nil) -> String {
        let load = loadMode.map { #","load_details":{"load_mode":"\#($0)"}"# } ?? ""
        return #"{"schema_version":"1.0","id":"\#(id)","client_event_id":null,"started_at":"2026-10-08T12:00:00Z","completed_at":"2026-10-08T12:30:00Z","timezone":"UTC","duration_seconds":1800,"exercises":[{"exercise_order":1,"planned_exercise_order":1,"name":"Sentadilla QA","sets":[{"set_number":1,"planned_set_number":1,"weight_kg":\#(weight),"reps":\#(reps)\#(load)},{"set_number":2,"planned_set_number":2,"weight_kg":\#(weight),"reps":\#(reps)\#(load)}]}]}"#
    }

    static func delivery(id: String = "qa-delivery-1", status: String = "available", revision: Int = 1) -> String {
        #"{"schema_version":"1.0","id":"\#(id)","device_id":"qa-device","profile_id":"qa-profile","planned_workout_id":"qa-planned-1","package_schema_version":"1.0","package_hash":"abc","status":"\#(status)","revision":\#(revision),"last_client_sequence":0,"created_at":"2026-10-01T00:00:00Z","updated_at":"2026-10-01T00:00:00Z"}"#
    }

    static func profile(deviceId: String = "qa-device", revision: Int = 2) -> String {
        #"{"schema_version":"1.0","id":"qa-profile","device_id":"\#(deviceId)","protocol_version":"1.0","workout_schema_version":"1.0","result_schema_version":"1.0","supported_features":["offline"],"supported_metrics":["reps"],"limits":{"max_payload_bytes":262144,"max_progress_events_per_workout":500},"revision":\#(revision),"last_negotiated_at":"2026-10-01T00:00:00Z","revoked":false}"#
    }

    static func bootstrap(deviceId: String = "qa-device", cursor: String = "qa-cursor-0", capabilities: String = allCapabilities, planned: [String]? = nil) -> String {
        let plannedJSON = (planned ?? [Self.planned()]).joined(separator: ",")
        return #"{"data":{"schema_version":"1.0","server_time":"2026-10-09T12:00:00Z","cursor":"\#(cursor)","active_routine":null,"planned_workouts":[\#(plannedJSON)],"completed_workouts":[\#(completed())],"capabilities":\#(capabilities),"limits":{"push_operations":50,"pull_limit":200,"json_bytes":1048576},"schemas":{"planned_workout":"1.0","completed_workout":"1.0","sync":"1.0"},"device":{"device_id":"\#(deviceId)","session_id":"qa-session"},"companion":{"profile":null,"deliveries":[\#(delivery())],"versions":{"protocol":"1.0","workout_package":"1.0","result":"1.0"}}}}"#
    }

    static func negotiation(deviceId: String = "qa-device", features: String = #"["offline","rest_timer","rpe","rir","weight"]"#) -> String {
        #"{"data":{"selected_protocol_version":"1.0","selected_workout_schema_version":"1.0","selected_result_schema_version":"1.0","accepted_features":\#(features),"rejected_features":[],"accepted_metrics":["reps","weight_kg","rest_seconds","rpe","rir"],"rejected_metrics":[],"effective_limits":{"max_payload_bytes":262144,"max_progress_events_per_workout":500},"server_capabilities":{},"profile":\#(profile(deviceId: deviceId))}}"#
    }

    static func change(_ type: String, id: String, operation: String = "upsert", revision: Int = 1, payload: String?) -> String {
        #"{"entity_type":"\#(type)","entity_id":"\#(id)","operation":"\#(operation)","revision":\#(revision),"changed_at":"2026-10-09T12:00:00Z","payload_hash":"x","payload":\#(payload ?? "null")}"#
    }

    static func pull(_ changes: [String], next: String, hasMore: Bool = false) -> String {
        #"{"data":{"schema_version":"1.0","changes":[\#(changes.joined(separator: ","))],"next_cursor":"\#(next)","has_more":\#(hasMore),"server_time":"2026-10-09T12:00:00Z"}}"#
    }

    static func status(deviceId: String = "qa-device", schema: String = "1.0") -> String {
        #"{"data":{"schema_version":"\#(schema)","device_id":"\#(deviceId)","cursor":"c","last_pull_at_sequence":1,"server_sequence":1,"server_time":"2026-10-09T12:00:00Z"}}"#
    }

    static func decode<T: Decodable & Sendable>(_ type: T.Type, envelope json: String) throws -> T {
        try JSONDecoder().decode(APIEnvelope<T>.self, from: Data(json.utf8)).data
    }

    static func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try JSONDecoder().decode(T.self, from: Data(json.utf8))
    }
}
