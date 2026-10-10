import HealthTrackerKit
import SwiftUI

/// Android `PlanWorkoutEditor`: name and notes, scheduling, catalog search with multi-select and the
/// exercise/set prescription. The whole workout autosaves 700 ms after the last change and on exit.
struct PlanWorkoutEditorView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.scenePhase) private var scenePhase
    let publicId: String

    @State private var name = ""
    @State private var notes = ""
    @State private var exercises: [PlanExercise] = []
    @State private var loaded = false
    @State private var revision = 0
    @State private var scheduleDate = Date()
    @State private var query = ""
    @State private var selected: Set<String> = []
    @State private var removing: PlanExercise?

    var body: some View {
        let training = model.training
        let planning = model.planning
        Screen {
            if let workout = training.selectedPlanWorkout, workout.publicId == publicId, loaded {
                TextField("Nombre", text: $name).font(.title3.weight(.semibold)).modifier(FieldStyle()).onChange(of: name) { _, _ in edited() }
                TextField("Notas", text: $notes, axis: .vertical).lineLimit(2...4).modifier(FieldStyle()).onChange(of: notes) { _, _ in edited() }
                Muted("Guardado automático · \(DisplayText.planningSync(workout.syncStatus))")

                Card {
                    Text("Programar").font(.headline)
                    DatePicker("Fecha", selection: $scheduleDate, displayedComponents: .date)
                    Button("Programar") { Task { await flush(); await planning.schedule(workoutId: publicId, date: scheduleDate) } }
                        .buttonStyle(PrimaryButtonStyle())
                        .accessibilityIdentifier("schedule_workout")
                }

                SectionTitle("Añadir ejercicios")
                TextField("Buscar catálogo", text: $query)
                    .textInputAutocapitalization(.never)
                    .modifier(FieldStyle())
                    .onChange(of: query) { _, value in planning.searchCatalog(value) }
                    .accessibilityIdentifier("catalog_search")
                Button("Añadir seleccionados (\(selected.count))") { addSelected() }
                    .buttonStyle(PrimaryButtonStyle())
                    .disabled(selected.isEmpty)
                    .accessibilityIdentifier("add_selected")
                if planning.catalog.isEmpty {
                    Muted(model.connected ? (planning.catalogLoading ? "Buscando…" : "Sin resultados en el catálogo.") : "Conecta para buscar en el catálogo.")
                }
                ForEach(planning.catalog) { item in
                    let available = item.selectable && !exercises.contains { $0.exerciseId == item.publicId }
                    Button {
                        if selected.contains(item.publicId) { selected.remove(item.publicId) } else { selected.insert(item.publicId) }
                    } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(item.name)
                                Muted(item.aliases.isEmpty ? "Sin alias" : item.aliases.joined(separator: " · "))
                            }
                            Spacer()
                            Image(systemName: selected.contains(item.publicId) ? "checkmark.square.fill" : "square")
                                .foregroundStyle(available ? Theme.primary : Theme.textMuted)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(!available)
                    .accessibilityIdentifier("catalog_item")
                }
                if planning.catalogHasMore {
                    Button("Cargar más ejercicios") { Task { await planning.loadCatalog(reset: false) } }
                        .buttonStyle(SecondaryButtonStyle())
                }

                SectionTitle("Ejercicios (\(exercises.count))")
                ForEach(Array(exercises.enumerated()), id: \.element.id) { index, exercise in
                    Card {
                        Text(exercise.name).font(.headline)
                        HStack(spacing: Theme.Space.s3) {
                            Button("Subir") { move(index, -1) }.disabled(index == 0)
                            Button("Bajar") { move(index, 1) }.disabled(index == exercises.count - 1)
                            Button("Duplicar") { duplicate(index) }
                            Button("Quitar", role: .destructive) { removing = exercise }
                        }
                        .font(.footnote)
                        ForEach(Array(exercise.sets.enumerated()), id: \.element.id) { setIndex, _ in
                            PlannedSetEditor(set: $exercises[index].sets[setIndex], onChange: edited) {
                                exercises[index].sets.remove(at: setIndex)
                                edited()
                            }
                        }
                        Button("Añadir serie") { addSet(index) }.buttonStyle(SecondaryButtonStyle())
                    }
                }
            } else {
                Text("Cargando entrenamiento…").foregroundStyle(Theme.textMuted)
            }
        }
        .navigationTitle("Editar entrenamiento")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button("Duplicar") {
                    Task {
                        await flush()
                        if let id = await planning.duplicateWorkout(publicId) { await training.openPlanWorkout(id) }
                    }
                }
            }
        }
        .task {
            await training.openPlanWorkout(publicId)
            load()
            planning.searchCatalog(query)
        }
        .task(id: revision) {
            guard revision > 0 else { return }
            try? await Task.sleep(for: .milliseconds(700))
            guard !Task.isCancelled else { return }
            await save()
        }
        .onChange(of: scenePhase) { _, phase in if phase != .active { Task { await flush() } } }
        .onDisappear { Task { await flush() } }
        .confirmationDialog("¿Quitar ejercicio?", isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }), titleVisibility: .visible) {
            Button("Quitar", role: .destructive) {
                if let id = removing?.id { exercises.removeAll { $0.id == id }; edited() }
                removing = nil
            }
        } message: {
            Text("También se quitarán sus prescripciones de esta rutina.")
        }
    }

    private func load() {
        guard let workout = model.training.selectedPlanWorkout, workout.publicId == publicId else { return }
        name = workout.name
        notes = workout.notes ?? ""
        exercises = workout.exercises
        loaded = true
    }

    private func edited() {
        guard loaded else { return }
        revision += 1
    }

    private func save() async {
        await model.planning.saveWorkout(publicId, name: name, notes: notes, exercises: exercises)
    }

    private func flush() async {
        guard loaded, revision > 0 else { return }
        await save()
    }

    private func newId() -> String { UUID().uuidString.lowercased() }

    private func addSelected() {
        let additions = model.planning.catalog.filter { item in
            selected.contains(item.publicId) && item.selectable && !exercises.contains { $0.exerciseId == item.publicId }
        }
        for item in additions {
            let mode = item.preferredLoadMode ?? "direct_total"
            let timed = mode == "duration_distance"
            exercises.append(PlanExercise(id: newId(), exerciseId: item.publicId, name: item.name, notes: nil, exerciseOrder: exercises.count + 1, sets: [
                PlanSet(id: newId(), setNumber: 1, reps: timed ? nil : 8, loadUnit: item.preferredUnit ?? "kg", loadMode: mode,
                        restSeconds: 90, durationSeconds: timed ? 600 : nil),
            ]))
        }
        selected.removeAll()
        edited()
    }

    private func move(_ index: Int, _ delta: Int) {
        let ids = exercises.map(\.id)
        guard let ordered = PlanningRules.reorderedIds(ids, id: exercises[index].id, delta: delta) else { return }
        exercises = ordered.compactMap { id in exercises.first { $0.id == id } }
        edited()
    }

    private func duplicate(_ index: Int) {
        var copy = exercises[index]
        copy.id = newId()
        copy.name = "\(copy.name) (copia)"
        copy.sets = copy.sets.map { var set = $0; set.id = newId(); return set }
        exercises.append(copy)
        edited()
    }

    private func addSet(_ index: Int) {
        if var last = exercises[index].sets.last {
            last.id = newId()
            last.setNumber += 1
            exercises[index].sets.append(last)
        } else {
            exercises[index].sets.append(PlanSet(id: newId(), setNumber: 1, reps: 8, restSeconds: 90))
        }
        edited()
    }
}

/// Android `PlanningSetEditor`: invalid values are shown but never autosaved.
private struct PlannedSetEditor: View {
    @Binding var set: PlanSet
    let onChange: () -> Void
    let onDelete: () -> Void
    @State private var reps = ""
    @State private var load = ""
    @State private var rir = ""
    @State private var rpe = ""
    @State private var rest = ""
    @State private var duration = ""
    @State private var distance = ""
    @State private var notes = ""
    @State private var loaded = false

    private var valid: Bool {
        let timed = Int(duration).map { (1...86_400).contains($0) } == true || LoadCalculator.parse(distance).map { $0 > 0 } == true
        let required = set.loadMode == "duration_distance" ? timed : (Int(reps).map { $0 > 0 } == true || timed)
        return PlanningRules.validPrescription(reps: reps, load: load, rir: rir, rpe: rpe, rest: rest) && required
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Space.s2) {
            HStack {
                Text("Serie \(set.setNumber)").font(.subheadline.weight(.semibold))
                Spacer()
                Button("Eliminar", role: .destructive, action: onDelete).font(.footnote)
            }
            HStack(spacing: Theme.Space.s2) {
                field("Reps", $reps, .numberPad)
                field("Carga \(set.loadUnit)", $load, .decimalPad)
            }
            Menu {
                ForEach(LoadMode.allCases, id: \.self) { mode in
                    Button(DisplayText.loadMode(mode)) { set.loadMode = mode.rawValue; commit() }
                }
            } label: {
                HStack {
                    Text("Modo: \(LoadMode(rawValue: set.loadMode).map(DisplayText.loadMode) ?? set.loadMode)").font(.footnote)
                    Spacer()
                    Image(systemName: "chevron.up.chevron.down").font(.footnote)
                }
                .modifier(FieldStyle())
            }
            HStack(spacing: Theme.Space.s2) {
                field("RIR", $rir, .decimalPad)
                field("RPE", $rpe, .decimalPad)
                field("Descanso s", $rest, .numberPad)
            }
            HStack(spacing: Theme.Space.s2) {
                field("Duración s", $duration, .numberPad)
                field("Distancia m", $distance, .decimalPad)
            }
            TextField("Notas de la serie", text: $notes).modifier(FieldStyle()).onChange(of: notes) { _, _ in commit() }
            Text(valid ? "Objetivo: \(reps.isEmpty ? "libre" : reps) reps · \(load.isEmpty ? "sin carga" : load) \(set.loadUnit)" : "Revisa los valores de la serie.")
                .font(.caption)
                .foregroundStyle(valid ? Theme.textMuted : Theme.dangerText)
        }
        .padding(Theme.Space.s3)
        .background(Theme.surfaceMuted)
        .onAppear {
            guard !loaded else { return }
            reps = set.reps.map(String.init) ?? ""
            load = set.loadValue ?? set.weightKg ?? ""
            rir = set.rir ?? ""
            rpe = set.rpe ?? ""
            rest = set.restSeconds.map(String.init) ?? ""
            duration = set.durationSeconds.map(String.init) ?? ""
            distance = set.distanceMeters ?? ""
            notes = set.notes ?? ""
            loaded = true
        }
    }

    private func field(_ label: String, _ text: Binding<String>, _ keyboard: UIKeyboardType) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption2).foregroundStyle(Theme.textMuted)
            TextField(label, text: text)
                .keyboardType(keyboard)
                .modifier(FieldStyle())
                .onChange(of: text.wrappedValue) { _, value in
                    let cleaned = keyboard == .decimalPad ? DisplayText.decimalDraft(value) : String(value.prefix(6))
                    if cleaned != value { text.wrappedValue = cleaned }
                    commit()
                }
        }
    }

    /// Copies valid values into the bound set and marks the workout as edited.
    private func commit() {
        guard loaded, valid else { return }
        set.reps = Int(reps)
        set.loadValue = load.isEmpty ? nil : load
        if set.loadUnit == "kg" { set.weightKg = load.isEmpty ? nil : load }
        set.rir = rir.isEmpty ? nil : rir
        set.rpe = rpe.isEmpty ? nil : rpe
        set.restSeconds = Int(rest)
        set.durationSeconds = Int(duration)
        set.distanceMeters = distance.isEmpty ? nil : distance
        set.notes = notes.trimmingCharacters(in: .whitespaces).isEmpty ? nil : String(notes.prefix(2000))
        onChange()
    }
}
