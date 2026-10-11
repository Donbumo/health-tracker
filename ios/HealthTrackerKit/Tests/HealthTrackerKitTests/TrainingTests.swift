import Foundation
import Testing
@testable import HealthTrackerKit

/// Fictional QA training payloads (no real user data).
enum TrainingFixtures {
    static func historyItem(id: String = "11111111-1111-4111-8111-111111111111", name: String = "Sesión QA", volume: String = "null") -> String {
        #"{"public_id":"\#(id)","performed_at":"2026-07-23T12:00:00Z","completed_at":"2026-07-23T12:00:00Z","name":"\#(name)","duration_seconds":1800,"exercise_count":1,"set_count":2,"volume_kg":\#(volume),"volume_partial":true,"source":"device_sync","sync_status":"synced"}"#
    }

    static func historyPage(_ items: [String], next: String? = "cursor-qa", hasMore: Bool = true, schema: String = "1.0") -> String {
        #"{"data":{"schema_version":"\#(schema)","items":[\#(items.joined(separator: ","))],"next_cursor":\#(next.map { "\"\($0)\"" } ?? "null"),"has_more":\#(hasMore)}}"#
    }

    static func historyDetail(id: String = "11111111-1111-4111-8111-111111111111") -> String {
        #"{"data":{"schema_version":"1.0","public_id":"\#(id)","performed_at":"2026-07-23T12:00:00Z","started_at":"2026-07-23T11:30:00Z","completed_at":"2026-07-23T12:00:00Z","timezone":"UTC","name":"Sesión QA","duration_seconds":1800,"exercise_count":1,"set_count":2,"volume_kg":"640.00","volume_partial":false,"source":"device_sync","sync_status":"synced","notes":"Nota QA","planned_workout_id":null,"training_plan_id":null,"training_plan_version_id":null,"exercises":[{"exercise_public_id":"22222222-2222-4222-8222-222222222222","exercise_order":1,"name":"Remo QA","notes":null,"sets":[{"set_number":1,"weight_kg":"40.00","display_load":{"value":"40","unit":"kg"},"load_mode":"direct_total","reps":8,"rir":"2.0","rpe":null,"rest_seconds":90,"duration_seconds":null,"distance_meters":null,"notes":null},{"set_number":2,"weight_kg":"40.00","display_load":null,"load_mode":"direct_total","reps":8,"rir":null,"rpe":"8.0","rest_seconds":null,"duration_seconds":null,"distance_meters":null,"notes":null}]}]}}"#
    }

    static func summary(range: String = "7") -> String {
        #"{"data":{"schema_version":"1.0","range":"\#(range)","generated_at":"2026-07-24T00:00:00Z","metrics":{"sessions":1,"training_days":1,"distinct_exercises":1,"completed_sets":2,"total_reps":10,"volume_kg":"500.00","volume_partial":false,"duration_seconds":1800},"comparison":{"sessions":{"change":"1.00","percent":null,"previous":"0.00"}},"comparable_load_modes":["direct_total"]}}"#
    }

    static let exercise = #"{"public_id":"22222222-2222-4222-8222-222222222222","name":"Remo QA","last_performed_at":"2026-07-23T00:00:00Z","session_count":1,"set_count":1,"best_load_kg":"40.00","best_repetition_set":{"reps":8,"weight_kg":"40.00"},"volume_kg":"320.00","volume_partial":false,"load_comparable":true,"load_modes":["direct_total"],"trend":"insufficient_data"}"#

    static func exercises(range: String = "7", items: [String] = [exercise]) -> String {
        #"{"data":{"schema_version":"1.0","range":"\#(range)","items":[\#(items.joined(separator: ","))]}}"#
    }

    static func exerciseDetail(range: String = "30") -> String {
        #"{"data":{"schema_version":"1.0","range":"\#(range)","exercise":\#(exercise),"points":[{"date":"2026-07-23","performed_at":"2026-07-23T00:00:00Z","session_public_id":"33333333-3333-4333-8333-333333333333","best_load_kg":"40.00","best_reps":8,"volume_kg":"320.00","set_count":1,"average_rir":"2.00","average_rpe":"8.00","load_comparable":true}],"personal_records":[{"type":"highest_load","value":"40.00","unit":"kg","date":"2026-07-23","session_public_id":"33333333-3333-4333-8333-333333333333","set_index":1}],"recent_sessions":[]}}"#
    }

    static func plan(id: String = "qa-plan-1", name: String = "Rutina QA", status: String = "active", revision: Int = 1, withWorkouts: Bool = true) -> String {
        let workouts = withWorkouts ? #","workouts":[{"public_id":"qa-workout-1","name":"Pierna QA","notes":null,"position":1,"exercises":[{"id":"qa-row-1","exercise_id":"qa-ex-1","exercise_order":1,"name":"Sentadilla QA","notes":null,"sets":[{"id":"qa-set-1","set_number":1,"reps":null,"reps_min":8,"reps_max":10,"weight_kg":"60.00","load_value":"60","load_unit":"kg","load_mode":"direct_total","load_details":null,"rir":"2","rpe":null,"rest_seconds":120,"duration_seconds":null,"distance_m":null,"notes":null}]}],"estimated_duration_seconds":2700,"revision":1,"created_at":"2026-07-01T00:00:00Z","updated_at":"2026-07-01T00:00:00Z"}]"# : ""
        return #"{"public_id":"\#(id)","name":"\#(name)","description":"Plan ficticio","status":"\#(status)","revision":\#(revision),"active_version_id":"qa-v1","active_version":1,"workout_count":1\#(workouts),"created_at":"2026-07-01T00:00:00Z","updated_at":"2026-07-01T00:00:00Z","archived_at":null}"#
    }
}

struct TrainingContractTests {
    @Test func historyPageMapsNullableVolumeAndCursor() throws {
        let page = try QAFixtures.decode(MobileHistoryPageDTO.self, envelope: TrainingFixtures.historyPage([TrainingFixtures.historyItem()]))
        #expect(page.nextCursor == "cursor-qa")
        #expect(page.items.count == 1 && page.items[0].volumeKg == nil)
    }

    @Test func summaryDoesNotInventPercentageWhenPreviousIsZero() throws {
        let summary = try QAFixtures.decode(ProgressSummaryDTO.self, envelope: TrainingFixtures.summary())
        #expect(summary.comparison?["sessions"]?.percent == nil)
    }

    @Test func exerciseDetailMapsTextFallbackDataAndRecords() throws {
        let detail = try QAFixtures.decode(ProgressExerciseDetailDTO.self, envelope: TrainingFixtures.exerciseDetail())
        #expect(detail.points.count == 1)
        #expect(!detail.personalRecords.isEmpty)
        #expect(detail.exercise.bestRepetitionSet == ProgressBestSetDTO(reps: 8, weightKg: "40.00"))
    }

    @Test func planDetailDecodesWorkoutsExercisesAndSetDefaults() throws {
        let plan = try QAFixtures.decode(MobilePlanDTO.self, TrainingFixtures.plan())
        let set = try #require(plan.workouts?.first?.exercises.first?.sets.first)
        #expect(set.repsMin == 8 && set.repsMax == 10)
        #expect(set.loadDetails == nil)
        let minimal = try QAFixtures.decode(MobilePlanSetDTO.self, #"{"id":"s","set_number":1}"#)
        #expect(minimal.loadUnit == "kg" && minimal.loadMode == "direct_total")
    }

    @Test func historyFilterCacheKeyMatchesAndroid() {
        #expect(HistoryFilters().cacheKey == "history:::")
        #expect(HistoryFilters(dateFrom: "2026-07-01", exercisePublicId: "e").cacheKey == "history:2026-07-01::e")
    }
}

/// Ported from android `UiFormattersTest` (load-mode copy arrives with the workout session stage).
struct DisplayTextTests {
    @Test func chartScaleHandlesEmptySingleEqualAndMultipleValues() {
        #expect(DisplayText.chartScale([]) == nil)
        #expect(DisplayText.chartScale([5])?.span == 1)
        #expect(DisplayText.chartScale([5, 5])?.span == 1)
        #expect(DisplayText.chartScale([3, 10])?.span == 7)
        #expect(DisplayText.chartScale([.nan, 2])?.minimum == 2)
    }

    @Test func internalStatusesBecomeHumanText() {
        #expect(DisplayText.draftStatus("pending_sync") == "Guardado; sincronización pendiente")
        #expect(DisplayText.syncStatus("conflict") == "Requiere intervención")
        #expect(DisplayText.workoutStatus("unexpected_internal_code") == "Estado no disponible")
        #expect(DisplayText.planningSync("pending") == "guardado local, pendiente")
        #expect(DisplayText.planningSync("syncing") == "sincronizando")
        #expect(DisplayText.planningSync("conflict") == "requiere atención")
    }

    @Test func planningAndConflictEnumsAreNeverShownRaw() {
        #expect(DisplayText.planningConflict("remote_deleted").contains("copia local está conservada"))
        #expect(DisplayText.workoutStatus("locally_pending") == "Programado en este dispositivo")
        #expect(DisplayText.workoutStatus("syncing") == "Sincronizando")
        #expect(DisplayText.workoutStatus("conflict") == "Requiere atención")
        #expect(DisplayText.planningConflict("schedule_date_conflict:scheduled_for_date") == "La fecha cambió en el servidor")
    }

    @Test func datesAndDurationsAreReadableWithoutExposingRawInvalidValues() {
        #expect(!DisplayText.readableDate("2026-07-20").contains("T"))
        #expect(DisplayText.readableDate("2026-07-20").contains("2026"))
        #expect(DisplayText.readableDate("20-07-2026") == "Fecha no disponible")
        #expect(DisplayText.readableInstant("not-a-date") == "Fecha no disponible")
        #expect(DisplayText.readableInstant(nil) == "Todavía no se ha sincronizado")
        #expect(DisplayText.readableInstant("2026-07-23T12:00:00Z", timeZone: TimeZone(identifier: "UTC")!).hasSuffix("12:00"))
        #expect(DisplayText.readableInstant("2026-07-23T12:00:00.123Z") != "Fecha no disponible")
        #expect(DisplayText.duration(5_460) == "1 h 31 min")
        #expect(DisplayText.duration(59) == "59 s")
        #expect(DisplayText.duration(nil) == "Duración no disponible")
    }

    @Test func decimalDraftPreservesInvalidInputForVisibleValidation() {
        #expect(DisplayText.decimalDraft("12..x") == "12..x")
        #expect(DisplayText.decimalDraft("12,5") == "12.5")
        #expect(DisplayText.decimalDraft("123456", maxLength: 4).count == 4)
    }

    @Test func isolatedDraftReasonsAreSanitizedAndSpecific() {
        #expect(DisplayText.draftIsolationReason("draft_package_missing") == "Package local ausente")
        #expect(DisplayText.draftIsolationReason("draft_device_mismatch") == "El borrador pertenece a otro dispositivo")
        #expect(DisplayText.draftIsolationReason("unexpected_internal_detail") == "Integridad local no verificable")
    }

    @Test func recordsTrendsAndPrescriptionsAreHuman() {
        #expect(DisplayText.recordType("highest_load") == "Mayor carga")
        #expect(DisplayText.trend("insufficient_data") == "Datos insuficientes para una tendencia")
        #expect(DisplayText.historySource("device_sync") == "Dispositivo")
        let set = PlanSet(id: "s", setNumber: 1, reps: nil, repsMin: 8, repsMax: 10, weightKg: "60.00", loadValue: "60", loadUnit: "kg",
                          loadMode: "direct_total", loadDetailsJSON: nil, rir: "2", rpe: nil, restSeconds: 120,
                          durationSeconds: nil, distanceMeters: nil, notes: nil)
        #expect(DisplayText.prescription(set) == "8–10 reps · 60 kg · RIR 2 · descanso 120 s")
    }
}

struct TrainingStoreTests {
    let scope = "qa-scope"

    @Test func historyPagesResetAndAppendInServerOrder() async throws {
        let store = try LocalStore.make(inMemory: true)
        let key = HistoryFilters().cacheKey
        let first = try QAFixtures.decode(MobileHistoryPageDTO.self, envelope: TrainingFixtures.historyPage([
            TrainingFixtures.historyItem(id: "a", name: "A"), TrainingFixtures.historyItem(id: "b", name: "B"),
        ]))
        try await store.applyHistoryPage(scope, cacheKey: key, page: first, reset: true)
        let second = try QAFixtures.decode(MobileHistoryPageDTO.self, envelope: TrainingFixtures.historyPage([TrainingFixtures.historyItem(id: "c", name: "C")], next: nil, hasMore: false))
        try await store.applyHistoryPage(scope, cacheKey: key, page: second, reset: false)
        #expect(await store.history(scope, cacheKey: key).map(\.name) == ["A", "B", "C"])
        #expect(await store.historyQueryState(scope, cacheKey: key) == HistoryQueryState(nextCursor: nil, hasMore: false))
        try await store.applyHistoryPage(scope, cacheKey: key, page: second, reset: true)
        #expect(await store.history(scope, cacheKey: key).map(\.name) == ["C"])
        // Other filter listings are untouched.
        #expect(await store.history(scope, cacheKey: HistoryFilters(dateFrom: "2026-01-01").cacheKey).isEmpty)
    }

    @Test func detailReplacesExercisesAndSetsAndKeepsSummaryFields() async throws {
        let store = try LocalStore.make(inMemory: true)
        let key = HistoryFilters().cacheKey
        let id = "11111111-1111-4111-8111-111111111111"
        try await store.applyHistoryPage(scope, cacheKey: key, page: try QAFixtures.decode(MobileHistoryPageDTO.self, envelope: TrainingFixtures.historyPage([TrainingFixtures.historyItem()])), reset: true)
        #expect(await store.historyDetail(scope, publicId: id)?.session.detailCached == false)
        let detail = try QAFixtures.decode(MobileHistoryDetailDTO.self, envelope: TrainingFixtures.historyDetail())
        try await store.applyHistoryDetail(scope, detail)
        try await store.applyHistoryDetail(scope, detail)
        let cached = try #require(await store.historyDetail(scope, publicId: id))
        #expect(cached.session.detailCached && cached.session.notes == "Nota QA" && cached.session.volumeKg == "640.00")
        #expect(cached.exercises.map(\.name) == ["Remo QA"])
        #expect(cached.exercises[0].sets.map(\.setNumber) == [1, 2])
        #expect(cached.exercises[0].sets[0].displayValue == "40")
        // A later list refresh updates the summary but keeps the cached detail.
        try await store.applyHistoryPage(scope, cacheKey: key, page: try QAFixtures.decode(MobileHistoryPageDTO.self, envelope: TrainingFixtures.historyPage([TrainingFixtures.historyItem(name: "Renombrada")])), reset: true)
        let refreshed = try #require(await store.historyDetail(scope, publicId: id))
        #expect(refreshed.session.name == "Renombrada" && refreshed.session.detailCached && refreshed.exercises[0].sets.count == 2)
    }

    @Test func progressReplacesExercisesPerRangeAndStoresPointsAndRecords() async throws {
        let store = try LocalStore.make(inMemory: true)
        let other = TrainingFixtures.exercise.replacingOccurrences(of: "22222222-2222-4222-8222-222222222222", with: "x").replacingOccurrences(of: "Remo QA", with: "Press QA")
        try await store.applyProgress(scope, summary: try QAFixtures.decode(ProgressSummaryDTO.self, envelope: TrainingFixtures.summary()),
                                      exercises: try QAFixtures.decode(ProgressExerciseListDTO.self, envelope: TrainingFixtures.exercises(items: [TrainingFixtures.exercise, other])))
        #expect(await store.progressExercises(scope, range: "7").map(\.name) == ["Press QA", "Remo QA"])
        try await store.applyProgress(scope, summary: try QAFixtures.decode(ProgressSummaryDTO.self, envelope: TrainingFixtures.summary()),
                                      exercises: try QAFixtures.decode(ProgressExerciseListDTO.self, envelope: TrainingFixtures.exercises()))
        #expect(await store.progressExercises(scope, range: "7").map(\.name) == ["Remo QA"])
        #expect(await store.progressSummary(scope, range: "7")?.hasComparison == true)
        #expect(await store.progressSummary(scope, range: "30") == nil)

        try await store.applyProgressExercise(scope, try QAFixtures.decode(ProgressExerciseDetailDTO.self, envelope: TrainingFixtures.exerciseDetail()))
        let id = "22222222-2222-4222-8222-222222222222"
        #expect(await store.progressPoints(scope, range: "30", publicId: id).map(\.bestLoadKg) == ["40.00"])
        #expect(await store.personalRecords(scope, range: "30", publicId: id).map(\.type) == ["highest_load"])
        #expect(await store.latestPersonalRecord(scope)?.value == "40.00")
        #expect(await store.progressExercise(scope, range: "30", publicId: id)?.bestReps == 8)
    }

    @Test func plansAreUpsertedWithDetailButLocalEditsAreProtected() async throws {
        let store = try LocalStore.make(inMemory: true)
        let list = try QAFixtures.decode(MobilePlanListDTO.self, #"{"items":[\#(TrainingFixtures.plan(withWorkouts: false))]}"#)
        #expect(try await store.applyPlanSummaries(scope, list) == ["qa-plan-1"])
        #expect(try await store.applyPlan(scope, try QAFixtures.decode(MobilePlanDTO.self, TrainingFixtures.plan())))
        let workouts = await store.planWorkouts(scope, planPublicId: "qa-plan-1")
        #expect(workouts.map(\.name) == ["Pierna QA"])
        #expect(workouts[0].exercises[0].sets[0].repsMax == 10)
        #expect(await store.planWorkout(scope, publicId: "qa-workout-1")?.exercises.count == 1)

        // A plan edited locally with queued planning work is not overwritten.
        try await store.setPlanSyncStatusForTesting(scope, "qa-plan-1", "pending")
        try await store.enqueue(scope, actionType: "planning_plan_patch", entityId: "qa-plan-1", idempotencyKey: "k1", payloadJSON: "{}")
        let renamed = try QAFixtures.decode(MobilePlanListDTO.self, #"{"items":[\#(TrainingFixtures.plan(name: "Remota", revision: 2, withWorkouts: false))]}"#)
        #expect(try await store.applyPlanSummaries(scope, renamed).isEmpty)
        #expect(try await !store.applyPlan(scope, try QAFixtures.decode(MobilePlanDTO.self, TrainingFixtures.plan(name: "Remota", revision: 2))))
        #expect(await store.plan(scope, publicId: "qa-plan-1")?.name == "Rutina QA")
    }

    @Test func archivedPlansAreHiddenUnlessRequested() async throws {
        let store = try LocalStore.make(inMemory: true)
        let list = try QAFixtures.decode(MobilePlanListDTO.self, #"{"items":[\#(TrainingFixtures.plan(withWorkouts: false)),\#(TrainingFixtures.plan(id: "qa-plan-2", name: "Vieja QA", status: "archived", withWorkouts: false))]}"#)
        try await store.applyPlanSummaries(scope, list)
        #expect(await store.plans(scope).map(\.name) == ["Rutina QA"])
        #expect(await store.plans(scope, includeArchived: true).map(\.name) == ["Rutina QA", "Vieja QA"])
    }

    @Test func trainingCacheIsIsolatedPerAccountAndClearedOnLogout() async throws {
        let store = try LocalStore.make(inMemory: true)
        let key = HistoryFilters().cacheKey
        let page = try QAFixtures.decode(MobileHistoryPageDTO.self, envelope: TrainingFixtures.historyPage([TrainingFixtures.historyItem()]))
        try await store.applyHistoryPage("a", cacheKey: key, page: page, reset: true)
        try await store.applyHistoryPage("b", cacheKey: key, page: page, reset: true)
        try await store.applyPlanSummaries("a", try QAFixtures.decode(MobilePlanListDTO.self, #"{"items":[\#(TrainingFixtures.plan(withWorkouts: false))]}"#))
        try await store.applyPlan("a", try QAFixtures.decode(MobilePlanDTO.self, TrainingFixtures.plan()))
        try await store.applyProgressExercise("a", try QAFixtures.decode(ProgressExerciseDetailDTO.self, envelope: TrainingFixtures.exerciseDetail()))
        #expect(await store.plans("b").isEmpty)
        try await store.clearAccountData("a")
        #expect(await store.history("a", cacheKey: key).isEmpty)
        #expect(await store.plans("a").isEmpty)
        #expect(await store.planWorkouts("a", planPublicId: "qa-plan-1").isEmpty)
        #expect(await store.latestPersonalRecord("a") == nil)
        #expect(await store.history("b", cacheKey: key).count == 1)
    }
}

struct TrainingRepositoryTests {
    @Test func refreshesHistoryPagesDetailProgressAndPlansThroughTheAPI() async throws {
        let h = try Harness()
        let scope = try await h.login().scope
        let repo = TrainingRepository(api: h.api, store: h.store)
        h.transport.on("GET", "/api/v1/mobile/history", json: TrainingFixtures.historyPage([TrainingFixtures.historyItem(id: "a")]))
        h.transport.on("GET", "/api/v1/mobile/history", json: TrainingFixtures.historyPage([TrainingFixtures.historyItem(id: "b")], next: nil, hasMore: false))
        try await repo.refreshHistory(scope: scope)
        try await repo.refreshHistory(scope: scope, reset: false)
        try await repo.refreshHistory(scope: scope, reset: false) // has_more == false: no request
        #expect(h.transport.count("GET", "/api/v1/mobile/history") == 2)
        let second = try #require(h.transport.requests.last { $0.url?.path == "/api/v1/mobile/history" })
        #expect(second.url?.query?.contains("cursor=cursor-qa") == true)
        #expect(await h.store.history(scope, cacheKey: HistoryFilters().cacheKey).map(\.id) == ["a", "b"])

        let id = "11111111-1111-4111-8111-111111111111"
        h.transport.on("GET", "/api/v1/mobile/history/\(id)", json: TrainingFixtures.historyDetail())
        try await repo.refreshHistoryDetail(scope: scope, publicId: id)
        #expect(await h.store.historyDetail(scope, publicId: id)?.exercises.count == 1)

        h.transport.on("GET", "/api/v1/mobile/progress/summary", json: TrainingFixtures.summary(range: "30"))
        h.transport.on("GET", "/api/v1/mobile/progress/exercises", json: TrainingFixtures.exercises(range: "30"))
        try await repo.refreshProgress(scope: scope, range: "30")
        #expect(await h.store.progressSummary(scope, range: "30")?.sessions == 1)

        h.transport.on("GET", "/api/v1/mobile/plans", json: #"{"data":{"items":[\#(TrainingFixtures.plan(withWorkouts: false))]}}"#)
        h.transport.on("GET", "/api/v1/mobile/plans/qa-plan-1", json: #"{"data":\#(TrainingFixtures.plan())}"#)
        try await repo.refreshPlans(scope: scope)
        #expect(await h.store.planWorkouts(scope, planPublicId: "qa-plan-1").count == 1)
    }

    @Test func filtersAreSentAsEncodedQueryParameters() async throws {
        let h = try Harness()
        let scope = try await h.login().scope
        let repo = TrainingRepository(api: h.api, store: h.store)
        h.transport.on("GET", "/api/v1/mobile/history", json: TrainingFixtures.historyPage([], next: nil, hasMore: false))
        try await repo.refreshHistory(scope: scope, filters: HistoryFilters(dateFrom: "2026-07-01", dateTo: "2026-07-31", exercisePublicId: "e 1"))
        let query = try #require(h.transport.requests.last?.url?.query)
        #expect(query == "limit=25&date_from=2026-07-01&date_to=2026-07-31&exercise_public_id=e+1")
    }

    @Test func incompatibleContractsNeverReplaceTheCache() async throws {
        let h = try Harness()
        let scope = try await h.login().scope
        let repo = TrainingRepository(api: h.api, store: h.store)
        h.transport.on("GET", "/api/v1/mobile/history", json: TrainingFixtures.historyPage([TrainingFixtures.historyItem(id: "a")]))
        try await repo.refreshHistory(scope: scope)
        h.transport.on("GET", "/api/v1/mobile/history", json: TrainingFixtures.historyPage([TrainingFixtures.historyItem(id: "z")], schema: "2.0"))
        await #expect(throws: AppFailure.self) { try await repo.refreshHistory(scope: scope) }
        #expect(await h.store.history(scope, cacheKey: HistoryFilters().cacheKey).map(\.id) == ["a"])

        h.transport.on("GET", "/api/v1/mobile/progress/summary", json: TrainingFixtures.summary(range: "7"))
        h.transport.on("GET", "/api/v1/mobile/progress/exercises", json: TrainingFixtures.exercises(range: "7"))
        await #expect(throws: AppFailure.self) { try await repo.refreshProgress(scope: scope, range: "30") }
        #expect(await h.store.progressSummary(scope, range: "30") == nil)

        h.transport.on("GET", "/api/v1/mobile/progress/exercises/other", json: TrainingFixtures.exerciseDetail())
        await #expect(throws: AppFailure.self) { try await repo.refreshProgressExercise(scope: scope, range: "30", publicId: "other") }
    }
}

extension LocalStore {
    /// Test-only: marks a cached plan as locally edited.
    func setPlanSyncStatusForTesting(_ scope: String, _ publicId: String, _ status: String) throws {
        let key = scopedKey(scope, publicId)
        try write { try fetch(#Predicate<PlanModel> { $0.key == key }).first?.syncStatus = status }
    }
}
