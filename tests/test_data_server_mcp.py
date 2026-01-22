from cgitb import text
import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv


# 1. Use the Unified SDK (Supports both API Key and Vertex AI)
from google import genai
from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.runners import InMemoryRunner
from google.genai import types


# --- Path & Env Setup ---
current_test_dir = Path(__file__).resolve().parent
project_root = current_test_dir.parent
server_script_path = project_root / "mcp_server/data_server.py"

load_dotenv(project_root / ".env")

# Ensure GCP Project is set
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION = os.getenv("GCP_REGION", "global")

if not server_script_path.exists():
    raise FileNotFoundError(f"Server script not found at: {server_script_path}")

if not PROJECT_ID:
    raise ValueError("GCP_PROJECT_ID is missing from .env")

os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
os.environ["GOOGLE_CLOUD_LOCATION"] = LOCATION
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

# --- The Vertex AI Agent ---
async def main():
    print(f"\n--- 🔌 Connecting to MCP Server: {server_script_path.name} ---")
    
    # 1. Define Server Parameters (Runs your local python script)
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(server_script_path)],
        env={**os.environ, "PYTHONUNBUFFERED": "1"}
    )

    connection_params = StdioConnectionParams(
        server_params=server_params,
        timeout=10,)
    # 2. Initialize Toolset
    # This automatically "glues" the MCP server tools to the Gemini client
    toolset = McpToolset(
        connection_params=connection_params)

    # 3. Initialize Client in VERTEX AI Mode
    # setting vertexai=True tells the SDK to use your GCP Project Quota & Auth
    client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=LOCATION
    )
    
    print(f"✅ Client initialized for Vertex AI Project: {PROJECT_ID}")

    model_id = "gemini-3-flash-preview" 
    user_query = "Analyze NVDA technicals (1mo, 1h). I specifically need MACD (12,26,9) and VWAP data. If there is an error, state the error message."

    print(f"\n🗣️  User Query: {user_query}")
    print("-" * 50)

    # 4. Run Generation with Tools
    # The 'async with' block ensures the MCP server subprocess is managed correctly
    model = Gemini(model=model_id, client=client)
    agent = LlmAgent(
        model=model,
        name="quant_agent",
        instruction="You are a professional Quantitative Analyst. Your job is to fetch technical indicators and summarize them for a trader.",
        tools=[toolset]
    )
    
    runner = InMemoryRunner(agent=agent)
    try:
        # --- EXECUTION ---
        # run_debug prints output directly to the console
        response = await runner.run_debug(user_query, verbose=False)

        print("\n" + "="*40)
        print("📊 Concise Summary")
        print("="*40)

        # 2. Iterate to find what code (Tools) was called
        tool_calls_found = False
        for turn in response:
            # Check safely for function_call in the turn content
            if hasattr(turn, 'content') and turn.content and hasattr(turn.content, 'parts'):
                for part in turn.content.parts:
                    if hasattr(part, 'function_call') and part.function_call:
                        tool_calls_found = True
                        print(f"\n🛠️  Code Called: {part.function_call.name}")
                        print(f"    Arguments: {part.function_call.args}")

        if not tool_calls_found:
            print("\n(No tools were called in this session)")

        # 3. Print ONLY the Final Text Response
        if response:
            last_turn = response[-1]
            # Dig for the text in the last turn
            if hasattr(last_turn, 'content') and last_turn.content and hasattr(last_turn.content, 'parts'):
                for part in last_turn.content.parts:
                    if hasattr(part, 'text') and part.text:
                        print(f"\n🤖 Agent Response:\n{part.text}")
        
        print("\n" + "="*40)

    except Exception as e:
        print(f"\n❌ Error during execution: {e}")
    
    finally:
        # --- 🛠️ FIX 2: Explicit Cleanup to prevent RuntimeError ---
        print("\n🔌 Closing MCP Server connection...")
        # We must manually close the toolset so 'anyio' doesn't panic at shutdown
        if hasattr(toolset, 'close'):
            await toolset.close()
        # Fallback: if .close() isn't exposed on your ADK version, 
        # try closing the internal session manager
        elif hasattr(toolset, '_session_manager') and hasattr(toolset._session_manager, 'close'):
             await toolset._session_manager.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        # Ignore the "Event loop is closed" noise if it happens after successful run
        if "Event loop is closed" not in str(e):
            print(f"Runtime Warning: {e}")