import SwiftUI

struct TasksView: View {
    @EnvironmentObject var appState: AppState
    @State private var isGeneratingPlan = false
    @State private var showAddTask = false
    @State private var selectedTask: Task?
    
    var body: some View {
        NavigationView {
            VStack {
                if appState.dailyTasks.isEmpty {
                    EmptyTasksView(isGenerating: $isGeneratingPlan, generateAction: generateDailyPlan)
                } else {
                    TaskListView(tasks: appState.dailyTasks, onTaskTap: { task in
                        selectedTask = task
                    })
                }
            }
            .navigationTitle("Today's Tasks")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Menu {
                        Button(action: generateDailyPlan) {
                            Label("Generate Daily Plan", systemImage: "wand.and.stars")
                        }
                        
                        Button(action: { showAddTask = true }) {
                            Label("Add Task", systemImage: "plus")
                        }
                        
                        Button(role: .destructive, action: clearTasks) {
                            Label("Clear All", systemImage: "trash")
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                }
            }
            .sheet(item: $selectedTask) { task in
                TaskDetailView(task: task)
            }
            .sheet(isPresented: $showAddTask) {
                AddTaskView()
            }
        }
    }
    
    func generateDailyPlan() {
        isGeneratingPlan = true
        
        Task {
            do {
                // Get calendar events (you'll need to implement calendar access)
                let calendarEvents: [[String: String]] = []
                
                // Get user priorities (could be from settings)
                let priorities = ["Complete work projects", "Exercise", "Read"]
                
                let plan = try await APIService.shared.getDailyPlan(
                    calendarEvents: calendarEvents,
                    priorities: priorities,
                    context: "Focus on productivity"
                )
                
                await MainActor.run {
                    appState.dailyTasks = plan.tasks
                    isGeneratingPlan = false
                }
                
            } catch {
                await MainActor.run {
                    appState.errorMessage = error.localizedDescription
                    isGeneratingPlan = false
                }
            }
        }
    }
    
    func clearTasks() {
        appState.dailyTasks.removeAll()
    }
}

struct EmptyTasksView: View {
    @Binding var isGenerating: Bool
    let generateAction: () -> Void
    
    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: "checklist")
                .font(.system(size: 60))
                .foregroundColor(.gray)
            
            Text("No tasks for today")
                .font(.title2)
                .fontWeight(.semibold)
            
            Text("Generate a daily plan based on your calendar and priorities")
                .multilineTextAlignment(.center)
                .foregroundColor(.secondary)
                .padding(.horizontal)
            
            Button(action: generateAction) {
                HStack {
                    if isGenerating {
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: .white))
                    } else {
                        Image(systemName: "wand.and.stars")
                    }
                    Text(isGenerating ? "Generating..." : "Generate Daily Plan")
                }
                .padding()
                .frame(maxWidth: .infinity)
                .background(Color.blue)
                .foregroundColor(.white)
                .cornerRadius(12)
            }
            .disabled(isGenerating)
            .padding(.horizontal)
        }
    }
}

struct TaskListView: View {
    let tasks: [Task]
    let onTaskTap: (Task) -> Void
    
    var body: some View {
        List {
            ForEach(tasks) { task in
                TaskRow(task: task)
                    .onTapGesture {
                        onTaskTap(task)
                    }
            }
        }
    }
}

struct TaskRow: View {
    let task: Task
    @State private var isCompleted: Bool
    
    init(task: Task) {
        self.task = task
        self._isCompleted = State(initialValue: task.isCompleted)
    }
    
    var body: some View {
        HStack {
            Button(action: { isCompleted.toggle() }) {
                Image(systemName: isCompleted ? "checkmark.circle.fill" : "circle")
                    .foregroundColor(isCompleted ? .green : .gray)
                    .font(.title3)
            }
            
            VStack(alignment: .leading, spacing: 4) {
                Text(task.title)
                    .font(.headline)
                    .strikethrough(isCompleted)
                
                HStack {
                    Label(task.estimatedTime, systemImage: "clock")
                    
                    Circle()
                        .fill(priorityColor(task.priority))
                        .frame(width: 8, height: 8)
                    
                    Text(task.priority.rawValue.capitalized)
                }
                .font(.caption)
                .foregroundColor(.secondary)
                
                if let suggestedTime = task.suggestedTime {
                    Label(suggestedTime, systemImage: "calendar")
                        .font(.caption)
                        .foregroundColor(.blue)
                }
            }
            
            Spacer()
        }
        .padding(.vertical, 4)
    }
    
    func priorityColor(_ priority: Task.Priority) -> Color {
        switch priority {
        case .high: return .red
        case .medium: return .orange
        case .low: return .green
        }
    }
}

struct TaskDetailView: View {
    let task: Task
    @Environment(\.dismiss) var dismiss
    
    var body: some View {
        NavigationView {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    // Title
                    Text(task.title)
                        .font(.title)
                        .fontWeight(.bold)
                    
                    // Priority
                    HStack {
                        Text("Priority:")
                            .fontWeight(.semibold)
                        Spacer()
                        Text(task.priority.rawValue.capitalized)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 6)
                            .background(priorityColor(task.priority).opacity(0.2))
                            .foregroundColor(priorityColor(task.priority))
                            .cornerRadius(8)
                    }
                    
                    // Time
                    HStack {
                        Text("Estimated Time:")
                            .fontWeight(.semibold)
                        Spacer()
                        Text(task.estimatedTime)
                    }
                    
                    // Suggested Time
                    if let suggestedTime = task.suggestedTime {
                        HStack {
                            Text("Suggested Time:")
                                .fontWeight(.semibold)
                            Spacer()
                            Text(suggestedTime)
                        }
                    }
                    
                    // Resources
                    if !task.resourcesNeeded.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Resources Needed:")
                                .fontWeight(.semibold)
                            
                            ForEach(task.resourcesNeeded, id: \.self) { resource in
                                HStack {
                                    Image(systemName: "checkmark.circle")
                                        .foregroundColor(.blue)
                                    Text(resource)
                                }
                            }
                        }
                    }
                    
                    // Notes
                    if let notes = task.notes {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Notes:")
                                .fontWeight(.semibold)
                            
                            Text(notes)
                                .padding()
                                .background(Color.gray.opacity(0.1))
                                .cornerRadius(8)
                        }
                    }
                }
                .padding()
            }
            .navigationTitle("Task Details")
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
    
    func priorityColor(_ priority: Task.Priority) -> Color {
        switch priority {
        case .high: return .red
        case .medium: return .orange
        case .low: return .green
        }
    }
}

struct AddTaskView: View {
    @Environment(\.dismiss) var dismiss
    @EnvironmentObject var appState: AppState
    
    @State private var title = ""
    @State private var priority: Task.Priority = .medium
    @State private var estimatedTime = "30 minutes"
    
    var body: some View {
        NavigationView {
            Form {
                Section("Task Details") {
                    TextField("Title", text: $title)
                    
                    Picker("Priority", selection: $priority) {
                        Text("High").tag(Task.Priority.high)
                        Text("Medium").tag(Task.Priority.medium)
                        Text("Low").tag(Task.Priority.low)
                    }
                    
                    TextField("Estimated Time", text: $estimatedTime)
                }
            }
            .navigationTitle("Add Task")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Cancel") {
                        dismiss()
                    }
                }
                
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Add") {
                        let newTask = Task(
                            title: title,
                            priority: priority,
                            estimatedTime: estimatedTime,
                            resourcesNeeded: [],
                            isCompleted: false
                        )
                        appState.dailyTasks.append(newTask)
                        dismiss()
                    }
                    .disabled(title.isEmpty)
                }
            }
        }
    }
}
