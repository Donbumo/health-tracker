import HealthTrackerKit
import SwiftUI

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()
            switch model.auth {
            case .authenticated:
                HomeView()
            case .authenticating where model.profile == nil && !model.busy:
                LoadingView(text: "Restaurando sesión segura…")
            default:
                LoginView()
            }
            if model.busy {
                Color.black.opacity(0.18).ignoresSafeArea()
                ProgressView().controlSize(.large).tint(Theme.primary)
                    .accessibilityLabel("Procesando")
            }
        }
        .foregroundStyle(Theme.text)
        .overlay(alignment: .bottom) { MessageBanner() }
        .animation(.easeOut(duration: 0.2), value: model.auth)
    }
}

private struct LoadingView: View {
    let text: String

    var body: some View {
        VStack(spacing: Theme.Space.s4) {
            ProgressView().tint(Theme.primary)
            Text(text).foregroundStyle(Theme.textMuted)
        }
        .accessibilityElement(children: .combine)
    }
}

/// Snackbar equivalent: shows `model.message` briefly, then clears it.
private struct MessageBanner: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if let message = model.message {
            Text(message)
                .font(.callout)
                .foregroundStyle(Theme.bg)
                .padding(Theme.Space.s4)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Theme.text)
                .padding(.horizontal, Theme.Space.s4)
                .padding(.bottom, Theme.Space.s6 + Theme.Space.s5)
                .transition(.move(edge: .bottom).combined(with: .opacity))
                .onTapGesture { model.message = nil }
                .task(id: message) {
                    try? await Task.sleep(for: .seconds(4))
                    if model.message == message { model.message = nil }
                }
                .accessibilityAddTraits(.updatesFrequently)
        }
    }
}
