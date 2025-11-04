import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var networkMonitor: NetworkMonitor
    
    var body: some View {
        NavigationView {
            Form {
                Section("AI Settings") {
                    Toggle("Use RAG for Context", isOn: $appState.useRAG)
                    
                    HStack {
                        Text("Connection Status")
                        Spacer()
                        Text(networkMonitor.isConnected ? "Online" : "Offline")
                            .foregroundColor(networkMonitor.isConnected ? .green : .orange)
                    }
                }
                
                Section("Stock Settings") {
                    NavigationLink("Manage Watchlist") {
                        WatchlistSettingsView()
                    }
                }
                
                Section("Data") {
                    Button("Clear Chat History") {
                        appState.messages.removeAll()
                    }
                    
                    Button("Clear Tasks") {
                        appState.dailyTasks.removeAll()
                    }
                    
                    Button(role: .destructive, action: {}) {
                        Text("Clear All Data")
                    }
                }
                
                Section("About") {
                    HStack {
                        Text("Version")
                        Spacer()
                        Text("1.0.0")
                            .foregroundColor(.secondary)
                    }
                }
            }
            .navigationTitle("Settings")
        }
    }
}

struct WatchlistSettingsView: View {
    @EnvironmentObject var appState: AppState
    
    var body: some View {
        List {
            ForEach(appState.stockWatchlist, id: \.self) { symbol in
                Text(symbol)
            }
            .onDelete { indexSet in
                appState.stockWatchlist.remove(atOffsets: indexSet)
                appState.saveData()
            }
        }
        .navigationTitle("Watchlist")
    }
}
