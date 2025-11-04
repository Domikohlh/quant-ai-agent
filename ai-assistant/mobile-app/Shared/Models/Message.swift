import Foundation

struct Message: Identifiable, Codable {
    let id: UUID
    let text: String
    let isUser: Bool
    let timestamp: Date
    var isLoading: Bool = false
    
    init(id: UUID = UUID(), text: String, isUser: Bool, timestamp: Date = Date(), isLoading: Bool = false) {
        self.id = id
        self.text = text
        self.isUser = isUser
        self.timestamp = timestamp
        self.isLoading = isLoading
    }
}
