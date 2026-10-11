import HealthTrackerKit
import SwiftUI
import UIKit

/// Download / start / continue actions for one planned workout (Android `TodayScreen` workout cards).
struct WorkoutActions: View {
    @Environment(AppModel.self) private var model
    let workout: PlannedWorkout

    var body: some View {
        let session = model.workout
        let package = session.package(forPlanned: workout.id)
        let active = package != nil && session.draft?.deliveryId == package?.deliveryId
        Group {
            if workout.status == "completed" || workout.status == "cancelled" {
                EmptyView()
            } else if active {
                if session.draft?.isFinalPending == false {
                    Button("Continuar") { Task { await session.resume() } }
                        .buttonStyle(PrimaryButtonStyle())
                        .accessibilityIdentifier("continue_workout")
                }
            } else if package != nil {
                Muted("Descargado · disponible sin conexión").accessibilityIdentifier("offline_available")
                Button(session.starting ? "Iniciando…" : "Empezar") { Task { await session.start(workout.id) } }
                    .buttonStyle(PrimaryButtonStyle())
                    .disabled(session.starting || session.draft.map { !$0.isFinalPending && $0.status != "corrupt" } == true)
                    .accessibilityIdentifier("start_workout")
            } else {
                Button(session.downloading == workout.id ? "Descargando…" : model.connected ? "Descargar para usar offline" : "Descarga requiere conexión") {
                    Task { await session.download(workout.id) }
                }
                .buttonStyle(SecondaryButtonStyle())
                .disabled(!model.connected || session.downloading != nil || ["locally_pending", "syncing", "conflict"].contains(workout.status))
                .accessibilityIdentifier("download_workout")
            }
        }
    }
}

/// Active or pending draft summary on Today.
struct DraftCard: View {
    @Environment(AppModel.self) private var model
    let draft: WorkoutDraft
    @State private var confirmDiscard = false

    var body: some View {
        Card {
            Text("Entrenamiento en progreso").font(.headline)
            Text("Estado: \(DisplayText.draftStatus(draft.status))").accessibilityIdentifier("draft_status")
            if draft.status == "corrupt" {
                Text("El borrador no superó una validación local de integridad. No se enviará.").foregroundStyle(Theme.dangerText)
                Muted(DisplayText.draftIsolationReason(draft.corruptReasonCode))
                Button("Descartar borrador corrupto") { confirmDiscard = true }
                    .buttonStyle(SecondaryButtonStyle(destructive: true))
            } else if draft.isFinalPending {
                Text(draft.status == "completion_pending" ? "Entrenamiento completado" : "Cancelación guardada").font(.subheadline.weight(.semibold))
                Muted("La operación final ya está guardada y se enviará al sincronizar.")
                Button("Sincronizar ahora") { model.syncNow() }
                    .buttonStyle(SecondaryButtonStyle())
                    .disabled(!model.connected)
            } else {
                Button("Continuar") { Task { await model.workout.resume() } }
                    .buttonStyle(PrimaryButtonStyle())
            }
        }
        .confirmationDialog("¿Descartar borrador aislado?", isPresented: $confirmDiscard, titleVisibility: .visible) {
            Button("Descartar", role: .destructive) { Task { await model.workout.discardCorrupt() } }
        } message: {
            Text("Se eliminará únicamente este borrador local y sus operaciones pendientes. No se puede deshacer.")
        }
    }
}

/// Android `WorkoutScreen`: one exercise at a time, set editors with autosave, rest timer and summary.
struct WorkoutView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dismiss) private var dismiss
    @State private var exerciseIndex = 0
    @State private var restRemaining = 0
    @State private var confirmComplete = false
    @State private var confirmAbort = false

    var body: some View {
        let session = model.workout
        NavigationStack {
            Group {
                if let draft = session.draft, draft.status == "corrupt" {
                    IsolatedDraftView(reason: draft.corruptReasonCode)
                } else if let draft = session.draft, draft.isFinalPending {
                    VStack(spacing: Theme.Space.s4) {
                        Text("La operación final está pendiente de confirmación; la captura quedó bloqueada.").multilineTextAlignment(.center)
                        Button("Volver a Hoy") { close() }.buttonStyle(PrimaryButtonStyle())
                    }
                    .padding(Theme.Space.s5)
                } else if let draft = session.draft, !session.exercises.isEmpty {
                    capture(draft)
                } else {
                    ProgressView("Recuperando borrador local…")
                }
            }
            .background(Theme.bg)
            .navigationTitle("Entrenamiento")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Cerrar") { close() } }
                if let draft = session.draft, !draft.isFinalPending, draft.status != "corrupt" {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button(draft.status == "paused" ? "Continuar" : "Pausar") { Task { await session.pauseOrResume() } }
                    }
                }
            }
        }
        .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
        .onDisappear { UIApplication.shared.isIdleTimerDisabled = false }
        .onChange(of: scenePhase) { _, phase in
            if phase != .active { Task { await session.flush() } }
        }
        .task(id: restRemaining) {
            guard restRemaining > 0 else { return }
            try? await Task.sleep(for: .seconds(1))
            if restRemaining > 0 { restRemaining -= 1 }
        }
    }

    private func close() {
        Task {
            await model.workout.flush()
            model.workout.presented = false
            dismiss()
        }
    }

    @ViewBuilder private func capture(_ draft: WorkoutDraft) -> some View {
        let session = model.workout
        let exercises = session.exercises
        let index = min(max(exerciseIndex, 0), exercises.count - 1)
        let current = exercises[index]
        let currentSets = session.sets.filter { $0.exerciseOrder == current.exerciseOrder }
        let completed = session.sets.filter(\.completed).count
        Screen {
            ProgressView(value: session.sets.isEmpty ? 0 : Double(completed), total: Double(max(session.sets.count, 1)))
                .tint(Theme.primary)
            Text("\(completed) de \(session.sets.count) series · ejercicio \(index + 1) de \(exercises.count)")
            Muted(model.connected ? "Los cambios se guardan primero en este dispositivo." : "Modo offline: los cambios quedarán pendientes hasta recuperar la red.")
            Muted(DisplayText.autosaveStatus(session.autosaveState)).accessibilityIdentifier("autosave_status")
            if restRemaining > 0 {
                Text("Descanso: \(restRemaining) s").font(.title2.weight(.semibold)).monospacedDigit()
                    .accessibilityAddTraits(.updatesFrequently)
            }
            HStack(spacing: Theme.Space.s2) {
                Button("Anterior") { Task { await session.flush(); exerciseIndex = max(index - 1, 0) } }
                    .buttonStyle(SecondaryButtonStyle()).disabled(index == 0)
                Button("Siguiente") { Task { await session.flush(); exerciseIndex = min(index + 1, exercises.count - 1) } }
                    .buttonStyle(SecondaryButtonStyle()).disabled(index == exercises.count - 1)
            }
            Text(current.name).font(.title2.weight(.semibold)).accessibilityAddTraits(.isHeader)
            if let notes = current.notes, !notes.isEmpty { Muted(notes) }
            ForEach(currentSets) { set in
                SetEditorView(
                    value: set,
                    unit: model.preferences.unit == .lb ? "lb" : "kg",
                    previous: currentSets.filter { $0.setNumber < set.setNumber }.max { $0.setNumber < $1.setNumber },
                    busy: session.setActions.contains { $0.hasSuffix(set.id) },
                    onComplete: { value in
                        restRemaining = value.restSeconds ?? 0
                        Task { await session.complete(value) }
                    }
                )
                .id("\(draft.deliveryId)-\(set.id)")
            }
            SummaryEditor(draft: draft)
            Button("Completar entrenamiento") { confirmComplete = true }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(completed == 0 || session.finalActionInProgress)
                .accessibilityIdentifier("complete_workout")
            Button("Abortar entrenamiento") { confirmAbort = true }
                .buttonStyle(SecondaryButtonStyle(destructive: true))
                .disabled(session.finalActionInProgress)
        }
        .accessibilityIdentifier("workout_screen")
        .confirmationDialog("¿Completar entrenamiento?", isPresented: $confirmComplete, titleVisibility: .visible) {
            Button("Completar") { Task { await session.finish(abort: false) } }
        } message: {
            Text("El resultado quedará guardado localmente y se enviará de forma idempotente.")
        }
        .confirmationDialog("¿Abortar entrenamiento?", isPresented: $confirmAbort, titleVisibility: .visible) {
            Button("Abortar", role: .destructive) { Task { await session.finish(abort: true) } }
        } message: {
            Text("Se conservará la operación hasta que el servidor confirme la cancelación.")
        }
    }
}

/// Android `SetEditor`: load mode, components with per-component unit, metrics and completion.
private struct SetEditorView: View {
    @Environment(AppModel.self) private var model
    let value: DraftSet
    let unit: String
    let previous: DraftSet?
    let busy: Bool
    let onComplete: (DraftSet) -> Void

    @State private var mode: LoadMode
    @State private var components: [String: String]
    @State private var units: [String: String]
    @State private var reps: String
    @State private var rir: String
    @State private var rpe: String
    @State private var rest: String
    @State private var notes: String

    init(value: DraftSet, unit: String, previous: DraftSet?, busy: Bool, onComplete: @escaping (DraftSet) -> Void) {
        self.value = value
        self.unit = unit
        self.previous = previous
        self.busy = busy
        self.onComplete = onComplete
        let details = value.loadDetailsJSON.flatMap { try? JSONValue.parse($0) }
        let mode = DisplayText.initialLoadMode(existing: details?["load_mode"]?.stringValue, durationSeconds: value.durationSeconds, distanceMeters: value.distanceMeters)
        var components: [String: String] = [:]
        var units: [String: String] = [:]
        for name in mode.components {
            let stored = details?["components"]?[name]
            components[name] = stored?["value"]?.stringValue ?? Self.defaultValue(name, value)
            units[name] = name == "duration_seconds" ? "s" : name == "distance_meters" ? "m" : stored?["unit"]?.stringValue ?? unit
        }
        _mode = State(initialValue: mode)
        _components = State(initialValue: components)
        _units = State(initialValue: units)
        _reps = State(initialValue: String(value.reps))
        _rir = State(initialValue: value.rir ?? "")
        _rpe = State(initialValue: value.rpe ?? "")
        _rest = State(initialValue: value.restSeconds.map(String.init) ?? "")
        _notes = State(initialValue: value.notes ?? "")
    }

    private static func defaultValue(_ name: String, _ value: DraftSet) -> String {
        switch name {
        case "direct_total": LoadCalculator.parse(value.weightKg).map(LoadCalculator.text) ?? "0"
        case "duration_seconds": value.durationSeconds.map(String.init) ?? "0"
        case "distance_meters": value.distanceMeters ?? "0"
        default: "0"
        }
    }

    private var preview: Result<LoadPreview, Error> {
        Result {
            var inputs: [String: ComponentInput] = [:]
            for name in mode.components {
                guard let number = LoadCalculator.parse(components[name] ?? "") else {
                    throw LoadValidationError("\(DisplayText.component(name)) no es un número válido.")
                }
                inputs[name] = ComponentInput(number, units[name] ?? unit)
            }
            return try LoadCalculator.calculate(mode: mode, displayUnit: unit, components: inputs)
        }
    }

    private var repsError: String? {
        guard let number = Int(reps) else { return reps.isEmpty ? "Indica las repeticiones." : "Usa un número entero." }
        return (1...10_000).contains(number) ? nil : "Debe estar entre 1 y 10 000."
    }
    private var rirError: String? { rir.isEmpty || LoadCalculator.parse(rir).map({ $0 <= 10 }) == true ? nil : "RIR debe estar entre 0 y 10." }
    private var rpeError: String? { rpe.isEmpty || LoadCalculator.parse(rpe).map({ $0 >= 1 && $0 <= 10 }) == true ? nil : "RPE debe estar entre 1 y 10." }
    private var restError: String? { rest.isEmpty || Int(rest).map({ (0...86_400).contains($0) }) == true ? nil : "El descanso debe estar entre 0 y 86 400 s." }
    private var durationError: String? {
        guard let text = components["duration_seconds"], let duration = LoadCalculator.parse(text) else { return nil }
        return duration > 86_400 ? "La duración máxima es 86 400 s." : nil
    }
    private var validMetrics: Bool { repsError == nil && rirError == nil && rpeError == nil && restError == nil && durationError == nil }

    /// The draft set this editor currently describes, when valid.
    private var candidate: DraftSet? {
        guard validMetrics, let repsNumber = Int(reps), case let .success(load) = preview else { return nil }
        var updated = value
        updated.reps = repsNumber
        updated.rir = rir.isEmpty ? nil : rir
        updated.rpe = rpe.isEmpty ? nil : rpe
        updated.notes = notes.isEmpty ? nil : String(notes.prefix(2000))
        updated.weightKg = load.weightKg
        updated.loadDetailsJSON = load.details.encoded()
        updated.durationSeconds = components["duration_seconds"].flatMap { LoadCalculator.parse($0) }.map { NSDecimalNumber(decimal: $0).intValue }.flatMap { $0 > 0 ? $0 : nil }
        updated.distanceMeters = components["distance_meters"].flatMap { $0.isEmpty ? nil : $0 }
        updated.restSeconds = rest.isEmpty ? nil : Int(rest)
        return updated
    }

    var body: some View {
        Card {
            HStack {
                Text("Serie \(value.setNumber)").font(.headline)
                Spacer()
                if value.completed { StatusPill(text: "Completada", tone: .success) }
            }
            Menu {
                ForEach(LoadMode.allCases, id: \.self) { candidate in
                    Button(DisplayText.loadMode(candidate)) { select(candidate) }
                }
            } label: {
                HStack {
                    Text(DisplayText.loadMode(mode))
                    Spacer()
                    Image(systemName: "chevron.up.chevron.down")
                }
                .modifier(FieldStyle())
            }
            ForEach(mode.components, id: \.self) { name in
                VStack(alignment: .leading, spacing: Theme.Space.s1) {
                    Text("\(DisplayText.component(name)) (\(units[name] ?? unit))").font(.caption).foregroundStyle(Theme.textMuted)
                    TextField(DisplayText.component(name), text: binding(name))
                        .keyboardType(.decimalPad)
                        .modifier(FieldStyle())
                    if !LoadMode.isMeasure(name) {
                        HStack(spacing: Theme.Space.s2) {
                            ForEach(["kg", "lb"], id: \.self) { option in
                                Chip(title: option, selected: units[name] == option) { units[name] = option; changed() }
                            }
                        }
                    }
                }
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: Theme.Space.s2) {
                    Button("−2.5") { step(-2.5) }
                    Button("+2.5") { step(2.5) }
                    if let previous { Button("Copiar carga") { Task { await model.workout.copyLoad(from: previous, to: value) } } }
                    Button("Duplicar") { Task { await model.workout.duplicate(value) } }.disabled(busy)
                }
                .buttonStyle(.bordered)
            }
            switch preview {
            case let .success(load):
                Text("Total: \(LoadCalculator.storageWeight(load.totalKg)) kg · \(LoadCalculator.storageWeight(load.totalLb)) lb").font(.subheadline)
            case let .failure(error):
                Text(WorkoutModel.message(error)).font(.footnote).foregroundStyle(Theme.dangerText)
            }
            HStack(alignment: .top, spacing: Theme.Space.s2) {
                metric("Reps", $reps, error: repsError, keyboard: .numberPad)
                metric("RIR", $rir, error: rirError, keyboard: .decimalPad)
                metric("RPE", $rpe, error: rpeError, keyboard: .decimalPad)
            }
            metric("Descanso (s)", $rest, error: restError, keyboard: .numberPad)
            TextField("Notas", text: $notes, axis: .vertical)
                .lineLimit(2...4)
                .modifier(FieldStyle())
                .onChange(of: notes) { _, _ in changed() }
            Button(busy ? "Guardando…" : value.completed ? "Actualizar serie" : "Completar serie") {
                if let candidate { onComplete(candidate) }
            }
            .buttonStyle(PrimaryButtonStyle())
            .disabled(candidate == nil || busy)
            .accessibilityIdentifier("complete_set_\(value.exerciseOrder)_\(value.setNumber)")
            if let planned = value.restSeconds { Muted("Descanso planeado: \(planned) s") }
        }
    }

    private func metric(_ label: String, _ text: Binding<String>, error: String?, keyboard: UIKeyboardType) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption).foregroundStyle(Theme.textMuted)
            TextField(label, text: text)
                .keyboardType(keyboard)
                .modifier(FieldStyle())
                .onChange(of: text.wrappedValue) { _, newValue in
                    let cleaned = DisplayText.decimalDraft(newValue, maxLength: 5)
                    if cleaned != newValue { text.wrappedValue = cleaned }
                    changed()
                }
            if let error { Text(error).font(.caption2).foregroundStyle(Theme.dangerText) }
        }
    }

    private func binding(_ name: String) -> Binding<String> {
        Binding(get: { components[name] ?? "" }, set: { components[name] = DisplayText.decimalDraft($0); changed() })
    }

    private func select(_ candidate: LoadMode) {
        mode = candidate
        for name in candidate.components {
            if components[name] == nil { components[name] = "0" }
            if units[name] == nil { units[name] = name == "duration_seconds" ? "s" : name == "distance_meters" ? "m" : unit }
        }
        changed()
    }

    private func step(_ delta: Decimal) {
        guard let key = mode.components.first(where: { !LoadMode.isMeasure($0) }) else { return }
        let next = max((LoadCalculator.parse(components[key] ?? "") ?? 0) + delta, 0)
        components[key] = LoadCalculator.text(next)
        changed()
    }

    /// Debounced autosave of the valid state (Android `queueSaveLoad`).
    private func changed() {
        if let candidate { model.workout.queueSave(candidate) }
    }
}

private struct SummaryEditor: View {
    @Environment(AppModel.self) private var model
    let draft: WorkoutDraft
    @State private var heartRate = ""
    @State private var calories = ""
    @State private var notes = ""
    @State private var loaded = false

    private var heartRateError: String? {
        guard !heartRate.isEmpty else { return nil }
        guard let value = Int(heartRate) else { return "Usa un número entero." }
        return (20...250).contains(value) ? nil : "Usa un valor entre 20 y 250."
    }
    private var caloriesError: String? { calories.isEmpty || LoadCalculator.parse(calories) != nil ? nil : "Usa un número no negativo." }

    var body: some View {
        Card {
            Text("Resumen opcional").font(.headline)
            HStack(alignment: .top, spacing: Theme.Space.s2) {
                field("FC media", $heartRate, error: heartRateError, keyboard: .numberPad)
                field("Calorías", $calories, error: caloriesError, keyboard: .decimalPad)
            }
            TextField("Notas de la sesión", text: $notes, axis: .vertical)
                .lineLimit(2...5)
                .modifier(FieldStyle())
            Muted("El resumen también se guarda automáticamente.")
        }
        .onAppear {
            guard !loaded else { return }
            heartRate = draft.averageHeartRateBpm.map(String.init) ?? ""
            calories = draft.caloriesBurned ?? ""
            notes = draft.notes ?? ""
            loaded = true
        }
        .onChange(of: heartRate) { _, _ in queue() }
        .onChange(of: calories) { _, _ in queue() }
        .onChange(of: notes) { _, _ in queue() }
    }

    private func field(_ label: String, _ text: Binding<String>, error: String?, keyboard: UIKeyboardType) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption).foregroundStyle(Theme.textMuted)
            TextField(label, text: text).keyboardType(keyboard).modifier(FieldStyle())
            if let error { Text(error).font(.caption2).foregroundStyle(Theme.dangerText) }
        }
    }

    private func queue() {
        guard loaded, heartRateError == nil, caloriesError == nil else { return }
        model.workout.queueSummary(heartRate: Int(heartRate), calories: calories.isEmpty ? nil : calories, notes: String(notes.prefix(5000)))
    }
}

/// Android `IsolatedDraftScreen`: never sent or discarded automatically.
private struct IsolatedDraftView: View {
    @Environment(AppModel.self) private var model
    let reason: String?
    @State private var showReason = false
    @State private var confirmDiscard = false

    var body: some View {
        VStack(spacing: Theme.Space.s3) {
            Text("Borrador aislado").font(.title2.weight(.semibold)).accessibilityAddTraits(.isHeader)
            Text("No se enviará ni descartará automáticamente.")
            if showReason { Text(DisplayText.draftIsolationReason(reason)).foregroundStyle(Theme.dangerText) }
            Button(showReason ? "Ocultar motivo" : "Ver motivo sanitizado") { showReason.toggle() }
                .buttonStyle(SecondaryButtonStyle())
            Button("Descartar borrador") { confirmDiscard = true }
                .buttonStyle(SecondaryButtonStyle(destructive: true))
        }
        .padding(Theme.Space.s5)
        .accessibilityIdentifier("isolated_draft_screen")
        .confirmationDialog("¿Descartar borrador aislado?", isPresented: $confirmDiscard, titleVisibility: .visible) {
            Button("Descartar", role: .destructive) { Task { await model.workout.discardCorrupt() } }
        } message: {
            Text("Se eliminará únicamente este borrador local. No se puede deshacer.")
        }
    }
}
