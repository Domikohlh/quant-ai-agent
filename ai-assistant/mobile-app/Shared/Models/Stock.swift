import Foundation

struct StockData: Identifiable, Codable {
    let id = UUID()
    let symbol: String
    let open: Double
    let high: Double
    let low: Double
    let close: Double
    let volume: Int
    let timestamp: String
}

struct StockNews: Identifiable, Codable {
    let id = UUID()
    let headline: String
    let summary: String
    let url: String
    let createdAt: String
    
    enum CodingKeys: String, CodingKey {
        case headline, summary, url
        case createdAt = "created_at"
    }
}

struct StockSummary: Codable {
    let summary: String
    let rawData: RawData
    
    struct RawData: Codable {
        let stocks: [StockData]
        let news: [StockNews]
    }
    
    enum CodingKeys: String, CodingKey {
        case summary
        case rawData = "raw_data"
    }
}
