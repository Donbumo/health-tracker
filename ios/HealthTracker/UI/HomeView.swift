import HealthTrackerKit
import SwiftUI

struct HomeView: View {
    var body: some View {
        TabView {
            NavigationStack { TodayView() }
                .tabItem { Label("Hoy", systemImage: "sun.max") }
            NavigationStack { PlanView() }
                .tabItem { Label("Plan", systemImage: "list.bullet.rectangle") }
            NavigationStack { HistoryView() }
                .tabItem { Label("Historial", systemImage: "clock.arrow.circlepath") }
            NavigationStack { TrainingProgressView() }
                .tabItem { Label("Progreso", systemImage: "chart.line.uptrend.xyaxis") }
            NavigationStack { SettingsView() }
                .tabItem { Label("Ajustes", systemImage: "gearshape") }
        }
        .tint(Theme.primary)
    }
}

private struct TodayView: View {
    @Environment(AppModel.self) private var model

    private var todayKey: String { Formatters.dayKey(Date()) }
    private var todayWorkout: PlannedWorkout? {
        let today = model.planned.filter { $0.scheduledForDate == todayKey }
        return today.first { !["cancelled", "completed"].contains($0.status) } ?? today.first
    }
    private var upcoming: [PlannedWorkout] { Array(model.planned.filter { $0.scheduledForDate > todayKey }.prefix(7)) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Space.s4) {
                SyncBanner()
                if let draft = model.workout.draft { DraftCard(draft: draft) }
                Card {
                    Text("Entrenamiento de hoy").font(.headline)
                    if let workout = todayWorkout {
                        Text(workout.title).font(.title3.weight(.semibold))
                        HStack {
                            StatusPill(text: DisplayText.workoutStatus(displayStatus(workout)), tone: workout.status == "conflict" ? .danger : .info)
                            Spacer()
                        }
                        WorkoutActions(workout: workout)
                    } else {
                        Text(model.syncSnapshot.hasSyncState ? "No hay entrenamiento programado para hoy." : "Sincroniza para descargar tu agenda.")
                            .foregroundStyle(Theme.textMuted)
                    }
                }
                .accessibilityIdentifier("today_card")

                if !upcoming.isEmpty {
                    section("Próximos") {
                        ForEach(upcoming) { workout in
                            row(title: workout.title, detail: Formatters.day(workout.scheduledForDate), trailing: DisplayText.workoutStatus(displayStatus(workout)))
                            WorkoutActions(workout: workout)
                        }
                    }
                }

                section("Recientes") {
                    if model.recent.isEmpty {
                        Text("Aún no hay entrenamientos completados en este dispositivo.").foregroundStyle(Theme.textMuted)
                    }
                    ForEach(model.recent) { session in
                        row(
                            title: session.summary.isEmpty ? session.title : session.summary,
                            detail: "\(Formatters.instant(session.completedAt)) · \(session.setCount) series",
                            trailing: "\(session.totalLoadKg) kg"
                        )
                    }
                }
            }
            .padding(Theme.Space.s4)
        }
        .refreshable { model.syncNow() }
        .background(Theme.bg)
        .navigationTitle("Hoy")
        .fullScreenCover(isPresented: Binding(get: { model.workout.presented }, set: { model.workout.presented = $0 })) {
            WorkoutView()
        }
    }

    private func displayStatus(_ workout: PlannedWorkout) -> String {
        if let package = model.workout.package(forPlanned: workout.id) {
            if model.workout.draft?.deliveryId == package.deliveryId { return "active" }
            if workout.status == "planned" { return "downloaded" }
        }
        return workout.status
    }

    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.s2) {
            Text(title).font(.title3.weight(.semibold)).accessibilityAddTraits(.isHeader)
            Card { content() }
        }
    }

    private func row(title: String, detail: String, trailing: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).lineLimit(2)
                Text(detail).font(.footnote).foregroundStyle(Theme.textMuted)
            }
            Spacer()
            Text(trailing).font(.footnote.weight(.medium)).foregroundStyle(Theme.textMuted)
        }
        .padding(.vertical, Theme.Space.s1)
        .accessibilityElement(children: .combine)
    }
}

/// Connection, sync and session status in one line.
struct SyncBanner: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        HStack(spacing: Theme.Space.s2) {
            StatusPill(text: label, tone: tone).accessibilityIdentifier("sync_status")
            if model.syncSnapshot.pendingCount > 0 {
                Text("\(model.syncSnapshot.pendingCount) pendientes").font(.footnote).foregroundStyle(Theme.textMuted)
            }
            Spacer()
            Text(model.profile?.email ?? "").font(.footnote).foregroundStyle(Theme.textMuted).lineLimit(1)
        }
    }

    private var label: String {
        if !model.connected { return "Sin red" }
        if model.profile?.role == "offline_cache" { return "Offline" }
        switch model.syncStatus {
        case .syncing: return "Sincronizando…"
        case .pending: return "Pendiente"
        case .conflict: return "Requiere atención"
        case .error: return "Error de sync"
        case .idle: return model.syncSnapshot.hasSyncState ? "Sincronizado" : "Conectado"
        }
    }

    private var tone: StatusPill.Tone {
        if !model.connected || model.profile?.role == "offline_cache" { return .warning }
        switch model.syncStatus {
        case .syncing: return .info
        case .pending: return .warning
        case .conflict, .error: return .danger
        case .idle: return .success
        }
    }
}

enum Formatters {
    static func dayKey(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }

    static func day(_ key: String) -> String {
        let parser = DateFormatter()
        parser.locale = Locale(identifier: "en_US_POSIX")
        parser.dateFormat = "yyyy-MM-dd"
        guard let date = parser.date(from: key) else { return key }
        return date.formatted(.dateTime.weekday(.wide).day().month(.abbreviated).locale(Locale(identifier: "es")))
    }

    static func instant(_ iso: String?) -> String {
        guard let iso else { return "Nunca" }
        let parser = ISO8601DateFormatter()
        guard let date = parser.date(from: iso) else { return iso }
        return date.formatted(.dateTime.day().month(.abbreviated).hour().minute().locale(Locale(identifier: "es")))
    }

    static func plannedStatus(_ status: String) -> String {
        switch status {
        case "planned", "scheduled": "Programado"
        case "completed": "Completado"
        case "cancelled": "Cancelado"
        case "conflict": "Conflicto"
        case "locally_pending", "syncing": "Pendiente"
        default: status.capitalized
        }
    }
}
