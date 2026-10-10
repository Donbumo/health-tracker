import HealthTrackerKit
import SwiftUI

/// Android `PlanScreen`: editable routines, conflicts and the agenda.
struct PlanView: View {
    @Environment(AppModel.self) private var model
    @State private var tab = 0
    @State private var showCreate = false
    @State private var newName = ""

    private var training: TrainingModel { model.training }
    private var todayKey: String { TrainingModel.dayKey(Date()) }
    private var nextScheduled: PlannedWorkout? {
        model.planned.first { $0.scheduledForDate >= todayKey && ["planned", "locally_pending", "syncing"].contains($0.status) }
    }

    var body: some View {
        Screen {
            Picker("Vista", selection: $tab) {
                Text("Rutinas").tag(0)
                Text("Agenda").tag(1)
            }
            .pickerStyle(.segmented)
            Muted(model.connected ? "Sincronizado con tu servidor" : "Disponible sin conexión")
            if !model.planning.conflicts.isEmpty { ConflictsCard() }
            if tab == 0 { routines } else { AgendaView() }
        }
        .accessibilityIdentifier("plan_screen")
        .navigationTitle("Plan")
        .navigationDestination(for: PlanRoute.self) { PlanDetailView(publicId: $0.id) }
        .navigationDestination(for: PlanWorkoutRoute.self) { PlanWorkoutEditorView(publicId: $0.id) }
        .refreshable {
            await training.refreshPlans()
            await model.planning.refreshSchedule()
        }
        .task {
            await training.refreshPlans()
            await model.planning.refreshSchedule()
        }
        .alert("Nueva rutina", isPresented: $showCreate) {
            TextField("Nombre", text: $newName).accessibilityIdentifier("new_plan_name")
            Button("Crear") {
                let name = String(newName.prefix(120))
                newName = ""
                Task {
                    if let id = await model.planning.createPlan(name: name) {
                        await training.openPlan(id)
                    }
                }
            }
            Button("Cancelar", role: .cancel) { newName = "" }
        }
    }

    @ViewBuilder private var routines: some View {
        Button("Crear rutina") { showCreate = true }
            .buttonStyle(PrimaryButtonStyle())
            .accessibilityIdentifier("create_plan")
        Chip(title: training.showArchivedPlans ? "Mostrando archivadas" : "Mostrar archivadas", selected: training.showArchivedPlans) {
            Task { await training.setShowArchivedPlans(!training.showArchivedPlans) }
        }
        Card {
            Text("Próxima programación").font(.headline)
            Text(nextScheduled.map { "\(Formatters.day($0.scheduledForDate)) · \($0.title)" } ?? "Sin entrenamientos próximos")
        }
        if training.plans.isEmpty {
            Text(training.planningRefreshing ? "Buscando rutinas…" : "Aún no hay rutinas. Crea una incluso sin conexión; se sincronizará después.")
                .foregroundStyle(Theme.textMuted)
        }
        ForEach(training.plans) { plan in
            LinkCard(value: PlanRoute(id: plan.publicId)) {
                HStack {
                    Text(plan.name).font(.headline)
                    if plan.status == "archived" { StatusPill(text: "Archivada", tone: .warning) }
                }
                if let description = plan.description, !description.isEmpty { Text(description).lineLimit(2) }
                Muted("\(plan.workoutCount) entrenamientos · revisión \(plan.revision) · \(DisplayText.planningSync(plan.syncStatus))")
            }
            .accessibilityIdentifier("plan_row")
        }
    }
}

struct PlanRoute: Hashable { let id: String }
struct PlanWorkoutRoute: Hashable { let id: String }

/// Conflicts that block the queue, with the three resolutions (Android planning conflicts card).
private struct ConflictsCard: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Space.s2) {
            Text("Cambios que requieren atención").font(.headline).foregroundStyle(Theme.dangerText)
            ForEach(model.planning.conflicts) { conflict in
                VStack(alignment: .leading, spacing: Theme.Space.s1) {
                    Text("Local: \(conflict.localName ?? conflict.entityType) · revisión \(conflict.localRevision)")
                    Muted("Servidor: \(conflict.remoteName ?? "no disponible")\(conflict.serverRevision.map { " · revisión \($0)" } ?? "")")
                    Muted(DisplayText.planningConflict(conflict.changedFields))
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: Theme.Space.s2) {
                            Button("Usar servidor") { Task { await model.planning.keepRemote(conflict.entityId) } }
                            if conflict.changedFields != "remote_deleted" {
                                Button("Reintentar copia local") { Task { await model.planning.retry(conflict.entityId) } }
                            }
                            if ["plan", "workout"].contains(conflict.entityType) {
                                Button("Duplicar copia local") { Task { await model.planning.duplicateConflict(conflict.entityId) } }
                            }
                        }
                        .buttonStyle(.bordered)
                        .disabled(!model.connected)
                    }
                }
                .padding(.vertical, Theme.Space.s1)
            }
        }
        .padding(Theme.Space.s4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.dangerBg)
        .accessibilityIdentifier("planning_conflicts")
    }
}

/// Week or month agenda with reschedule and cancel (Android `PlanningCalendarAgenda`).
private struct AgendaView: View {
    @Environment(AppModel.self) private var model
    @State private var month = false
    @State private var anchor = TrainingModel.dayKey(Date())
    @State private var rescheduling: PlannedWorkout?
    @State private var newDate = Date()
    @State private var cancelling: PlannedWorkout?

    var body: some View {
        let range = PlanningRules.dateRange(anchor: anchor, month: month)
        let items = model.planned.filter { range?.contains($0.scheduledForDate) == true }
        Picker("Periodo", selection: $month) {
            Text("Semana").tag(false)
            Text("Mes").tag(true)
        }
        .pickerStyle(.segmented)
        HStack {
            Button { anchor = PlanningRules.shiftedAnchor(anchor, month: month, delta: -1) } label: { Image(systemName: "chevron.left") }
                .accessibilityLabel("Periodo anterior")
            Spacer()
            Text(range.map { "\(Formatters.day($0.lowerBound)) – \(Formatters.day($0.upperBound))" } ?? "").font(.subheadline.weight(.semibold))
            Spacer()
            Button { anchor = PlanningRules.shiftedAnchor(anchor, month: month, delta: 1) } label: { Image(systemName: "chevron.right") }
                .accessibilityLabel("Periodo siguiente")
        }
        .padding(.vertical, Theme.Space.s1)
        if month { MonthGrid(anchor: anchor, scheduledDays: Set(items.filter { $0.status != "cancelled" }.map(\.scheduledForDate))) }
        Button("Hoy") { anchor = TrainingModel.dayKey(Date()) }.font(.footnote.weight(.semibold))
        if items.isEmpty { Text("Sin entrenamientos en este periodo.").foregroundStyle(Theme.textMuted) }
        ForEach(items) { workout in
            Card {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(workout.title).font(.headline)
                        Muted(Formatters.day(workout.scheduledForDate))
                    }
                    Spacer()
                    StatusPill(text: DisplayText.workoutStatus(workout.status), tone: Self.tone(workout.status))
                }
                if ["planned", "locally_pending"].contains(workout.status) {
                    HStack(spacing: Theme.Space.s2) {
                        Button("Reprogramar") {
                            newDate = PlanningRules.parse(workout.scheduledForDate).map(Self.localDate) ?? Date()
                            rescheduling = workout
                        }
                        Button("Cancelar", role: .destructive) { cancelling = workout }
                    }
                    .buttonStyle(.bordered)
                }
            }
            .accessibilityIdentifier("agenda_row")
        }
        .sheet(item: $rescheduling) { workout in
            NavigationStack {
                Form {
                    DatePicker("Nueva fecha", selection: $newDate, displayedComponents: .date)
                        .datePickerStyle(.graphical)
                }
                .navigationTitle(workout.title)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("Cerrar") { rescheduling = nil } }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Guardar") {
                            let id = workout.id
                            let date = newDate
                            rescheduling = nil
                            Task { await model.planning.reschedule(id, date: date) }
                        }
                    }
                }
            }
            .presentationDetents([.large])
        }
        .confirmationDialog("¿Cancelar programación?", isPresented: Binding(get: { cancelling != nil }, set: { if !$0 { cancelling = nil } }), titleVisibility: .visible) {
            Button("Cancelar programación", role: .destructive) {
                if let id = cancelling?.id { Task { await model.planning.cancelSchedule(id) } }
                cancelling = nil
            }
        }
    }

    /// A stored calendar day at local noon, so the picker shows the same day in any zone.
    static func localDate(_ utcDay: Date) -> Date {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let parts = calendar.dateComponents([.year, .month, .day], from: utcDay)
        var local = DateComponents(year: parts.year, month: parts.month, day: parts.day, hour: 12)
        local.calendar = Calendar(identifier: .gregorian)
        return local.date ?? utcDay
    }

    static func tone(_ status: String) -> StatusPill.Tone {
        switch status {
        case "completed": .success
        case "conflict": .danger
        case "cancelled", "locally_pending", "syncing": .warning
        default: .info
        }
    }
}

private struct MonthGrid: View {
    let anchor: String
    let scheduledDays: Set<String>
    private let columns = Array(repeating: GridItem(.flexible(), spacing: 2), count: 7)

    var body: some View {
        let month = String(anchor.prefix(7))
        LazyVGrid(columns: columns, spacing: 2) {
            ForEach(["L", "M", "X", "J", "V", "S", "D"], id: \.self) { Text($0).font(.caption2).foregroundStyle(Theme.textMuted) }
            ForEach(PlanningRules.monthGrid(anchor: anchor), id: \.self) { day in
                VStack(spacing: 2) {
                    Text(String(Int(day.suffix(2)) ?? 0))
                        .font(.footnote)
                        .foregroundStyle(day.hasPrefix(month) ? Theme.text : Theme.textMuted)
                    Circle().fill(scheduledDays.contains(day) ? Theme.primary : .clear).frame(width: 5, height: 5)
                }
                .frame(maxWidth: .infinity, minHeight: 34)
                .background(day == TrainingModel.dayKey(Date()) ? Theme.primarySoft : .clear)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(Formatters.day(day))\(scheduledDays.contains(day) ? ", con entrenamiento" : "")")
            }
        }
    }
}

/// Android `PlanDetailScreen`: autosaved name and description, workouts and plan actions.
struct PlanDetailView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let publicId: String
    @State private var name = ""
    @State private var description = ""
    @State private var loadedId: String?
    @State private var showCreate = false
    @State private var workoutName = ""
    @State private var confirmArchive = false

    var body: some View {
        let training = model.training
        Screen {
            if let plan = training.selectedPlan, plan.publicId == publicId {
                TextField("Nombre", text: $name).font(.title3.weight(.semibold)).modifier(FieldStyle())
                    .accessibilityIdentifier("plan_name_field")
                TextField("Descripción", text: $description, axis: .vertical).lineLimit(2...5).modifier(FieldStyle())
                Muted("Guardado automático · \(DisplayText.planningSync(plan.syncStatus)) · revisión \(plan.revision)")
                HStack(spacing: Theme.Space.s2) {
                    Button("Añadir entrenamiento") { showCreate = true }
                        .buttonStyle(PrimaryButtonStyle())
                        .disabled(plan.status != "active")
                        .accessibilityIdentifier("add_workout")
                    Button("Duplicar rutina") {
                        Task { if let id = await model.planning.duplicatePlan(plan) { await training.openPlan(id) } }
                    }
                    .buttonStyle(SecondaryButtonStyle())
                }
                SectionTitle("Entrenamientos")
                if training.planWorkouts.isEmpty {
                    Text("Esta rutina aún no tiene entrenamientos.").foregroundStyle(Theme.textMuted)
                }
                ForEach(training.planWorkouts) { workout in
                    VStack(spacing: 0) {
                        LinkCard(value: PlanWorkoutRoute(id: workout.publicId)) {
                            Text(workout.name).font(.headline)
                            Muted("\(workout.exercises.count) ejercicios\(workout.estimatedDurationSeconds.map { " · ~\($0 / 60) min" } ?? "") · \(DisplayText.planningSync(workout.syncStatus))")
                        }
                        .accessibilityIdentifier("plan_workout_row")
                        HStack {
                            Button("Subir") { Task { await model.planning.moveWorkout(planId: publicId, workoutId: workout.publicId, delta: -1) } }
                                .disabled(workout.position <= 1)
                            Button("Bajar") { Task { await model.planning.moveWorkout(planId: publicId, workoutId: workout.publicId, delta: 1) } }
                                .disabled(workout.position >= training.planWorkouts.count)
                            Spacer()
                        }
                        .font(.footnote)
                        .padding(.vertical, Theme.Space.s1)
                    }
                }
                if plan.status == "archived" {
                    Button("Restaurar rutina") { Task { await model.planning.restore(plan) } }.buttonStyle(SecondaryButtonStyle())
                } else {
                    Button("Archivar rutina") { confirmArchive = true }.buttonStyle(SecondaryButtonStyle(destructive: true))
                }
            } else {
                Text("Cargando rutina…").foregroundStyle(Theme.textMuted)
            }
        }
        .navigationTitle("Rutina")
        .navigationBarTitleDisplayMode(.inline)
        .task { await training.openPlan(publicId) }
        .onChange(of: training.selectedPlan) { _, plan in load(plan) }
        .onAppear { load(training.selectedPlan) }
        .task(id: "\(name)|\(description)") {
            guard loadedId == publicId, let plan = training.selectedPlan, plan.publicId == publicId else { return }
            try? await Task.sleep(for: .milliseconds(700))
            guard !Task.isCancelled else { return }
            await model.planning.editPlan(plan, name: name, description: description)
        }
        .onDisappear {
            if let plan = training.selectedPlan, plan.publicId == publicId {
                let (name, description) = (name, description)
                Task { await model.planning.editPlan(plan, name: name, description: description) }
            }
        }
        .alert("Nuevo entrenamiento", isPresented: $showCreate) {
            TextField("Nombre", text: $workoutName).accessibilityIdentifier("new_workout_name")
            Button("Crear") {
                let value = String(workoutName.prefix(120))
                workoutName = ""
                Task { _ = await model.planning.createWorkout(planId: publicId, name: value) }
            }
            Button("Cancelar", role: .cancel) { workoutName = "" }
        }
        .confirmationDialog("¿Archivar rutina?", isPresented: $confirmArchive, titleVisibility: .visible) {
            Button("Archivar", role: .destructive) {
                guard let plan = training.selectedPlan else { return }
                Task { if await model.planning.archive(plan, planned: model.planned) { dismiss() } }
            }
        } message: {
            Text("Se ocultará de la lista activa. Para proteger la agenda, primero debes cancelar sus programaciones activas.")
        }
    }

    private func load(_ plan: TrainingPlan?) {
        guard let plan, plan.publicId == publicId, loadedId != publicId else { return }
        name = plan.name
        description = plan.description ?? ""
        loadedId = publicId
    }
}
