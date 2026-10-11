import HealthTrackerKit
import SwiftUI

struct HomeView: View {
    var body: some View {
        TabView {
            NavigationStack { TodayView() }
                .tabItem { Label("Hoy", systemImage: "sun.max") }
            NavigationStack { SettingsView() }
                .tabItem { Label("Ajustes", systemImage: "gearshape") }
        }
        .tint(Theme.primary)
    }
}

private struct TodayView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Space.s4) {
                Card {
                    HStack {
                        Text("Sesión").font(.headline)
                        Spacer()
                        if model.profile?.role == "offline_cache" {
                            StatusPill(text: "Offline", tone: .warning)
                        } else {
                            StatusPill(text: model.connected ? "Conectado" : "Sin red", tone: model.connected ? .success : .warning)
                        }
                    }
                    Text(model.profile?.email ?? "Sin sesión")
                    Text(model.preferences.serverURL ?? "Sin servidor")
                        .font(.footnote)
                        .foregroundStyle(Theme.textMuted)
                        .textSelection(.enabled)
                }
                Card {
                    Text("Entrenamientos del día").font(.headline)
                    Text("La sincronización offline y el plan de hoy llegan en la siguiente etapa del companion iOS.")
                        .foregroundStyle(Theme.textMuted)
                }
            }
            .padding(Theme.Space.s4)
        }
        .background(Theme.bg)
        .navigationTitle("Hoy")
    }
}
