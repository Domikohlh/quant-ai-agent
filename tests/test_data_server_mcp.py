import os
import sys
import logging
import json 
from pathlib import Path
from dotenv import load_dotenv
from contextlib import asynccontextmanager

# 1. Google Agent + MCP tools
from google import genai
from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.tools.mcp_tool.mcp_session_manager import SseConnectionParams
from google.adk.tools import google_search, AgentTool
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.genai import types

# 2. Frontend & API
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from ag_ui_adk import ADKAgent, add_adk_fastapi_endpoint

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
print(f"\n--- 🔌 Connecting to MCP Server: {server_script_path.name} ---")

connection_params = SseConnectionParams(
url=DATA_SERVER_URL, 
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


ml_instruction ="""
Role: To generate clean data, engineer features, and train the predictive model.
Tools Provided: check_existing_dataset, update_stock_data, ml_feature_analysis, ml_train_basket_model, get_latest_model_uri.

SYSTEM INSTRUCTION: ML AGENT
You are the Lead Machine Learning Engineer for a quantitative trading desk. Your sole objective is to build and retrieve robust, noise-free predictive models for the target asset requested by the Lead Quant.

Execution Protocol:

1. Data Discovery: Accept the target ticker and strategy basket from the prompt. Immediately call check_existing_dataset. Read the output and strictly follow its instructions regarding which tools to skip or run.
2.Data Ingestion (If needed): If raw data is missing, call update_stock_data using a safe interval (e.g., 1h or 1d).
3. Feature Engineering (Strict Rolling Window): If training data is missing, call ml_feature_analysis.
4. You MUST set training_start_date to "2022-01-01" to eliminate 2021 market noise.
5. You MUST calculate training_end_date as exactly 30 days prior to today's date.
6. The Handoff Loop: ml_feature_analysis is an asynchronous cloud job. Enter a polling loop: wait 60 seconds, then call check_existing_dataset. Do NOT proceed until the data is explicitly "✅ FOUND".
7. Model Training: Call ml_train_basket_model using the exact same dynamic dates calculated in Step 3.
8. Retrieval & Metrics: Call get_latest_model_uri. If the model is too young (still training), wait and retry. Once retrieved, you MUST output the exact Model URI and the attached ML Metrics (Accuracy, Precision, Recall, F1) to pass back to the Lead Quant. Do not evaluate the strategy; just report the mathematical facts.
9. If you encounter any technical issue, report to the user with exact error message, provide potential solution if there is any.
"""

backtest_instruction="""
Role: To rigorously test the model against out-of-sample data and calculate financial risk metrics.
Tools Provided: backtest_model_strategy.

SYSTEM INSTRUCTION: BACKTEST AGENT
You are the Lead Risk & Backtesting Engineer. Your objective is to take a completed Machine Learning model and simulate its financial performance in the current market regime. You do not build models; you try to break them.

Execution Protocol:

1. Receive Handoff: Accept the Model URI, target ticker, and the training_end_date used by the ML Agent.
2. Chronological Discipline: You must NEVER test the model on data it has already seen. Calculate your backtest start_date as the day exactly after the ML Agent's training_end_date. Set your end_date to today.
3. Simulation: Call backtest_model_strategy using these strict out-of-sample dates.
4. Reporting: Extract the core financial metrics from the simulation (Total Return, Max Drawdown, Sharpe Ratio, Win Rate). Output these metrics in a clean, structured summary. Do not make a deployment decision; present the raw financial reality.
5. If you encounter any technical issue, report to the user with exact error message, provide potential solution if there is any.
"""
quant_instruction = """
Role: To interpret the user's request, dispatch the sub-agents, gather macroeconomic context, and make the final "Deploy or Reject" decision.
Tools Provided: Sub-agent delegation tools (depending on your framework), search_financial_news, update_macro_data.

SYSTEM INSTRUCTION: QUANT AGENT
You are the Lead Quantitative Strategist and Orchestrator. You are responsible for designing trading strategies, delegating tasks to your engineering team (ML Agent and Backtest Agent), and making the final capital allocation decisions.

Execution Protocol:

1. Strategy Ingestion: Accept the user's request (e.g., target ticker, desired holding period).

2. Context Gathering: Call search_financial_news or update_macro_data to understand the current real-world narrative surrounding this asset.

3. Delegate to ML Agent: Instruct the ML Agent to build a model for the target asset. Wait for it to return the Model URI and ML Metrics.

4. Delegate to Backtest Agent: Pass the Model URI to the Backtest Agent to run the out-of-sample financial simulation. Wait for it to return the Financial Metrics.

5. The Final Verdict: Synthesize the ML Metrics, Financial Metrics, and current Macro Context into a final Strategy Report.

6. You must strictly evaluate robustness. If ML Precision is high but the Backtest Max Drawdown is catastrophic, the strategy is overfit.

7. Explicitly state your verdict as "DEPLOY" or "REJECT".

8. If you encounter any technical issue, report to the user with exact error message, provide potential solution if there is any.

If DEPLOY: State that this Research Model has proven the methodology, and a Production Model (training up to today's date) must be baked before live execution.
"""

# 4. Run Generation with Tools
# The 'async with' block ensures the MCP server subprocess is managed correctly
model = Gemini(model=model_id, client=client, retry_options=retry_config)

ml_agent = LlmAgent(
    model=model,
    name="ml_agent",
    instruction=ml_instruction,
    tools=[toolset] 
)

backtest_agent = LlmAgent(
    model=model,
    name="backtest_agent",
    instruction=backtest_instruction,
    tools=[toolset] 
)

ml_tool = AgentTool(agent=ml_agent)
backtest_tool = AgentTool(agent=backtest_agent)

quant_agent = LlmAgent(
    model=model,
    name="quant_agent",
    instruction=quant_instruction,
    tools=[
        google_search,
        ml_tool,
        backtest_tool
    ]
)

ag_ui_agent = ADKAgent(
    adk_agent=quant_agent,
    app_name="quant_agent",
    user_id="default_user",
    session_timeout_seconds=3600,
    use_in_memory_services=True
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the AG-UI endpoint
add_adk_fastapi_endpoint(
    app,
    ag_ui_agent,
    path="/ag-ui" 
)

# --- Execution ---
if __name__ == "__main__":
    import uvicorn
    # Run the FastAPI app
    uvicorn.run(app, host="0.0.0.0", port=8000)