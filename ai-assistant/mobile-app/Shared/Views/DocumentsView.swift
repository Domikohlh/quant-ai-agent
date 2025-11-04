import SwiftUI
import UniformTypeIdentifiers

struct DocumentsView: View {
    @EnvironmentObject var appState: AppState
    @State private var documents: [String] = []
    @State private var isLoading = false
    @State private var showFilePicker = false
    @State private var showQuery = false
    @State private var queryText = ""
    @State private var queryResult = ""
    
    var body: some View {
        NavigationView {
            VStack {
                if documents.isEmpty {
                    EmptyDocumentsView(showFilePicker: $showFilePicker)
                } else {
                    List {
                        ForEach(documents, id: \.self) { doc in
                            HStack {
                                Image(systemName: "doc.fill")
                                Text(doc)
                                Spacer()
                            }
                        }
                    }
                }
            }
            .navigationTitle("Documents")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Menu {
                        Button(action: { showFilePicker = true }) {
                            Label("Upload Document", systemImage: "plus")
                        }
                        
                        Button(action: { showQuery = true }) {
                            Label("Query Documents", systemImage: "magnifyingglass")
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                }
            }
            .fileImporter(
                isPresented: $showFilePicker,
                allowedContentTypes: [.pdf, .plainText, .rtf],
                allowsMultipleSelection: false
            ) { result in
                handleFileSelection(result)
            }
            .sheet(isPresented: $showQuery) {
                QueryDocumentsView(queryText: $queryText, result: $queryResult)
            }
        }
    }
    
    func handleFileSelection(_ result: Result<[URL], Error>) {
        switch result {
        case .success(let urls):
            guard let url = urls.first else { return }
            uploadDocument(url)
            
        case .failure(let error):
            appState.errorMessage = error.localizedDescription
        }
    }
    
    func uploadDocument(_ url: URL) {
        isLoading = true
        
        Task {
            do {
                // Ensure we have access to the file
                guard url.startAccessingSecurityScopedResource() else {
                    throw NSError(domain: "FileAccess", code: -1, userInfo: [NSLocalizedDescriptionKey: "Cannot access file"])
                }
                
                defer { url.stopAccessingSecurityScopedResource() }
                
                let filename = try await APIService.shared.uploadDocument(fileURL: url)
                
                await MainActor.run {
                    documents.append(filename)
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
}

struct EmptyDocumentsView: View {
    @Binding var showFilePicker: Bool
    
    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: "doc.text")
                .font(.system(size: 60))
                .foregroundColor(.gray)
            
            Text("No documents uploaded")
                .font(.title2)
                .fontWeight(.semibold)
            
            Text("Upload documents to ask questions and get AI-powered insights")
                .multilineTextAlignment(.center)
                .foregroundColor(.secondary)
                .padding(.horizontal)
            
            Button(action: { showFilePicker = true }) {
                Label("Upload Document", systemImage: "plus")
                    .padding()
                    .frame(maxWidth: .infinity)
                    .background(Color.blue)
                    .foregroundColor(.white)
                    .cornerRadius(12)
            }
            .padding(.horizontal)
        }
    }
}

struct QueryDocumentsView: View {
    @Environment(\.dismiss) var dismiss
    @Binding var queryText: String
    @Binding var result: String
    @State private var isQuerying = false
    
    var body: some View {
        NavigationView {
            VStack(spacing: 20) {
                TextField("Ask a question about your documents", text: $queryText, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(3...6)
                    .padding()
                
                Button(action: queryDocuments) {
                    HStack {
                        if isQuerying {
                            ProgressView()
                                .progressViewStyle(CircularProgressViewStyle(tint: .white))
                        }
                        Text(isQuerying ? "Searching..." : "Search")
                    }
                    .padding()
                    .frame(maxWidth: .infinity)
                    .background(queryText.isEmpty ? Color.gray : Color.blue)
                    .foregroundColor(.white)
                    .cornerRadius(12)
                }
                .disabled(queryText.isEmpty || isQuerying)
                .padding(.horizontal)
                
                if !result.isEmpty {
                    ScrollView {
                        Text(result)
                            .padding()
                    }
                    .background(Color.gray.opacity(0.1))
                    .cornerRadius(12)
                    .padding()
                }
                
                Spacer()
            }
            .navigationTitle("Query Documents")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
        }
    }
    
    func queryDocuments() {
        isQuerying = true
        
        Task {
            do {
                let response = try await APIService.shared.sendMessage(
                    queryText,
                    useRAG: true
                )
                
                await MainActor.run {
                    result = response
                    isQuerying = false
                }
                
            } catch {
                await MainActor.run {
                    result = "Error: \(error.localizedDescription)"
                    isQuerying = false
                }
            }
        }
    }
}
