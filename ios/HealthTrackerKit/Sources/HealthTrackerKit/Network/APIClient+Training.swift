import Foundation

// MARK: History, progress and planning reads (android `ApiClient.history…plan`)

extension APIClient {
    public func history(
        cursor: String? = nil,
        limit: Int = 25,
        dateFrom: String? = nil,
        dateTo: String? = nil,
        exercisePublicId: String? = nil
    ) async throws -> MobileHistoryPageDTO {
        var query = ["limit=\(limit)"]
        if let cursor { query.append("cursor=\(Self.encodeQuery(cursor))") }
        if let dateFrom { query.append("date_from=\(Self.encodeQuery(dateFrom))") }
        if let dateTo { query.append("date_to=\(Self.encodeQuery(dateTo))") }
        if let exercisePublicId { query.append("exercise_public_id=\(Self.encodeQuery(exercisePublicId))") }
        return try await call("/api/v1/mobile/history?\(query.joined(separator: "&"))", method: "GET")
    }

    public func historyDetail(_ publicId: String) async throws -> MobileHistoryDetailDTO {
        try await call("/api/v1/mobile/history/\(Self.encodePathComponent(publicId))", method: "GET")
    }

    public func progressSummary(range: String) async throws -> ProgressSummaryDTO {
        try await call("/api/v1/mobile/progress/summary?range=\(Self.encodeQuery(range))", method: "GET")
    }

    public func progressExercises(range: String) async throws -> ProgressExerciseListDTO {
        try await call("/api/v1/mobile/progress/exercises?range=\(Self.encodeQuery(range))", method: "GET")
    }

    public func progressExercise(_ publicId: String, range: String) async throws -> ProgressExerciseDetailDTO {
        try await call("/api/v1/mobile/progress/exercises/\(Self.encodePathComponent(publicId))?range=\(Self.encodeQuery(range))", method: "GET")
    }

    public func plans(status: String = "active") async throws -> MobilePlanListDTO {
        try await call("/api/v1/mobile/plans?status=\(Self.encodeQuery(status))", method: "GET")
    }

    public func plan(_ publicId: String) async throws -> MobilePlanDTO {
        try await call("/api/v1/mobile/plans/\(Self.encodePathComponent(publicId))", method: "GET")
    }
}
