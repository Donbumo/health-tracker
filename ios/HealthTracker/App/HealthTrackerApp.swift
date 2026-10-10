import SwiftUI

@main
struct HealthTrackerApp: App {
    @State private var model: AppModel
    @Environment(\.scenePhase) private var scenePhase

    init() {
        let model = AppModel.live()
        _model = State(initialValue: model)
        SyncCoordinator.registerBackgroundTask { [weak model] in model?.sync }
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .preferredColorScheme(Theme.colorScheme(model.preferences.theme))
                .task { await model.start() }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { model.appBecameActive() }
        }
    }
}
