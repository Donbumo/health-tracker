import HealthTrackerKit
import SwiftUI
import UIKit

struct LoginView: View {
    @Environment(AppModel.self) private var model
    @State private var server = ""
    @State private var localHTTP = false
    @State private var email = ""
    @State private var password = ""
    @State private var deviceName = String(UIDevice.current.name.prefix(120))
    @FocusState private var focus: Field?

    private enum Field { case server, email, password, device }

    private var canSubmit: Bool {
        !server.trimmingCharacters(in: .whitespaces).isEmpty && !email.trimmingCharacters(in: .whitespaces).isEmpty &&
            !password.isEmpty && !deviceName.trimmingCharacters(in: .whitespaces).isEmpty
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Space.s4) {
                header
                labeled("URL del servidor") {
                    TextField("https://tracker.example.local", text: $server)
                        .textContentType(.URL)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .focused($focus, equals: .server)
                        .submitLabel(.next)
                        .onSubmit { focus = .email }
                        .modifier(FieldStyle())
                        .accessibilityLabel("URL base del servidor")
                        .accessibilityIdentifier("server_field")
                }
                if ServerURLValidator.buildAllowsLocalHTTP {
                    Toggle(isOn: $localHTTP) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Permitir HTTP local en debug")
                            Text("Solo loopback, simulador, RFC1918 o .local").font(.footnote).foregroundStyle(Theme.textMuted)
                        }
                    }
                    .tint(Theme.primary)
                    .accessibilityIdentifier("local_http_toggle")
                }
                Button("Probar conexión") { model.testServer(url: server, localHTTP: localHTTP) }
                    .buttonStyle(SecondaryButtonStyle())
                    .disabled(server.trimmingCharacters(in: .whitespaces).isEmpty)

                Divider().overlay(Theme.border).padding(.vertical, Theme.Space.s2)

                labeled("Usuario o email") {
                    TextField("", text: $email)
                        .textContentType(.username)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .focused($focus, equals: .email)
                        .submitLabel(.next)
                        .onSubmit { focus = .password }
                        .modifier(FieldStyle())
                        .accessibilityIdentifier("email_field")
                }
                labeled("Contraseña") {
                    SecureField("", text: $password)
                        .textContentType(.password)
                        .focused($focus, equals: .password)
                        .submitLabel(.next)
                        .onSubmit { focus = .device }
                        .modifier(FieldStyle())
                        .accessibilityIdentifier("password_field")
                }
                labeled("Nombre del dispositivo") {
                    TextField("", text: $deviceName)
                        .focused($focus, equals: .device)
                        .submitLabel(.go)
                        .onSubmit(submit)
                        .onChange(of: deviceName) { _, value in
                            if value.count > 120 { deviceName = String(value.prefix(120)) }
                        }
                        .modifier(FieldStyle())
                }
                Button("Iniciar sesión", action: submit)
                    .buttonStyle(PrimaryButtonStyle())
                    .disabled(!canSubmit)
                    .accessibilityIdentifier("login_button")
                Text("La contraseña solo se usa para el login. El refresh token se guarda en el llavero de iOS (solo este dispositivo); nunca en ajustes ni caché.")
                    .font(.footnote)
                    .foregroundStyle(Theme.textMuted)
            }
            .padding(.horizontal, Theme.Space.s5)
            .padding(.vertical, Theme.Space.s6)
        }
        .scrollDismissesKeyboard(.interactively)
        .onAppear {
            if server.isEmpty { server = model.preferences.serverURL ?? "" }
            if ServerURLValidator.buildAllowsLocalHTTP, model.preferences.allowLocalHTTP { localHTTP = true }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Theme.Space.s2) {
            Text("Health Tracker")
                .font(.largeTitle.weight(.bold))
                .accessibilityAddTraits(.isHeader)
            Text("iOS Companion \(AppModel.appVersion)")
                .font(.headline)
                .foregroundStyle(Theme.textMuted)
            Text(statusText)
                .padding(.top, Theme.Space.s2)
        }
        .padding(.bottom, Theme.Space.s2)
    }

    private var statusText: String {
        switch model.auth {
        case .deviceRevoked: "Este dispositivo fue revocado. Inicia sesión para registrarlo nuevamente."
        case .serverIncompatible: "El servidor no ofrece un contrato iOS compatible. Revisa su versión."
        case .tokenExpired: "La sesión venció. Inicia sesión nuevamente."
        case .offline: "No se pudo alcanzar el servidor. Revisa la red y vuelve a intentar."
        default: "Configura tu servidor privado y entra con tu cuenta."
        }
    }

    private func submit() {
        guard canSubmit else { return }
        focus = nil
        model.login(url: server, localHTTP: localHTTP, email: email, password: password, deviceName: deviceName)
    }

    private func labeled<Content: View>(_ label: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.s1) {
            Text(label).font(.subheadline.weight(.medium)).foregroundStyle(Theme.textMuted)
            content()
        }
    }
}
