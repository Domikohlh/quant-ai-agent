import Foundation

struct Task: Identifiable, Codable {
    let id: UUID
    let title: String
    let priority: Priority
    let estimatedTime: String
    let resourcesNeeded: [String]
    let suggestedTime: String?
    let notes: String?
    var isCompleted: Bool
    
    enum Priority: String, Codable {
        case high = "high"
        case medium = "medium"
        case low = "low"
        
        var color: String {
            switch self {
            case .high: return "red"
            case .medium: return "orange"
            case .low: return "green"
            }
        }
    }
    
    init(id: UUID = UUID(), title: String, priority: Priority, estimatedTime: String, resourcesNeeded: [String], suggestedTime: String? = nil, notes: String? = nil, isCompleted: Bool = false) {
        self.id = id
        self.title = title
        self.priority = priority
        self.estimatedTime = estimatedTime
        self.resourcesNeeded = resourcesNeeded
        self.suggestedTime = suggestedTime
        self.notes = notes
        self.isCompleted = isCompleted
    }
}

struct DailyPlan: Codable {
    let tasks: [Task]
    let dailySummary: String
    
    enum CodingKeys: String, CodingKey {
        case tasks
        case dailySummary = "daily_summary"
    }
}
