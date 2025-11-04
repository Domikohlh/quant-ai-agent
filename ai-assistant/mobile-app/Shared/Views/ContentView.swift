import SwiftUI

struct ContentView: View {
    @EnvironmentObject var networkMonitor: NetworkMonitor
    @EnvironmentObject var appState: AppState
    
    var body: some View {
        TabView(selection: $appState.selectedTab) {
            ChatView()
                .tabItem {
                    Label("Chat", systemImage: "message.fill")
                }
                .tag(0)
            
            TasksView()
                .tabItem {
                    Label("Tasks", systemImage: "checklist")
                }
                .tag(1)
            
            StocksView()
                .tabItem {
                    Label("Stocks", systemImage: "chart.line.uptrend.xyaxis")
                }
                .tag(2)
            
            DocumentsView()
                .tabItem {
                    Label("Documents", systemImage: "doc.fill")
                }
                .tag(3)
            
            SettingsView()
                .tabItem {
                    Label("Settings", systemImage: "gear")
                }
                .tag(4)
        }
        .overlay(alignment: .top) {
            if !networkMonitor.isConnected {
                OfflineBanner()
            }
        }
    }
}

struct OfflineBanner: View {
    var body: some View {
        HStack {
            Image(systemName: "wifi.slash")
            Text("Offline Mode")
            Spacer()
        }
        .padding()
        .background(Color.orange)
        .foregroundColor(.white)
    }
}

// MARK: - Preview
#Preview("Normal") {
    ContentView()
        .environmentObject(NetworkMonitor())
        .environmentObject(AppState())
}

#Preview("Offline") {
    let networkMonitor = NetworkMonitor()
    networkMonitor.isConnected = false
    
    return ContentView()
        .environmentObject(networkMonitor)
        .environmentObject(AppState())
}
