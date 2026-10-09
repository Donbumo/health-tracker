import HealthTrackerKit
import SwiftUI

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var pending: SessionAction?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Space.s3) {
                info("Servidor", model.preferences.serverURL ?? "Sin configurar")
                info("Usuario", model.profile?.email ?? "Sin sesión")
                info("Dispositivo", "iOS \(deviceLabel) · \(model.connected ? "con red" : "offline")")
                info("Versión", "App \(AppModel.appVersion) (\(AppModel.buildNumber)) · API 1 · Sync 1.0 · Companion 1.0")

                Card {
                    Text("Apariencia").font(.headline)
                    Picker("Tema", selection: Binding(get: { model.preferences.theme }, set: { model.setTheme($0) })) {
                        ForEach(ThemePreference.allCases, id: \.self) { Text(label(for: $0)).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    Text("Unidades").font(.subheadline).foregroundStyle(Theme.textMuted).padding(.top, Theme.Space.s2)
                    Picker("Unidades", selection: Binding(get: { model.preferences.unit }, set: { model.setUnit($0) })) {
                        Text("kg").tag(UnitPreference.kg)
                        Text("lb").tag(UnitPreference.lb)
                    }
                    .pickerStyle(.segmented)
                }

                VStack(alignment: .leading, spacing: Theme.Space.s1) {
                    Text("Sesiones y datos locales").font(.title3.weight(.semibold))
                    Text("Cerrar sesión elimina esta cuenta del teléfono. Cerrar todas revoca todas las sesiones API. Revocar bloquea este dispositivo. Borrar local no cambia el servidor.")
                        .font(.callout)
                        .foregroundStyle(Theme.textMuted)
                }
                .padding(.top, Theme.Space.s3)

                ForEach(SessionAction.allCases) { action in
                    Button(action.button) { pending = action }
                        .buttonStyle(SecondaryButtonStyle(destructive: action.destructive))
                }
            }
            .padding(Theme.Space.s4)
            .padding(.bottom, Theme.Space.s6)
        }
        .background(Theme.bg)
        .navigationTitle("Ajustes")
        .sheet(item: $pending) { action in
            ConfirmationSheet(action: action) {
                pending = nil
                run(action)
            }
            .presentationDetents([.medium])
        }
    }

    private var deviceLabel: String {
        let id = model.preferences.deviceId
        return id.isEmpty ? "Sin identificar" : "\(id.prefix(8))…"
    }

    private func info(_ title: String, _ value: String) -> some View {
        Card {
            Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.textMuted)
            Text(value).textSelection(.enabled)
        }
    }

    private func label(for theme: ThemePreference) -> String {
        switch theme {
        case .system: "Sistema"
        case .light: "Claro"
        case .dark: "Oscuro"
        }
    }

    private func run(_ action: SessionAction) {
        switch action {
        case .switchServer: model.switchServer()
        case .logout: model.logout()
        case .logoutAll: model.logoutAll()
        case .revoke: model.logout(revoke: true)
        case .clear: model.logout(localOnly: true)
        }
    }
}

enum SessionAction: String, CaseIterable, Identifiable {
    case switchServer, logout, logoutAll, revoke, clear

    var id: String { rawValue }

    var button: String {
        switch self {
        case .switchServer: "Cambiar servidor"
        case .logout: "Cerrar sesión en este teléfono"
        case .logoutAll: "Cerrar todas las sesiones API"
        case .revoke: "Revocar este dispositivo"
        case .clear: "Borrar solo datos locales"
        }
    }

    var title: String {
        switch self {
        case .switchServer: "¿Cambiar de servidor?"
        case .revoke: "¿Revocar dispositivo?"
        case .clear: "¿Borrar datos locales?"
        case .logoutAll: "¿Cerrar todas las sesiones?"
        case .logout: "¿Cerrar sesión?"
        }
    }

    var detail: String {
        switch self {
        case .switchServer: "Se cerrará la sesión activa y se invalidarán sus tokens locales. Los datos locales se conservarán bajo su servidor y cuenta actuales; después deberás confirmar la nueva URL e iniciar sesión."
        case .clear: "Se borrarán cache, drafts y pendientes de esta cuenta. Esta acción no se puede deshacer."
        case .revoke: "El servidor revocará sesiones del dispositivo y se borrarán sus datos locales."
        case .logoutAll: "El servidor revocará todas tus sesiones API. Esta operación requiere red."
        case .logout: "Los drafts y datos locales de esta cuenta se borrarán por privacidad."
        }
    }

    var requiresAcknowledgement: Bool { self != .logout }
    var destructive: Bool { [.clear, .revoke, .logoutAll].contains(self) }
}

private struct ConfirmationSheet: View {
    let action: SessionAction
    let confirm: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var acknowledged = false

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Space.s4) {
            Text(action.title).font(.title2.weight(.bold))
            Text(action.detail).foregroundStyle(Theme.textMuted)
            if action.requiresAcknowledgement {
                Toggle("Entiendo el alcance de esta acción", isOn: $acknowledged).tint(Theme.primary)
            }
            Spacer()
            Button("Confirmar", action: confirm)
                .buttonStyle(PrimaryButtonStyle(destructive: action.destructive))
                .disabled(action.requiresAcknowledgement && !acknowledged)
            Button("Cancelar") { dismiss() }
                .buttonStyle(SecondaryButtonStyle())
        }
        .padding(Theme.Space.s5)
        .background(Theme.bg)
    }
}
