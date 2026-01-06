# agent.py
import os
from google import genai
from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.runners import InMemoryRunner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters
import asyncio # <--- 1. Import this
import sys
import fastmcp
import warnings

# 1. Hide the specific warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="google.adk")
warnings.filterwarnings("ignore", category=UserWarning, module="google.adk")
warnings.filterwarnings("ignore", category=DeprecationWarning, message="Inheritance class AiohttpClientSession from ClientSession is discouraged")

# --- CONFIGURATION ---
os.environ["GOOGLE_CLOUD_PROJECT"] = "quant-ai-agent-482111"
os.environ["GOOGLE_CLOUD_LOCATION"] = "global" # Changed to us-central1 (global is often invalid for Vertex location)
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
# ---------------------

# 1. CONNECT TO YOUR CUSTOM SERVER
# We tell the agent: "Use 'uv' to run 'server.py' in this folder"
server_params = StdioServerParameters(
    command=sys.executable,
    args=["testing_mcp.py"],
    cwd="."
)
connection_params = StdioConnectionParams(server_params=server_params)
mcp_tools = McpToolset(connection_params=connection_params)

# 2. SETUP THE AGENT
client = genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ["GOOGLE_CLOUD_LOCATION"])
model = Gemini(model="gemini-3-pro-preview", client=client)

agent = LlmAgent(
    name="WallStreetBot",
    model=model,
    instruction="""
    You are a stock market assistant. 
    1. If asked for a price, just show the price.
    2. If asked "should I buy?", check the fundamentals (P/E ratio) and News.
    """,
    tools=[mcp_tools] # <--- Inject your custom tools here
)

async def main():
    # Initialize runner inside the async function usually safer
    runner = InMemoryRunner(agent=agent)

    print("--- Agent Ready (Type 'quit' to exit) ---")
    
    while True:
        # standard input() blocks the loop, but it's fine for this simple CLI
        user_input = str(input("\nYou: "))
        if user_input.lower() in ["quit", "exit"]:
            break
        
        try:
            # <--- 2. USE 'await' HERE
            response = await runner.run_debug(user_input)
            
            # The structure of response might vary, usually run_debug prints automatically
            # or returns a simple object. If it doesn't print, uncomment below:
            # print(f"Agent: {response.text}")
            
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    # <--- 3. START THE ASYNC LOOP
    asyncio.run(main())
