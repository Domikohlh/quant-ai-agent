"use client";

import { CopilotKit } from "@copilotkit/react-core";
import { CopilotChat } from "@copilotkit/react-ui";
import "@copilotkit/react-ui/styles.css";

export default function Home() {
  return (
    // We replace the <main> with a strict screen-sized flex container
    <div className="flex h-screen w-full flex-col bg-gray-50">
      <CopilotKit runtimeUrl="/api/copilotkit" agent="quant_agent">
        
        {/* We removed the 600px wrapper div entirely. 
            className="h-full w-full" tells CopilotKit to fill the screen and manage its own scrollbar */}
        <CopilotChat 
          instructions="You are assisting the user via the dashboard."
          labels={{
            title: "Quant AI Assistant",
            initial: "Hello! The MCP server is connected. What would you like to analyze?",
          }}
          className="h-full w-full"
        />
        
      </CopilotKit>
    </div>
  );
}