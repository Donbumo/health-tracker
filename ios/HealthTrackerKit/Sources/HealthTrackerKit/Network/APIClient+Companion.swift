import Foundation

// MARK: Companion deliveries (android `ApiClient.createDelivery…complete`)

extension APIClient {
    public func createDelivery(plannedWorkoutId: String, key: String) async throws -> DeliveryDTO {
        let body: JSONValue = .object([("schema_version", .string(contractVersion)), ("planned_workout_id", .string(plannedWorkoutId))])
        return try await call("/api/v1/companion/deliveries", method: "POST", body: Data(body.encoded().utf8), idempotencyKey: key)
    }

    public func deliveries() async throws -> [DeliveryDTO] {
        try await call("/api/v1/companion/deliveries", method: "GET")
    }

    /// Downloads the package and verifies its SHA-256 and 1.0 structure before anything is stored.
    public func downloadPackage(deliveryId: String) async throws -> VerifiedPackage {
        let data = try await callJSON("/api/v1/companion/deliveries/\(Self.encodePathComponent(deliveryId))/package", method: "GET")
        return try Self.verifyPackage(data)
    }

    static func verifyPackage(_ data: JSONValue) throws -> VerifiedPackage {
        guard let declared = data["package_hash"]?.stringValue else {
            throw AppFailure(.schemaIncompatible, "El package no declara su hash.", retryable: false)
        }
        let calculated = CanonicalJSON.sha256(data, excludingTopLevelKey: "package_hash")
        guard declared.lowercased() == calculated else {
            throw AppFailure(.packageHashMismatch, "El package descargado no pasó la verificación SHA-256.", retryable: false)
        }
        let decoded: WorkoutPackageDTO
        do {
            decoded = try JSONDecoder().decode(WorkoutPackageDTO.self, from: Data(data.encoded().utf8))
        } catch {
            throw AppFailure(.schemaIncompatible, "El package no cumple la estructura de entrenamiento 1.0.", retryable: false)
        }
        guard decoded.schemaVersion == contractVersion else {
            throw AppFailure(.schemaIncompatible, "La versión del package no es compatible.", retryable: false)
        }
        let orders = decoded.exercises.map(\.exerciseOrder)
        guard !decoded.exercises.isEmpty, Set(orders).count == orders.count,
              !decoded.exercises.contains(where: { $0.exerciseOrder < 1 || $0.name.trimmingCharacters(in: .whitespaces).isEmpty || $0.sets.isEmpty }) else {
            throw AppFailure(.schemaIncompatible, "El package no cumple la estructura de entrenamiento 1.0.", retryable: false)
        }
        return VerifiedPackage(value: decoded, calculatedHash: calculated)
    }

    public func transition(deliveryId: String, action: String, operation: JSONValue, key: String) async throws -> DeliveryDTO {
        try await call("/api/v1/companion/deliveries/\(Self.encodePathComponent(deliveryId))/\(action)", method: "POST",
                       body: Data(operation.encoded().utf8), idempotencyKey: key)
    }

    public func progress(deliveryId: String, request: JSONValue, key: String) async throws {
        _ = try await callJSON("/api/v1/companion/deliveries/\(Self.encodePathComponent(deliveryId))/progress", method: "POST",
                               body: Data(request.encoded().utf8), idempotencyKey: key)
    }

    public func complete(deliveryId: String, request: JSONValue, key: String) async throws -> CompletionResponse {
        try await call("/api/v1/companion/deliveries/\(Self.encodePathComponent(deliveryId))/complete", method: "POST",
                       body: Data(request.encoded().utf8), idempotencyKey: key)
    }
}
