//
//  Item.swift
//  AIAssistant
//
//  Created by Domiko HLH on 4/11/2025.
//

import Foundation
import SwiftData

@Model
final class Item {
    var timestamp: Date
    
    init(timestamp: Date) {
        self.timestamp = timestamp
    }
}
