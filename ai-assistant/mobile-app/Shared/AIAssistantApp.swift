import SwiftUI

@main
struct AIAssistantApp: App {
    @StateObject private var networkMonitor = NetworkMonitor()
    @StateObject private var appState = AppState()
    
    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(networkMonitor)
                .environmentObject(appState)
        }
    }
}
