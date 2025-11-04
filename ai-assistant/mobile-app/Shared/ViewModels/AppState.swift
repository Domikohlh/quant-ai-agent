import Foundation
import SwiftUI

class AppState: ObservableObject {
    @Published var messages: [Message] = []
    @Published var dailyTasks: [Task] = []
    @Published var stockWatchlist: [String] = ["AAPL", "GOOGL", "MSFT"]
    @Published var isLoading = false
    @Published var errorMessage: String?
    
    // Settings
    @Published var useRAG = true
    @Published var selectedTab = 0
    
    init() {
        loadPersistedData()
    }
    
    func loadPersistedData() {
        // Load from UserDefaults or iCloud
        if let savedWatchlist = UserDefaults.standard.array(forKey: "stockWatchlist") as? [String] {
            stockWatchlist = savedWatchlist
        }
    }
    
    func saveData() {
        UserDefaults.standard.set(stockWatchlist, forKey: "stockWatchlist")
    }
}
