from cgitb import text
import os
import sys
import logging
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

#logging.basicConfig(
#    level=logging.DEBUG,
#    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
#    handlers=[logging.StreamHandler(sys.stdout)]
#)

# Specifically boost the noise for the MCP and ADK libraries
#logging.getLogger("google.adk").setLevel(logging.DEBUG)
#logging.getLogger("mcp").setLevel(logging.DEBUG)
#logging.getLogger("httpcore").setLevel(logging.DEBUG) # Shows raw network requests
 
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

# Avoid rate limits and temorary service unavailability 
retry_config = types.HttpRetryOptions(
    attempts=5,  # Maximum retry attempts
    exp_base=7,  # Delay multiplier
    initial_delay=1,
    http_status_codes=[429, 500, 503, 504],  # Retry on these HTTP errors
)

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
    Action: Retrain and validate the Sector-Aware Model for NVDA.
    
    Context:
    - Target Asset: NVDA
    - Strategy Type: Triple Barrier (Basket)
    - Backtest Period: 2025-01-01 to 2025-12-31
"""

    instruction = """
    You are a Senior Quantitative Researcher. You execute strict algorithmic pipelines.

    **CRITICAL TOOL SAFETY RULES:**
    1. Use ONLY: `get_latest_model_uri`, `ml_feature_analysis`, `ml_train_basket_model`, `backtest_model_strategy`.
    2. Do NOT hallucinate filenames. If you don't have a URI, you cannot backtest.

    **STANDARD OPERATING PROCEDURE (SOP):**

    **Phase 0: Discovery (Mandatory)**
    * **Tool:** `get_latest_model_uri(ticker="NVDA")`
    * **Logic:** * If it returns a URI (e.g., `gs://...`), **SKIP Phase 1 & 2**. Go straight to Phase 3.
        * If it returns "None", proceed to Phase 1.

    **Phase 1: Feature Engineering**
    * **Tool:** `ml_feature_analysis` (Basket="NVDA,AMD,INTC,MSFT,TSM", Barrier=1.0, Horizon=5, Run_Remote=True)

    **Phase 2: Model Training**
    * **Tool:** `ml_train_basket_model` (Target="NVDA", Run_Remote=True)
    * **WAIT:** The training is asynchronous. It takes time.
    * **Retrieval:** After triggering training, you MUST call `get_latest_model_uri("NVDA")` again to get the NEW filename. 
    * **Loop:** If `get_latest_model_uri` still returns "None" or the old model, wait and retry fetching the URI. Do NOT retrain.

    **Phase 3: Strategy Backtesting (QA)**
    * **Tool:** `backtest_model_strategy`
    * **Mandatory Params:**
        * `model_uri`: (The exact URI you retrieved in Phase 0 or Phase 2).
        * `start_date`: "2024-01-01", `end_date`: "2024-12-31"

    **FINAL VERDICT:**
    * Provide the full Machine learning evaluation metrics
    * Report the Accuracy and Sharpe Ratio.
    * Provide your verdict *BUY/*SELL/*HOLD for NVDA based on the news sentiment, machine learning metrics and backtest result

    **Technical error:**
    * Report the exact technical error message to the user if there is any. 
    """

    # 4. Run Generation with Tools
    # The 'async with' block ensures the MCP server subprocess is managed correctly
    model = Gemini(model=model_id, client=client, retry_options=retry_config)
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