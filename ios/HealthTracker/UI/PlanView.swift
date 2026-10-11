import HealthTrackerKit
import SwiftUI

/// Android `PlanScreen`: routines and agenda. Editing arrives with the planning editor stage.
struct PlanView: View {
    @Environment(AppModel.self) private var model
    @State private var tab = 0

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
            if tab == 0 { routines } else { agenda }
        }
        .accessibilityIdentifier("plan_screen")
        .navigationTitle("Plan")
        .navigationDestination(for: PlanRoute.self) { PlanDetailView(publicId: $0.id) }
        .navigationDestination(for: PlanWorkoutRoute.self) { PlanWorkoutDetailView(publicId: $0.id) }
        .refreshable { await training.refreshPlans() }
        .task { await training.refreshPlans() }
    }

    @ViewBuilder private var routines: some View {
        Chip(title: training.showArchivedPlans ? "Mostrando archivadas" : "Mostrar archivadas", selected: training.showArchivedPlans) {
            Task { await training.setShowArchivedPlans(!training.showArchivedPlans) }
        }
        Card {
            Text("Próxima programación").font(.headline)
            Text(nextScheduled.map { "\(Formatters.day($0.scheduledForDate)) · \($0.title)" } ?? "Sin entrenamientos próximos")
        }
        if training.plans.isEmpty {
            Text(training.planningRefreshing ? "Buscando rutinas…" : "Aún no hay rutinas en este dispositivo.").foregroundStyle(Theme.textMuted)
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

    @ViewBuilder private var agenda: some View {
        let upcoming = model.planned.filter { $0.scheduledForDate >= todayKey }
        let past = model.planned.filter { $0.scheduledForDate < todayKey }.reversed()
        SectionTitle("Próximos")
        if upcoming.isEmpty { Text("Sin entrenamientos próximos").foregroundStyle(Theme.textMuted) }
        ForEach(upcoming) { agendaRow($0) }
        if !past.isEmpty {
            SectionTitle("Anteriores")
            ForEach(Array(past.prefix(30))) { agendaRow($0) }
        }
    }

    private func agendaRow(_ workout: PlannedWorkout) -> some View {
        Card {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(workout.title).font(.headline)
                    Muted(Formatters.day(workout.scheduledForDate))
                }
                Spacer()
                StatusPill(text: DisplayText.workoutStatus(workout.status), tone: Self.tone(workout.status))
            }
        }
        .accessibilityElement(children: .combine)
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

struct PlanRoute: Hashable { let id: String }
struct PlanWorkoutRoute: Hashable { let id: String }

/// Android `PlanDetailScreen` in read-only form.
struct PlanDetailView: View {
    @Environment(AppModel.self) private var model
    let publicId: String

    var body: some View {
        let training = model.training
        Screen {
            if let plan = training.selectedPlan, plan.publicId == publicId {
                Card {
                    Text(plan.name).font(.title3.weight(.semibold)).accessibilityAddTraits(.isHeader)
                    if let description = plan.description, !description.isEmpty { Text(description) }
                    Muted("Revisión \(plan.revision) · \(DisplayText.planningSync(plan.syncStatus))")
                    if plan.status == "archived" { StatusPill(text: "Archivada", tone: .warning) }
                }
                SectionTitle("Entrenamientos")
                if training.planWorkouts.isEmpty {
                    Text(model.connected ? "Esta rutina aún no tiene entrenamientos." : "Conecta para descargar los entrenamientos de esta rutina.")
                        .foregroundStyle(Theme.textMuted)
                }
                ForEach(training.planWorkouts) { workout in
                    LinkCard(value: PlanWorkoutRoute(id: workout.publicId)) {
                        Text(workout.name).font(.headline)
                        Muted("\(workout.exercises.count) ejercicios\(workout.estimatedDurationSeconds.map { " · ~\($0 / 60) min" } ?? "")")
                    }
                }
            } else {
                Text("Cargando rutina…").foregroundStyle(Theme.textMuted)
            }
        }
        .navigationTitle("Rutina")
        .navigationBarTitleDisplayMode(.inline)
        .task { await training.openPlan(publicId) }
    }
}

/// Exercises and prescribed sets of a plan workout.
struct PlanWorkoutDetailView: View {
    @Environment(AppModel.self) private var model
    let publicId: String

    var body: some View {
        let training = model.training
        Screen {
            if let workout = training.selectedPlanWorkout, workout.publicId == publicId {
                Card {
                    Text(workout.name).font(.title3.weight(.semibold)).accessibilityAddTraits(.isHeader)
                    if let notes = workout.notes, !notes.isEmpty { Text(notes) }
                    Muted(workout.estimatedDurationSeconds.map { "Duración estimada: \(DisplayText.duration($0))" } ?? "Sin duración estimada")
                }
                ForEach(workout.exercises) { exercise in
                    Card {
                        Text("\(exercise.exerciseOrder). \(exercise.name)").font(.headline)
                        if let notes = exercise.notes, !notes.isEmpty { Muted(notes) }
                        ForEach(exercise.sets) { set in
                            Text("Serie \(set.setNumber): \(DisplayText.prescription(set))").font(.subheadline)
                        }
                    }
                    .accessibilityElement(children: .combine)
                }
            } else {
                Text("Cargando entrenamiento…").foregroundStyle(Theme.textMuted)
            }
        }
        .navigationTitle("Entrenamiento")
        .navigationBarTitleDisplayMode(.inline)
        .task { await training.openPlanWorkout(publicId) }
    }
}
