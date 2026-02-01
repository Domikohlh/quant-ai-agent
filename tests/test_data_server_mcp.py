from cgitb import text
import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv


# 1. Google Agent + MCP tools
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
        timeout=300,)
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
    user_query = """

    Task: Execute the following 2-step pipeline to retrain the model and evaluate if the signal-to-noise ratio has improved.

    Step 1: Basket Feature Engineering (Triple Barrier) Call ml_feature_analysis with the following rigorous settings:

    Target: NVDA

    Basket: NVDA,AMD,INTC,MSFT,TSM (We want the model to learn general semiconductor/tech price physics).

    Barrier Width: 1.0 (Target is a 1 standard deviation move).

    Time Horizon: 5 (The move must happen within 5 bars).

    Correlation Threshold: 0.85 (Remove redundant features).

    Step 2: Train & Test Call ml_train_directional_model for NVDA.

    Note: The tool will automatically detect and load the "Basket Train" and "Target Test" datasets created in Step 1.

    Analysis Request: After training, compare the results to our previous baseline (which was ~50.4% Accuracy).

    Did Accuracy improve? (We are looking for >53%).

    Check the Precision: Is the model better at predicting "Up" moves (Class 1) specifically?

    Feature Stability: Which features survived the selection process across the whole basket?

    Explanation of the Strategy

    Why these specific stocks? NVDA, AMD, INTC, and TSM share the same semiconductor supply chain cycle. MSFT represents the "AI demand" side.

    Why Barrier 1.0 / Horizon 5? This filters out the "noise" (small 0.1% moves) that confused the previous model. We are telling the AI: "Only learn from moves that are statistically significant."
    """

    instruction = """
    You are a Quantitative Researcher expertise in Machine learning. 
    Your goal is to improve the directional prediction model for NVDA by moving from a single-stock approach to a "Sector-Aware" approach using the Triple Barrier Method
    """

    print(f"\n🗣️  User Query: {user_query}")
    print("-" * 50)

    # 4. Run Generation with Tools
    # The 'async with' block ensures the MCP server subprocess is managed correctly
    model = Gemini(model=model_id, client=client)
    agent = LlmAgent(
        model=model,
        name="quant_agent",
        instruction=instruction,
        tools=[toolset],
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