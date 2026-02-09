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
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams, SseConnectionParams
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
LOCATION = os.getenv("GCP_AI_REGION", "global")
DATA_SERVER_URL = os.getenv("DATA_SERVER_URL")

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
    
    connection_params = SseConnectionParams(
    url=DATA_SERVER_URL, 
    # Optional: Add headers if your server requires auth (e.g. Cloud Run)
    headers={
        "Authorization": "Bearer YOUR_TOKEN"
    },
    timeout=300
)

# 2. Initialize Toolset
# This connects to the remote server via SSE instead of spawning a local process
    toolset = McpToolset(
        connection_params=connection_params
    )

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

    Task: Execute the following 2-step pipeline to retrain the model for NVDA.

    Strict Constraints:
    1. Only use the tools provided. Do not hallucinate tool names.
    2. If a tool fails, stop and report the exact error message.
    3. If Step 1 fails, do NOT proceed to Step 2.

    Step 1: Basket Feature Engineering
    Call the tool `ml_feature_analysis` with these rigorous settings to generate the dataset:
    - Target: "NVDA"
    - Basket: "NVDA,AMD,INTC,MSFT,TSM" (Semiconductor supply chain & AI demand).
    - Barrier Width: 1.0 (Targeting a 1 standard deviation move).
    - Time Horizon: 5 (Move must happen within 5 bars).
    - Top N: 15 (Keep top 15 features).

    Step 2: Train Model
    Once Step 1 is confirmed successful, call `ml_train_basket_model`.
    - Target: "NVDA"
    - Run Remote: True

    Analysis Request:
    After the training tool returns the results, analyze the JSON output:
    1. Did Accuracy improve over the baseline of 50.4%? (Target > 53%)
    2. Check Precision: Is the model reliable when predicting "Up" moves?
    3. Feature Stability: List the top features that the model selected."
    """

    instruction = """
    You are a Senior Quantitative Researcher specializing in Machine Learning and Market Microstructure. 

    **Your Objective:** Validate whether a "Sector-Aware" Triple Barrier strategy outperforms the baseline single-stock model for NVDA. You are moving from a univariate approach to a multivariate approach by incorporating peer price physics (AMD, INTC, MSFT, TSM).

    **Operational Protocol:**
    1.  **Strict Tool Usage:** You may ONLY use the tools provided in your toolset (`ml_feature_analysis`, `ml_train_basket_model`, `update_stock_data`, etc.). 
        * Do NOT invent new tool names (e.g., do not call `get_prediction` or `ml_train_directional_model`).
        * If a tool is missing, report the limitation immediately.
    2.  **Dependency Management:** * You MUST run `ml_feature_analysis` (Step 1) successfully before attempting `ml_train_basket_model` (Step 2).
        * If Step 1 fails, STOP and report the error. Do not proceed to training.
    3.  **Scope Limit:** * Your task is **Training and Evaluation ONLY**. 
        * Do NOT attempt to make live predictions or trade calls after training.
        * STOP once you have analyzed the accuracy and feature importance from Step 2.

    **The Strategy (Triple Barrier):**
    * **Concept:** We label data based on volatility. A "Class 1" (Buy) is only generated if the price hits the upper barrier (1.0 std dev) before the vertical barrier (Time Horizon).
    * **Sector Hypothesis:** We believe NVDA's price moves are statistically coupled with its supply chain (TSM) and competitors (AMD, INTC).

    **Output Format:**
    When reporting results, structure your response as:
    * **Observation:** (What strictly happened in the tool output)
    * **Metrics:** (Accuracy, Precision, Recall vs Baseline)
    * **Feature Importance:** (Which specific peer stocks drove the prediction?)
    * **Conclusion:** (Deploy or Discard?)
    """

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