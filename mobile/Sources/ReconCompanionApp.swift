import SwiftUI

@main
struct ReconCompanionApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
                .preferredColorScheme(.light)   // tactical light mode, system-independent
        }
    }
}
