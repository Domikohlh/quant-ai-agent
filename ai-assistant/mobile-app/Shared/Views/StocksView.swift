import SwiftUI

struct StocksView: View {
    @EnvironmentObject var appState: AppState
    @State private var stockSummary: StockSummary?
    @State private var isLoading = false
    @State private var showAddStock = false
    @State private var newSymbol = ""
    
    var body: some View {
        NavigationView {
            ScrollView {
                VStack(spacing: 20) {
                    // Watchlist
                    WatchlistSection(
                        symbols: appState.stockWatchlist,
                        onDelete: removeStock,
                        onRefresh: loadStockData
                    )
                    
                    // Summary
                    if let summary = stockSummary {
                        SummarySection(summary: summary)
                    }
                    
                    if isLoading {
                        ProgressView("Loading stock data...")
                    }
                }
                .padding()
            }
            .navigationTitle("Stocks")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Menu {
                        Button(action: loadStockData) {
                            Label("Refresh", systemImage: "arrow.clockwise")
                        }
                        
                        Button(action: { showAddStock = true }) {
                            Label("Add Symbol", systemImage: "plus")
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                }
            }
            .sheet(isPresented: $showAddStock) {
                AddStockView(onAdd: addStock)
            }
            .onAppear {
                if stockSummary == nil {
                    loadStockData()
                }
            }
        }
    }
    
    func loadStockData() {
        guard !appState.stockWatchlist.isEmpty else { return }
        
        isLoading = true
        
        Task {
            do {
                let summary = try await APIService.shared.getStockSummary(
                    symbols: appState.stockWatchlist
                )
                
                await MainActor.run {
                    stockSummary = summary
                    isLoading = false
                }
                
            } catch {
                await MainActor.run {
                    appState.errorMessage = error.localizedDescription
                    isLoading = false
                }
            }
        }
    }
    
    func addStock(symbol: String) {
        let uppercased = symbol.uppercased()
        if !appState.stockWatchlist.contains(uppercased) {
            appState.stockWatchlist.append(uppercased)
            appState.saveData()
            loadStockData()
        }
    }
    
    func removeStock(at offsets: IndexSet) {
        appState.stockWatchlist.remove(atOffsets: offsets)
        appState.saveData()
        loadStockData()
    }
}

struct WatchlistSection: View {
    let symbols: [String]
    let onDelete: (IndexSet) -> Void
    let onRefresh: () -> Void
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Watchlist")
                    .font(.title2)
                    .fontWeight(.bold)
                
                Spacer()
                
                Button(action: onRefresh) {
                    Image(systemName: "arrow.clockwise")
                }
            }
            
            if symbols.isEmpty {
                Text("No stocks in watchlist")
                    .foregroundColor(.secondary)
            } else {
                ForEach(symbols, id: \.self) { symbol in
                    HStack {
                        Text(symbol)
                            .font(.headline)
                        Spacer()
                        Image(systemName: "chevron.right")
                            .foregroundColor(.secondary)
                    }
                    .padding()
                    .background(Color.gray.opacity(0.1))
                    .cornerRadius(8)
                }
            }
        }
    }
}

struct SummarySection: View {
    let summary: StockSummary
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("AI Analysis")
                .font(.title2)
                .fontWeight(.bold)
            
            Text(summary.summary)
                .padding()
                .background(Color.blue.opacity(0.1))
                .cornerRadius(12)
            
            // Stock data cards
            ForEach(summary.rawData.stocks) { stock in
                StockCard(stock: stock)
            }
            
            // News section
            if !summary.rawData.news.isEmpty {
                Text("Latest News")
                    .font(.title3)
                    .fontWeight(.semibold)
                    .padding(.top)
                
                ForEach(summary.rawData.news.prefix(5)) { news in
                    NewsCard(news: news)
                }
            }
        }
    }
}

struct StockCard: View {
    let stock: StockData
    
    var priceChange: Double {
        stock.close - stock.open
    }
    
    var priceChangePercent: Double {
        (priceChange / stock.open) * 100
    }
    
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(stock.symbol)
                    .font(.headline)
                
                Spacer()
                
                VStack(alignment: .trailing) {
                    Text("$\(stock.close, specifier: "%.2f")")
                        .font(.title3)
                        .fontWeight(.bold)
                    
                    HStack(spacing: 4) {
        Image(systemName: priceChange >= 0 ? "arrow.up.right" : "arrow.down.right")
                        Text("\(priceChangePercent, specifier: "%.2f")%")
                    }
                    .foregroundColor(priceChange >= 0 ? .green : .red)
                    .font(.caption)
                }
            }
            
            HStack(spacing: 16) {
                VStack(alignment: .leading) {
                    Text("High")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Text("$\(stock.high, specifier: "%.2f")")
                        .font(.subheadline)
                }
                
                VStack(alignment: .leading) {
                    Text("Low")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Text("$\(stock.low, specifier: "%.2f")")
                        .font(.subheadline)
                }
                
                VStack(alignment: .leading) {
                    Text("Volume")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Text("\(stock.volume)")
                        .font(.subheadline)
                }
            }
        }
        .padding()
        .background(Color.gray.opacity(0.05))
        .cornerRadius(12)
    }
}

struct NewsCard: View {
    let news: StockNews
    
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(news.headline)
                .font(.headline)
            
            Text(news.summary)
                .font(.subheadline)
                .foregroundColor(.secondary)
                .lineLimit(3)
            
            Link("Read more", destination: URL(string: news.url)!)
                .font(.caption)
        }
        .padding()
        .background(Color.gray.opacity(0.05))
        .cornerRadius(8)
    }
}

struct AddStockView: View {
    @Environment(\.dismiss) var dismiss
    @State private var symbol = ""
    let onAdd: (String) -> Void
    
    var body: some View {
        NavigationView {
            Form {
                Section {
                    TextField("Stock Symbol (e.g., AAPL)", text: $symbol)
                        .textInputAutocapitalization(.characters)
                }
            }
            .navigationTitle("Add Stock")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Cancel") {
                        dismiss()
                    }
                }
                
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Add") {
                        onAdd(symbol)
                        dismiss()
                    }
                    .disabled(symbol.isEmpty)
                }
            }
        }
    }
}
