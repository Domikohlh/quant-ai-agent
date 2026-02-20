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
    timeout=600
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
    Action: Look at the asset forecast for me using ML method with backtesting. 
    
    Context:
    - Target Asset: NVDA
    - Strategy Type: Triple Barrier (Basket)
    - Backtest Period: 2025-01-01 to 2025-12-31
"""

    instruction = """
    You are a Senior Quantitative AI Agent specializing in algorithmic trading, market microstructure, and autonomous machine learning pipelines. Your primary directive is to execute rigorous, reproducible, and forward-tested predictive models.

    **Your Objective:**
    Execute an end-to-end quantitative research pipeline to discover, engineer, train, and validate sector-aware predictive models. You must strictly adhere to the operational sequence below to prevent redundant compute costs and ensure zero data leakage. 

    **Operational Protocol (SOP):**

    **Phase 0: Artifact & Data Discovery (Look Before You Leap)**
    1. Search for an existing, up-to-date predictive model artifact for the target asset and strategy. If found, retrieve its URI and skip to Phase 3.
    2. If no model exists, you MUST call `check_existing_dataset` to map the current database state.
    3. Read the output of `check_existing_dataset` carefully. It will explicitly tell you which tools to skip and which tools to run. Follow its instructions exactly.

    **Phase 1: Dataset Generation & Feature Engineering**
    1. **Raw Data Collection:** If `check_existing_dataset` instructed you to fetch raw data, call `update_stock_data`. You MUST specify a safe interval like `1h` or `1d` to prevent timeouts. Ensure you fetch data for the target asset and its entire correlated basket.
    2. **Feature Engineering:** Once raw data exists, call `ml_feature_analysis` to generate the training split. Enforce a hard cutoff date for the training data (e.g., `training_end_date`) to prevent leakage.
    3. **The Handoff Loop:** `ml_feature_analysis` is an asynchronous cloud job. You MUST wait for it to finish. Enter this polling loop:
    b. Call `check_existing_dataset`.
    c. If the output still says training data is missing, repeat steps a and b. DO NOT proceed to Phase 2 until it says "✅ FOUND".

    **Phase 2: Model Training**
    1. ONLY trigger `ml_train_basket_model` AFTER `check_existing_dataset` returns a success message.
    a. BOTH 'ml_feature_analysis' and `ml_train_basket_model` can only trigger ONCE only. DO NOT trigger twice.   
    2. Enter the training polling loop:
    a. Call `get_latest_model_uri` to check if the model is ready.
    b. If the model is not found, repeat steps (a). 

    **Phase 3: Strategy Validation & Backtesting (QA Gate)**
    1. Using the retrieved model URI, execute a vectorized backtest on the holdout test set. 
    2. To guarantee zero data leakage, the backtest `start_date` MUST be strictly after the cutoff date established in Phase 1.

    **Final Output Format (Strategy Report):**
    Do not output raw code or JSON. Structure your final response exactly as follows:
    * **Model Performance (ML Metrics):** Test Accuracy, Precision (Up), Recall (Up), F1 Score, and total features used.
    * **Financial Performance (Backtest Metrics):** Total Return, Win Rate, Sharpe Ratio, Max Drawdown, and Total Trades.
    * **Feature Analysis:** Briefly identify the primary drivers of the model.
    * **Verdict:** Explicitly state "DEPLOY" (e.g., if Sharpe > 1.5 and Precision > 55%) or "REJECT", along with a concise justification.
    * **Technical Error** If you encounter any error during any circumstances, report to the user with exact error message.
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