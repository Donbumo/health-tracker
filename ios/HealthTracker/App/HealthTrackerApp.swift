import SwiftUI

@main
struct HealthTrackerApp: App {
    @State private var model = AppModel.live()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .preferredColorScheme(Theme.colorScheme(model.preferences.theme))
                .task { await model.start() }
        }
    }
}
