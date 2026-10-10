import HealthTrackerKit
import SwiftUI

/// Android `HistoryScreen`: cached sessions with date/exercise filters and cursor paging.
struct HistoryView: View {
    @Environment(AppModel.self) private var model
    @State private var useFrom = false
    @State private var useTo = false
    @State private var from = Calendar.current.date(byAdding: .month, value: -1, to: Date()) ?? Date()
    @State private var to = Date()
    @State private var exerciseId: String?
    @State private var showFilters = false

    private var training: TrainingModel { model.training }

    var body: some View {
        Screen {
            Muted(model.connected ? "Se muestra la copia local mientras se actualiza." : "Sin conexión: datos guardados en este dispositivo.")
            if model.syncSnapshot.pendingCount > 0 {
                Muted("Hay cambios pendientes; el historial se actualizará al sincronizar.")
            }
            filters
            if let error = training.historyError {
                Text("No se pudo actualizar: \(error) Se conserva la caché.").font(.footnote).foregroundStyle(Theme.dangerText)
            }
            if training.history.isEmpty {
                Text(training.historyRefreshing ? "Buscando sesiones…" : "No hay sesiones para estos filtros.").foregroundStyle(Theme.textMuted)
            }
            ForEach(training.history) { session in
                LinkCard(value: HistoryRoute(id: session.id)) {
                    Text(session.name).font(.headline)
                    Text(DisplayText.readableInstant(session.completedAt))
                    Text("\(session.exerciseCount) ejercicios · \(session.setCount) series")
                    Text(Self.volume(session.volumeKg, partial: session.volumePartial))
                    Muted("\(DisplayText.historySource(session.source)) · \(DisplayText.syncStatus(session.syncStatus)) · \(DisplayText.duration(session.durationSeconds))")
                }
                .accessibilityIdentifier("history_row")
            }
            if training.historyState?.hasMore == true {
                Button(training.historyRefreshing ? "Cargando…" : "Cargar más") {
                    Task { await training.refreshHistory(reset: false) }
                }
                .buttonStyle(SecondaryButtonStyle())
                .disabled(!model.connected || training.historyRefreshing)
            } else if !training.history.isEmpty {
                Muted("Fin del historial disponible.")
            }
        }
        .accessibilityIdentifier("history_screen")
        .navigationTitle("Historial")
        .navigationDestination(for: HistoryRoute.self) { HistoryDetailView(publicId: $0.id) }
        .refreshable { await training.refreshHistory() }
        .task { await training.refreshHistory() }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { showFilters.toggle() } label: {
                    Label("Filtros", systemImage: training.historyFilters.isEmpty ? "line.3.horizontal.decrease.circle" : "line.3.horizontal.decrease.circle.fill")
                }
            }
        }
    }

    @ViewBuilder private var filters: some View {
        if showFilters {
            Card {
                Text("Filtros").font(.headline)
                Toggle("Desde", isOn: $useFrom)
                if useFrom { DatePicker("Fecha inicial", selection: $from, displayedComponents: .date).labelsHidden() }
                Toggle("Hasta", isOn: $useTo)
                if useTo { DatePicker("Fecha final", selection: $to, displayedComponents: .date).labelsHidden() }
                if !training.progressExercises.isEmpty {
                    Muted("Ejercicio")
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: Theme.Space.s2) {
                            ForEach(training.progressExercises.prefix(20)) { exercise in
                                Chip(title: exercise.name, selected: exerciseId == exercise.publicId) {
                                    exerciseId = exerciseId == exercise.publicId ? nil : exercise.publicId
                                }
                            }
                        }
                    }
                }
                HStack(spacing: Theme.Space.s2) {
                    Button("Aplicar") {
                        Task { await training.setHistoryFilters(from: useFrom ? from : nil, to: useTo ? to : nil, exercisePublicId: exerciseId) }
                    }
                    .buttonStyle(PrimaryButtonStyle())
                    .disabled(training.historyRefreshing)
                    Button("Limpiar") {
                        useFrom = false; useTo = false; exerciseId = nil
                        Task { await training.clearHistoryFilters() }
                    }
                    .buttonStyle(SecondaryButtonStyle())
                }
            }
        } else if !training.historyFilters.isEmpty {
            HStack {
                Muted("Filtros activos")
                Spacer()
                Button("Limpiar") {
                    useFrom = false; useTo = false; exerciseId = nil
                    Task { await training.clearHistoryFilters() }
                }
                .font(.footnote.weight(.semibold))
            }
        }
    }

    static func volume(_ value: String?, partial: Bool) -> String {
        guard let value else { return "Volumen no comparable" }
        return "Volumen \(value) kg\(partial ? " (parcial)" : "")"
    }
}

struct HistoryRoute: Hashable { let id: String }

/// Android `HistoryDetailScreen`.
struct HistoryDetailView: View {
    @Environment(AppModel.self) private var model
    let publicId: String

    var body: some View {
        Screen {
            if let detail = model.training.selectedHistory, detail.session.id == publicId {
                let session = detail.session
                Card {
                    Text(session.name).font(.title3.weight(.semibold)).accessibilityAddTraits(.isHeader)
                    Text(DisplayText.readableInstant(session.completedAt))
                    Text(DisplayText.duration(session.durationSeconds))
                    Muted("\(DisplayText.historySource(session.source)) · \(DisplayText.syncStatus(session.syncStatus))")
                    if let volume = session.volumeKg { Text("Volumen: \(volume) kg\(session.volumePartial ? " (parcial)" : "")") }
                    if let notes = session.notes { Text("Notas: \(notes)") }
                    if session.plannedWorkoutId != nil { Muted("Vinculada al entrenamiento planificado") }
                }
                ForEach(detail.exercises) { exercise in
                    SectionTitle(exercise.name)
                    if let notes = exercise.notes { Muted(notes) }
                    ForEach(exercise.sets) { set in
                        Card {
                            Text("Serie \(set.setNumber)").font(.headline)
                            Text(Self.load(set))
                            Text("\(set.reps) reps\(set.rir.map { " · RIR \($0)" } ?? "")\(set.rpe.map { " · RPE \($0)" } ?? "")")
                            if let rest = set.restSeconds { Muted("Descanso: \(rest) s") }
                            if let duration = set.durationSeconds { Muted("Duración: \(duration) s") }
                            if let distance = set.distanceMeters { Muted("Distancia: \(distance) m") }
                            if let notes = set.notes { Muted("Notas: \(notes)") }
                        }
                        .accessibilityElement(children: .combine)
                    }
                }
                if !session.detailCached {
                    Muted("El resumen está disponible offline; conecta para descargar el detalle completo.")
                }
            } else {
                Text("Cargando detalle guardado…").foregroundStyle(Theme.textMuted)
            }
        }
        .navigationTitle("Sesión")
        .navigationBarTitleDisplayMode(.inline)
        .task { await model.training.openHistory(publicId) }
    }

    static func load(_ set: HistorySet) -> String {
        if let value = set.displayValue { return "\(value) \(set.displayUnit ?? "kg")" }
        if let weight = set.weightKg { return "\(weight) kg" }
        return "Carga no disponible"
    }
}
