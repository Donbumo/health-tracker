import Foundation

/// Human copy for internal states and values (android `UiFormatters.kt`). Wire codes are never shown raw.
public enum DisplayText {
    public struct ChartScale: Sendable, Equatable {
        public let minimum: Double
        public let maximum: Double
        public let span: Double
    }

    public static func chartScale(_ values: [Double]) -> ChartScale? {
        let finite = values.filter(\.isFinite)
        guard let minimum = finite.min(), let maximum = finite.max() else { return nil }
        let span = maximum - minimum
        return ChartScale(minimum: minimum, maximum: maximum, span: span > 0 ? span : 1)
    }

    private static let locale = Locale(identifier: "es_MX")

    public static func readableDate(_ value: String) -> String {
        let parser = DateFormatter()
        parser.locale = Locale(identifier: "en_US_POSIX")
        parser.timeZone = TimeZone(identifier: "UTC")
        parser.dateFormat = "yyyy-MM-dd"
        guard value.count == 10, let date = parser.date(from: value) else { return "Fecha no disponible" }
        let formatter = DateFormatter()
        formatter.locale = locale
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.dateFormat = "d MMM yyyy"
        return formatter.string(from: date)
    }

    public static func readableInstant(_ value: String?, timeZone: TimeZone = .current) -> String {
        guard let value, !value.trimmingCharacters(in: .whitespaces).isEmpty else { return "Todavía no se ha sincronizado" }
        guard let date = parseInstant(value) else { return "Fecha no disponible" }
        let formatter = DateFormatter()
        formatter.locale = locale
        formatter.timeZone = timeZone
        formatter.dateFormat = "d MMM yyyy, HH:mm"
        return formatter.string(from: date)
    }

    public static func parseInstant(_ value: String) -> Date? {
        let plain = ISO8601DateFormatter()
        if let date = plain.date(from: value) { return date }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return fractional.date(from: value)
    }

    public static func duration(_ seconds: Int?) -> String {
        guard let seconds, seconds >= 0 else { return "Duración no disponible" }
        let hours = seconds / 3_600
        let minutes = (seconds % 3_600) / 60
        if hours > 0 { return "\(hours) h \(minutes) min" }
        if minutes > 0 { return "\(minutes) min" }
        return "\(seconds) s"
    }

    public static func draftStatus(_ status: String) -> String {
        switch status {
        case "active": "Activo"
        case "paused": "En pausa"
        case "saved": "Guardado localmente"
        case "pending_sync": "Guardado; sincronización pendiente"
        case "completion_pending": "Finalización pendiente"
        case "aborted_pending": "Cancelación pendiente"
        case "corrupt": "Requiere intervención"
        default: "Estado no disponible"
        }
    }

    public static func draftIsolationReason(_ code: String?) -> String {
        switch code {
        case "draft_schema_incompatible": "Versión de borrador incompatible"
        case "draft_expired": "El borrador local expiró"
        case "draft_package_missing": "Package local ausente"
        case "draft_package_mismatch": "Identidad o hash del package no coincide"
        case "draft_delivery_missing": "Delivery local ausente"
        case "draft_package_content_missing": "Contenido estructural del package ausente"
        case "draft_sets_missing": "Series locales ausentes"
        case "draft_metric_invalid": "Métrica local inválida"
        case "draft_payload_hash_mismatch": "Integridad del borrador no coincide"
        case "draft_start_state_missing": "No existe evidencia local o remota del inicio"
        case "draft_account_missing": "Cuenta local ausente"
        case "draft_account_scope_mismatch": "El borrador pertenece a otro ámbito de cuenta"
        case "draft_device_mismatch": "El borrador pertenece a otro dispositivo"
        case "draft_profile_missing": "Perfil Companion local ausente"
        case "draft_profile_mismatch": "El borrador pertenece a otro perfil Companion"
        default: "Integridad local no verificable"
        }
    }

    public static func workoutStatus(_ status: String) -> String {
        switch status {
        case "planned": "Programado"
        case "locally_pending": "Programado en este dispositivo"
        case "syncing": "Sincronizando"
        case "downloaded": "Descargado"
        case "started_pending": "Inicio pendiente de sincronización"
        case "active": "Activo"
        case "in_progress": "En progreso"
        case "completed": "Completado"
        case "cancelled": "Cancelado"
        case "conflict": "Requiere atención"
        default: "Estado no disponible"
        }
    }

    public static func planningConflict(_ value: String) -> String {
        switch value.split(separator: ":", maxSplits: 1).first.map(String.init) ?? value {
        case "remote_deleted": "La rutina se eliminó en el servidor. Tu copia local está conservada: puedes duplicarla o aceptar la eliminación con Usar servidor."
        case "revision_conflict", "revision", "remote_revision": "La revisión cambió en el servidor"
        case "archived_remote": "La rutina fue archivada en el servidor"
        case "deleted_or_unavailable": "El recurso ya no está disponible"
        case "schedule_date_conflict": "La fecha cambió en el servidor"
        case "package_revision_conflict": "Existe una versión más reciente del entrenamiento"
        default: "El cambio local requiere revisión"
        }
    }

    public static func syncStatus(_ status: String) -> String {
        switch status {
        case "synced": "Sincronizado"
        case "pending", "pending_sync": "Pendiente de sincronización"
        case "sending": "Enviando"
        case "conflict": "Requiere intervención"
        case "rejected": "Rechazado"
        default: "Estado no disponible"
        }
    }

    public static func planningSync(_ value: String) -> String {
        switch value {
        case "pending": "guardado local, pendiente"
        case "syncing": "sincronizando"
        case "conflict": "requiere atención"
        default: "sincronizado"
        }
    }

    public static func recordType(_ value: String) -> String {
        switch value {
        case "highest_load": "Mayor carga"
        case "most_reps_at_comparable_load": "Más repeticiones"
        case "highest_set_volume": "Mayor volumen de serie"
        case "highest_session_volume": "Mayor volumen de sesión"
        default: "Mejor marca"
        }
    }

    public static func trend(_ value: String) -> String {
        switch value {
        case "up": "Tendencia al alza"
        case "down": "Tendencia a la baja"
        case "stable": "Tendencia estable"
        default: "Datos insuficientes para una tendencia"
        }
    }

    public static func historySource(_ value: String) -> String {
        switch value {
        case "device_sync": "Dispositivo"
        case "import": "Importado"
        case "manual": "Registro manual"
        default: "Servidor"
        }
    }

    public static func decimalDraft(_ value: String, maxLength: Int = 16) -> String {
        String(value.replacingOccurrences(of: ",", with: ".").prefix(maxLength))
    }

    /// Plan prescription summary such as "8–10 reps · 60 kg · RIR 2".
    public static func prescription(_ set: PlanSet) -> String {
        var parts: [String] = []
        if let min = set.repsMin, let max = set.repsMax { parts.append("\(min)–\(max) reps") }
        else if let reps = set.reps { parts.append("\(reps) reps") }
        if let value = set.loadValue ?? set.weightKg { parts.append("\(value) \(set.loadValue == nil ? "kg" : set.loadUnit)") }
        if let duration = set.durationSeconds { parts.append(Self.duration(duration)) }
        if let distance = set.distanceMeters { parts.append("\(distance) m") }
        if let rir = set.rir { parts.append("RIR \(rir)") }
        if let rpe = set.rpe { parts.append("RPE \(rpe)") }
        if let rest = set.restSeconds { parts.append("descanso \(rest) s") }
        return parts.isEmpty ? "Sin prescripción" : parts.joined(separator: " · ")
    }

    public static func loadMode(_ value: LoadMode) -> String {
        switch value {
        case .directTotal: "Carga total directa"
        case .perSide: "Carga por lado"
        case .barPlusPerSide: "Barra más carga por lado"
        case .machineInitialTotal: "Máquina: inicial más añadida"
        case .machineInitialPerSide: "Máquina: carga por lado"
        case .machineExternalPerSideInitialTotal: "Máquina: inicial total más carga externa por lado"
        case .selectorStack: "Torre selectora"
        case .dumbbellEach: "Mancuerna por mano"
        case .bodyweight: "Peso corporal"
        case .bodyweightPlus: "Peso corporal más carga"
        case .assistance: "Peso corporal con asistencia"
        case .durationDistance: "Duración y distancia"
        }
    }

    public static func component(_ value: String) -> String {
        switch value {
        case "direct_total": "Carga total"
        case "per_side": "Carga por lado"
        case "bar": "Barra"
        case "initial_total": "Carga inicial total"
        case "added_total": "Carga añadida total"
        case "initial_per_side": "Carga inicial por lado"
        case "external_per_side": "Carga externa por lado"
        case "selector_stack": "Torre seleccionada"
        case "dumbbell_each": "Cada mancuerna"
        case "bodyweight": "Peso corporal"
        case "assistance": "Asistencia"
        case "duration_seconds": "Duración"
        case "distance_meters": "Distancia"
        default: "Componente"
        }
    }

    /// Editor mode for a set: its stored mode, or duration/distance when only those metrics exist.
    public static func initialLoadMode(existing: String?, durationSeconds: Int?, distanceMeters: String?) -> LoadMode {
        if let existing, let mode = LoadMode(rawValue: existing) { return mode }
        return durationSeconds != nil || distanceMeters != nil ? .durationDistance : .directTotal
    }

    public static func autosaveStatus(_ state: AutosaveState) -> String {
        switch state {
        case .saving: "Guardando…"
        case .saved: "Guardado"
        case .savedLocal: "Guardado en este dispositivo"
        case .error: "Requiere atención: no se pudo guardar localmente"
        }
    }
}

public enum AutosaveState: Sendable, Equatable {
    case saving, saved, savedLocal, error
}
