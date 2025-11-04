import SwiftUI

struct ChatView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var networkMonitor: NetworkMonitor
    @StateObject private var offlineModel = OfflineModelService()
    
    @State private var messageText = ""
    @State private var isProcessing = false
    
    var body: some View {
        VStack {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 12) {
                        ForEach(appState.messages) { message in
                            MessageBubble(message: message)
                                .id(message.id)
                        }
                    }
                    .padding()
                }
                .onChange(of: appState.messages.count) { _ in
                    if let lastMessage = appState.messages.last {
                        withAnimation {
                            proxy.scrollTo(lastMessage.id, anchor: .bottom)
                        }
                    }
                }
            }
            
            // Input area
            HStack {
                TextField("Ask me anything...", text: $messageText, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(1...4)
                    .disabled(isProcessing)
                
                Button(action: sendMessage) {
                    Image(systemName: isProcessing ? "hourglass" : "arrow.up.circle.fill")
                        .font(.title2)
                        .foregroundColor(messageText.isEmpty ? .gray : .blue)
                }
                .disabled(messageText.isEmpty || isProcessing)
            }
            .padding()
        }
        .navigationTitle("AI Assistant")
    }

   func sendMessage() {
        guard !messageText.isEmpty else { return }
        
        let userMessage = Message(text: messageText, isUser: true)
        appState.messages.append(userMessage)
        
        let queryText = messageText
        messageText = ""
        isProcessing = true
        
        // Add loading message
        let loadingMessage = Message(text: "Thinking...", isUser: false, isLoading: true)
        appState.messages.append(loadingMessage)
        
        Task {
            do {
                let response: String
                
                if networkMonitor.isConnected {
                    // Use online model
                    response = try await APIService.shared.sendMessage(
                        queryText,
                        useRAG: appState.useRAG
                    )
                } else {
                    // Use offline model
                    response = await offlineModel.generate(queryText)
                }
                
                await MainActor.run {
                    // Remove loading message
                    appState.messages.removeAll { $0.isLoading }
                    
                    // Add AI response
                    let aiMessage = Message(text: response, isUser: false)
                    appState.messages.append(aiMessage)
                    
                    isProcessing = false
                }
                
            } catch {
                await MainActor.run {
                    appState.messages.removeAll { $0.isLoading }
                    
                    let errorMessage = Message(
                        text: "Sorry, I encountered an error: \(error.localizedDescription)",
                        isUser: false
                    )
                    appState.messages.append(errorMessage)
                    
                    isProcessing = false
                }
            }
        }
    }
}

struct MessageBubble: View {
    let message: Message
    
    var body: some View {
        HStack {
            if message.isUser { Spacer() }
            
            VStack(alignment: message.isUser ? .trailing : .leading, spacing: 4) {
                Text(message.text)
                    .padding(12)
                    .background(message.isUser ? Color.blue : Color.gray.opacity(0.2))
                    .foregroundColor(message.isUser ? .white : .primary)
                    .cornerRadius(16)
                
                if message.isLoading {
                    ProgressView()
                        .progressViewStyle(CircularProgressViewStyle())
                }
                
                Text(message.timestamp, style: .time)
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
            
            if !message.isUser { Spacer() }
        }
    }
}
