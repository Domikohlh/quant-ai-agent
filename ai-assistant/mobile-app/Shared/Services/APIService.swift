import Foundation

class APIService {
    static let shared = APIService()
    
    private let baseURL = "http://YOUR_SERVER_IP:3000/api" // Replace with your actual server
    private let apiKey = "your-gateway-api-key" // Store in Keychain in production
    
    private init() {}
    
    // MARK: - Chat
    func sendMessage(_ message: String, useRAG: Bool = false, context: String? = nil) async throws -> String {
        let url = URL(string: "\(baseURL)/assistant/chat")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(apiKey, forHTTPHeaderField: "X-Api-Key")
        
        let body: [String: Any] = [
            "message": message,
            "use_rag": useRAG,
            "context": context as Any
        ]
        
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            throw APIError.invalidResponse
        }
        
        let decoded = try JSONDecoder().decode(ChatResponse.self, from: data)
        return decoded.response
    }
    
    // MARK: - Tasks
    func getDailyPlan(calendarEvents: [[String: String]], priorities: [String], context: String = "") async throws -> DailyPlan {
        let url = URL(string: "\(baseURL)/tasks/daily-plan")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(apiKey, forHTTPHeaderField: "X-Api-Key")
        
        let body: [String: Any] = [
            "calendar_events": calendarEvents,
            "priorities": priorities,
            "context": context
        ]
        
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            throw APIError.invalidResponse
        }
        
        let decoded = try JSONDecoder().decode(DailyPlanResponse.self, from: data)
        return decoded.plan
    }
    
    // MARK: - Stocks
    func getStockSummary(symbols: [String]) async throws -> StockSummary {
        let url = URL(string: "\(baseURL)/stocks/summary")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(apiKey, forHTTPHeaderField: "X-Api-Key")
        
        let body: [String: Any] = ["symbols": symbols]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            throw APIError.invalidResponse
        }
        
        return try JSONDecoder().decode(StockSummary.self, from: data)
    }
    
    // MARK: - RAG
    func uploadDocument(fileURL: URL) async throws -> String {
        let url = URL(string: "\(baseURL)/rag/upload")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(apiKey, forHTTPHeaderField: "X-Api-Key")
        
        let boundary = UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(fileURL.lastPathComponent)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: application/octet-stream\r\n\r\n".data(using: .utf8)!)
        body.append(try Data(contentsOf: fileURL))
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        
        request.httpBody = body
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            throw APIError.invalidResponse
        }
        
        let decoded = try JSONDecoder().decode(UploadResponse.self, from: data)
        return decoded.filename
    }
    
    // MARK: - Helper Structs
    struct ChatResponse: Codable {
        let response: String
        let tokensUsed: Int
        let usedRAG: Bool
        
        enum CodingKeys: String, CodingKey {
            case response
            case tokensUsed = "tokens_used"
            case usedRAG = "used_rag"
        }
    }
    
    struct DailyPlanResponse: Codable {
        let plan: DailyPlan
        let date: String
        let weather: String
    }
    
    struct UploadResponse: Codable {
        let status: String
        let filename: String
        let chunksCreated: Int
        
        enum CodingKeys: String, CodingKey {
            case status, filename
            case chunksCreated = "chunks_created"
        }
    }
    
    enum APIError: Error {
        case invalidResponse
        case networkError
    }
}
