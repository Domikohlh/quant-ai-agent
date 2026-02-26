"use client";

import { CopilotKit } from "@copilotkit/react-core";
import { CopilotChat } from "@copilotkit/react-ui";
import "@copilotkit/react-ui/styles.css";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24 bg-gray-50">
      <div className="z-10 w-full max-w-5xl items-center justify-center font-mono text-sm flex">
        
        {/* Change the agent name to "default" right here 👇 */}
        <CopilotKit runtimeUrl="/api/copilotkit" agent="quant_agent">
          
          <div className="w-full max-w-2xl h-[600px] border border-gray-200 rounded-lg shadow-lg overflow-hidden bg-white">
            <CopilotChat 
              instructions="You are assisting the user via the dashboard."
              labels={{
                title: "Quant AI Assistant",
                initial: "Hello! The MCP server is connected. What would you like to analyze?",
              }}
            />
          </div>
          
        </CopilotKit>

      </div>
    </main>
  );
}